"""DMX Worker нишка: отваря .wds файла, отброява 40 ms интервали и пише в порта.

UI нишката никога не докосва серийния порт или файла директно - тя изпраща
команди през опашка (load/play/pause/stop) и чете състоянието със snapshot().
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

from audio import AudioError, NullAudio, find_audio
from dmx_engine import BLACKOUT, DMXError
from wds_parser import DEFAULT_FPS, WDSError, WDSFile, WDSInfo  # noqa: F401

# Последните ~2 ms преди кадъра се изчакват активно за по-малък jitter.
SPIN_MARGIN = 0.002


DROP_LOG = "/dev/shm/wds_drops.log" if os.path.isdir("/dev/shm") else os.path.join(
    os.environ.get("TMPDIR", "/tmp"), "wds_drops.log")


def _read_first(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return "?"


def _throttled() -> str:
    """Флагове за throttling/ниско напрежение на Pi (0x0 = ОК)."""
    v = _read_first("/sys/devices/platform/soc/soc:firmware/get_throttled")
    if v != "?":
        return v
    try:
        import subprocess
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True,
                             timeout=1).stdout.strip()
        return out.split("=")[-1] or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def log_drop(idx: int, skipped: int, late_ms: float) -> None:
    """Записва пропуснати кадри (рядко събитие) с признаци за причината: натоварване,
    температура и флагове за throttling/ниско напрежение на Raspberry Pi."""
    try:
        if os.path.exists(DROP_LOG) and os.path.getsize(DROP_LOG) > 200_000:
            os.unlink(DROP_LOG)
        temp = _read_first("/sys/class/thermal/thermal_zone0/temp")
        thr = _read_first("/sys/devices/platform/soc/soc:firmware/get_throttled")
        with open(DROP_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" кадър={idx} пропуснати={skipped} "
                    f"закъснение={late_ms:.0f}ms load={os.getloadavg()[0]:.2f} "
                    f"temp={temp} throttled={thr}\n")
    except OSError:
        pass


def _try_realtime() -> bool:
    """Работната нишка получава реално-времеви приоритет (ако правата позволяват),
    за да не я изместват mpv и интерфейсът. Без права просто остава нормална."""
    try:
        os.sched_setscheduler(0, os.SCHED_RR, os.sched_param(20))
        return True
    except (AttributeError, OSError):
        return False


def next_start(schedule, now: datetime) -> datetime | None:
    """Следващият автоматичен старт за (включен, час, минута, секунда) или None."""
    enabled, h, m, sec = schedule
    if not enabled:
        return None
    candidate = now.replace(hour=h, minute=m, second=sec, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


class State(str, Enum):
    IDLE = "IDLE"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"


STATE_LABELS = {
    State.IDLE: "ГОТОВНОСТ (IDLE)",
    State.PLAYING: "ВЪЗПРОИЗВЕЖДАНЕ (PLAYING)",
    State.PAUSED: "ПАУЗА (PAUSED)",
}


@dataclass(frozen=True)
class Snapshot:
    state: State = State.IDLE
    info: WDSInfo | None = None
    frame_index: int = 0          # следващ кадър за изпращане
    position: float = 0.0         # секунди от началото на шоуто
    dropped_frames: int = 0       # пропуснати кадри поради закъснение
    error: str | None = None
    output_ok: bool = False
    last_frame: bytes = BLACKOUT  # последно изпратеният DMX кадър
    audio_path: str | None = None  # звуков файл към шоуто (None = без звук)
    loop_number: int = 0          # кое поред възпроизвеждане върви (1 = първото; 0 = спряно)
    waiting_until: float = 0.0    # perf_counter() край на паузата между повторенията (0 = няма)
    load_count: int = 0           # колко команди "load" са обработени (успешни или не)

    @property
    def elapsed(self) -> float:
        return self.position

    @property
    def remaining(self) -> float:
        return max(0.0, self.info.duration - self.elapsed) if self.info else 0.0

    @property
    def progress(self) -> float:
        if not self.info or not self.info.duration:
            return 0.0
        return min(1.0, self.position / self.info.duration)


class DMXPlayer:
    def __init__(self, output, fps: int = DEFAULT_FPS, hold_on_pause: bool = True, audio=None):
        """
        output        - DMXOutput или NullDMXOutput
        fps           - честота за суров .wds формат и за опресняване при пауза;
                        при формата със записи времената идват от файла
        audio         - AudioPlayer (mpv) или NullAudio; None = без звук
        hold_on_pause - при ПАУЗА текущият кадър продължава да се опреснява
                        (повечето тела гасят при загуба на DMX сигнал).
                        False = при пауза излъчването спира напълно.
        """
        self._output = output
        self._fps = fps
        self._period = 1.0 / fps
        self._pause_mode = "hold" if hold_on_pause else "off"   # hold | blackout | off
        self._stop_mode = "blackout"                            # blackout | hold | off
        self._audio = audio if audio is not None else NullAudio()
        self._loops = 1                  # 0 = безкрайно, 1 = веднъж, N = N пъти
        self._loop_gap = 0               # секунди между повторенията (Blackout)
        self._schedule = (False, 0, 0, 0)  # (включен, час, минута, секунда) - всеки ден
        self._cmd: queue.Queue = queue.Queue()
        self._snap_lock = threading.Lock()
        self._snap = Snapshot()
        self._thread = threading.Thread(target=self._run, name="DMXWorker", daemon=True)

    # ---------------- API за UI нишката ----------------
    def start(self) -> None:
        self._thread.start()

    def load(self, path: str, audio: str | None = None) -> None:
        """audio - ръчно избран звуков файл; None = автоматично търсене до .wds"""
        self._cmd.put(("load", path, audio))

    def set_audio(self, path: str | None) -> None:
        """Ръчно сменя звука на заредено шоу; None = обратно към автоматичния."""
        self._cmd.put(("audio", path))

    def play(self) -> None:
        self._cmd.put(("play",))

    def pause(self) -> None:
        self._cmd.put(("pause",))

    def stop(self) -> None:
        self._cmd.put(("stop",))

    # Настройките могат да се сменят и по време на възпроизвеждане.
    @property
    def loops(self) -> int:
        return self._loops

    # --- DMX поведение ---
    PAUSE_MODES = ("hold", "blackout", "off")
    STOP_MODES = ("blackout", "hold", "off")

    def set_pause_mode(self, mode: str) -> None:
        """Пауза: hold = последният кадър се опреснява, blackout = тъмно (сигналът остава),
        off = излъчването спира."""
        if mode in self.PAUSE_MODES:
            self._pause_mode = mode

    def set_stop_mode(self, mode: str) -> None:
        """Стоп: blackout = всички канали 0, hold = последният кадър остава, off = излъчването спира."""
        if mode in self.STOP_MODES:
            self._stop_mode = mode

    def set_fps(self, fps: int) -> None:
        """Честота на кадрите за суров формат и за опресняване при пауза/задържане
        (при .wds със записи времената идват от файла)."""
        self._fps = max(1, min(44, int(fps)))
        self._period = 1.0 / self._fps

    def set_channels(self, n: int) -> None:
        """Брой DMX канали в пакета (24..512); по-малко канали = по-кратък пакет."""
        setter = getattr(self._output, "set_channels", None)
        if setter is not None:
            setter(n)

    def set_loops(self, n: int) -> None:
        """Повторения: 0 = безкрайно, 1 = веднъж (като Loops в Depence)."""
        self._loops = max(0, int(n))

    @property
    def loop_gap(self) -> int:
        return self._loop_gap

    def set_loop_gap(self, seconds: int) -> None:
        self._loop_gap = max(0, int(seconds))

    @property
    def schedule(self) -> tuple:
        return self._schedule

    def set_schedule(self, enabled: bool, h: int = 0, m: int = 0, s: int = 0) -> None:
        """Автоматичен старт всеки ден в h:m:s (системно местно време)."""
        self._schedule = (bool(enabled), int(h) % 24, int(m) % 60, int(s) % 60)

    def set_audio_offset(self, ms: int) -> None:
        """Синхрон на звука в милисекунди: + = звукът по-рано, - = по-късно."""
        setter = getattr(self._audio, "set_offset", None)
        if setter:
            setter(int(ms) / 1000.0)

    def set_volume(self, percent: int) -> None:
        """Сила на звука 0..100 %."""
        setter = getattr(self._audio, "set_volume", None)
        if setter:
            setter(int(percent))

    @property
    def loop(self) -> bool:
        """Съвместимост: има ли повторение (повече от едно възпроизвеждане)."""
        return self._loops != 1

    def set_loop(self, enabled: bool) -> None:
        self._loops = 0 if enabled else 1

    def shutdown(self, timeout: float = 2.0) -> None:
        self._cmd.put(("quit",))
        if self._thread.is_alive():
            self._thread.join(timeout)

    def snapshot(self) -> Snapshot:
        with self._snap_lock:
            return self._snap

    # ---------------- Worker нишка ----------------
    def _publish(self, **changes) -> None:
        with self._snap_lock:
            self._snap = replace(self._snap, **changes)

    def _send(self, frame: bytes) -> None:
        if not self._output_ok:
            return
        try:
            self._output.send(frame)
        except DMXError as e:
            self._output_ok = False
            self._publish(output_ok=False, error=str(e))

    def _run(self) -> None:
        self.realtime = _try_realtime()
        self._output_ok = False
        try:
            self._output.open()
            self._output_ok = True
            self._publish(output_ok=True)
            self._send(BLACKOUT)
        except DMXError as e:
            self._publish(output_ok=False, error=str(e))

        wds: WDSFile | None = None
        wds_path = ""
        state = State.IDLE
        idx = 0
        t0 = 0.0  # perf_counter() момент, съответстващ на началото на шоуто (0 s)
        dropped = 0
        last_frame = BLACKOUT
        loops_done = 0            # завършени възпроизвеждания в тази серия
        restart_audio = False     # звукът трябва да тръгне отначало със следващия кадър 0
        last_sched = None
        sched_target: datetime | None = None
        loads = 0
        holding = False           # след Стоп в режим „задръж“: последният кадър се опреснява

        def due_time(i: int) -> float:
            """Кога (s от началото) се изпраща кадър i; i == брой кадри -> краят."""
            return wds.frame_time(i) if i < wds.frame_count else wds.info.duration

        def set_state(new_state, **extra):
            nonlocal state
            state = new_state
            extra.setdefault("position", due_time(idx) if wds and idx else 0.0)
            self._publish(state=state, frame_index=idx, dropped_frames=dropped, **extra)

        def audio_call(method, *args):
            try:
                getattr(self._audio, method)(*args)
            except AudioError as e:
                self._publish(error=str(e))
            err = getattr(self._audio, "last_error", None)  # асинхронна грешка от mpv
            if err:
                self._publish(error=err)
                self._audio.last_error = None

        def apply_audio(override):
            """Избира и зарежда звука към текущото шоу (ръчен или автоматичен)."""
            manual = override if override and os.path.isfile(override) else None
            path = manual or find_audio(wds_path, wds.info.audio_file)
            if path:
                audio_call("load", path)
            else:
                audio_call("unload")
            self._publish(audio_path=path)
            if not path and wds.info.audio_file:
                self._publish(error=f"Звуковият файл „{wds.info.audio_file}“ не е намерен до шоуто")

        def start_play():
            nonlocal t0, loops_done, restart_audio, holding
            holding = False
            if state is State.IDLE:
                loops_done = 0
            pos = due_time(idx)
            restart_audio = False
            audio_call("play", pos)                 # първо звукът...
            t0 = time.perf_counter() - pos          # ...после часовникът на DMX (без закъснението на командата)
            set_state(State.PLAYING, loop_number=loops_done + 1, waiting_until=0.0)

        def do_stop():
            nonlocal idx, last_frame, loops_done, restart_audio, holding
            idx = 0
            loops_done = 0
            restart_audio = False
            mode = self._stop_mode
            holding = mode == "hold" and any(last_frame)
            if mode == "blackout" or (mode == "hold" and not holding):
                last_frame = BLACKOUT
                self._send(BLACKOUT)
            elif mode == "off":
                last_frame = BLACKOUT          # излъчването спира (нищо не се праща)
            audio_call("stop")
            set_state(State.IDLE, last_frame=last_frame, loop_number=0, waiting_until=0.0)

        while True:
            # --- колко можем да чакаме команда ---
            if state is State.PLAYING:
                timeout = t0 + due_time(idx) - time.perf_counter() - SPIN_MARGIN
            elif state is State.PAUSED and self._pause_mode != "off":
                timeout = self._period
            elif state is State.IDLE and holding:
                timeout = self._period
            else:
                timeout = 0.5
            if state is State.IDLE and sched_target is not None:
                timeout = min(timeout, max(0.0, (sched_target - datetime.now()).total_seconds()))

            try:
                cmd = self._cmd.get(timeout=timeout) if timeout > 0 else self._cmd.get_nowait()
            except queue.Empty:
                cmd = None

            if cmd is not None:
                name = cmd[0]
                if name == "quit":
                    self._send(BLACKOUT)
                    if wds:
                        wds.close()
                    self._output.close()
                    self._audio.close()
                    return
                if name == "load":
                    if state is not State.IDLE:
                        do_stop()
                    if wds:
                        wds.close()
                        wds = None
                    try:
                        wds = WDSFile(cmd[1], fps=self._fps)
                        wds_path = cmd[1]
                        idx, dropped, loops_done = 0, 0, 0
                        self._publish(info=wds.info, frame_index=0, dropped_frames=0, position=0.0,
                                      loop_number=0, waiting_until=0.0, audio_path=None,
                                      error=None if self._output_ok else self._snap.error)
                        apply_audio(cmd[2] if len(cmd) > 2 else None)
                    except (WDSError, OSError) as e:
                        self._publish(info=None, frame_index=0, position=0.0, audio_path=None,
                                      error=str(e))
                        audio_call("unload")
                    loads += 1
                    self._publish(load_count=loads)  # сигнал към GUI: зареждането приключи
                elif name == "audio":
                    if wds is not None:
                        if state is not State.IDLE:
                            do_stop()
                        self._publish(error=None if self._output_ok else self._snap.error)
                        apply_audio(cmd[1])
                elif name == "play":
                    if wds is None:
                        self._publish(error="Няма зареден .wds файл")
                    elif state is not State.PLAYING:
                        start_play()
                elif name == "pause":
                    if state is State.PLAYING:
                        audio_call("pause")
                        set_state(State.PAUSED)
                elif name == "stop":
                    do_stop()
                continue

            # --- график: автоматичен старт всеки ден в зададения час ---
            sched = self._schedule
            if sched != last_sched:
                last_sched = sched
                sched_target = next_start(sched, datetime.now())
            if sched_target is not None:
                now_dt = datetime.now()
                if now_dt >= sched_target:
                    late = (now_dt - sched_target).total_seconds()
                    sched_target = next_start(sched, now_dt)
                    # late > 5 s = скок на часовника (напр. NTP след старт) - не стартираме
                    if late < 5 and state is State.IDLE and wds is not None:
                        start_play()
                        continue

            # --- изтекъл таймаут: време е за действие ---
            if state is State.PLAYING:
                if idx >= wds.frame_count:  # последният кадър е изтекъл - край
                    loops_done += 1
                    if self._loops == 0 or loops_done < self._loops:
                        # Безшевно повторение: часовникът се измества с точно една
                        # дължина на шоуто + паузата (без натрупване на грешка).
                        gap = self._loop_gap
                        t0 += wds.info.duration + gap
                        idx = 0
                        restart_audio = True
                        changes = dict(frame_index=0, position=0.0, loop_number=loops_done + 1,
                                       waiting_until=t0 if gap > 0 else 0.0)
                        if gap > 0:  # пауза между повторенията: Blackout
                            last_frame = BLACKOUT
                            self._send(BLACKOUT)
                            changes["last_frame"] = BLACKOUT
                        self._publish(**changes)
                        continue
                    self._publish(position=wds.info.duration)
                    do_stop()
                    continue
                due = t0 + wds.frame_time(idx)
                now = time.perf_counter()
                while now < due:
                    now = time.perf_counter()
                if restart_audio:  # нов цикъл: звукът тръгва отначало заедно с кадър 0
                    restart_audio = False
                    audio_call("play", max(0.0, now - t0))
                # Ако следващият кадър също вече е закъснял - прескачаме, за да
                # остане шоуто синхронизирано с реалното време (важно за аудио).
                skipped = 0
                while idx + 1 < wds.frame_count and t0 + wds.frame_time(idx + 1) <= now:
                    idx += 1
                    dropped += 1
                    skipped += 1
                if skipped:
                    log_drop(idx, skipped, (now - due) * 1000)
                try:
                    frame = wds.read_frame(idx)
                except (WDSError, OSError) as e:
                    self._publish(error=f"Грешка при четене: {e}")
                    do_stop()
                    continue
                self._send(frame)
                last_frame = frame
                idx += 1
                self._publish(frame_index=idx, dropped_frames=dropped, last_frame=frame,
                              position=time.perf_counter() - t0, waiting_until=0.0)
            elif state is State.PAUSED and self._pause_mode != "off":
                self._send(last_frame if self._pause_mode == "hold" else BLACKOUT)
            elif state is State.IDLE and holding:
                self._send(last_frame)
