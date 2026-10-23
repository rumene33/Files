"""Звук (mp3 / mp4 / ...) към шоуто - през mpv, управляван по IPC сокет.

mpv се стартира веднъж и стои в готовност (--idle --pause). Файлът се зарежда
на пауза още при избора на шоуто, така че при СТАРТ остава само да се премести
позицията и да се пусне звукът - това отнема милисекунди, а не секунда и
половина за стартиране на процес. mp4 се възпроизвежда САМО като звук.

Инсталация:  sudo apt install mpv
Избор на изход (3.5 mm жак / HDMI):  mpv --audio-device=help  ->  --audio-device
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time

AUDIO_EXTENSIONS = (".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".flac")


class AudioError(Exception):
    pass


def find_audio(wds_path: str, audio_name: str | None) -> str | None:
    """Намира звуковия файл към шоуто в папката на .wds файла.

    1. името от хедъра на .wds (без значение от главни/малки букви);
    2. резерва: файл със същото име като шоуто (Show.wds -> Show.mp3/.mp4/...).
    """
    folder = os.path.dirname(os.path.abspath(wds_path))
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    lower = {n.lower(): n for n in names}
    if audio_name:
        hit = lower.get(audio_name.replace("\\", "/").rsplit("/", 1)[-1].lower())  # и Windows пътища
        if hit and os.path.isfile(os.path.join(folder, hit)):
            return os.path.join(folder, hit)
    stem = os.path.splitext(os.path.basename(wds_path))[0].lower()
    for ext in AUDIO_EXTENSIONS:
        hit = lower.get(stem + ext)
        if hit and os.path.isfile(os.path.join(folder, hit)):
            return os.path.join(folder, hit)
    return None


class NullAudio:
    """Без звук (тестове, --no-audio). Пази извикванията за проверки."""

    available = True

    def __init__(self):
        self.calls: list[tuple] = []

    def load(self, path):
        self.calls.append(("load", path))

    def unload(self):
        self.calls.append(("unload",))

    def play(self, position):
        self.calls.append(("play", round(position, 3)))

    def pause(self):
        self.calls.append(("pause",))

    def set_offset(self, seconds):
        self.calls.append(("offset", round(seconds, 3)))

    def set_volume(self, percent):
        self.calls.append(("volume", int(percent)))

    def stop(self):
        self.calls.append(("stop",))

    def close(self):
        self.calls.append(("close",))


class AudioPlayer:
    def __init__(self, mpv_cmd=None, audio_device: str | None = None, offset: float = 0.0,
                 connect_timeout: float = 5.0, volume: int = 100):
        """
        mpv_cmd      - команда за mpv (за тестове се подава заместител)
        audio_device - стойност за mpv --audio-device (напр. alsa/plughw:CARD=Headphones)
        offset       - секунди; положително = звукът върви по-напред от DMX
                       (компенсира забавянето на аудио изхода, ~0.1-0.2 s)
        """
        self._cmd = list(mpv_cmd) if mpv_cmd else [shutil.which("mpv") or "mpv"]
        self._device = audio_device
        self._offset = offset
        self._volume = min(100, max(0, int(volume)))
        self._connect_timeout = connect_timeout
        self._sock_path = os.path.join(tempfile.gettempdir(), f"wds_mpv_{os.getpid()}.sock")
        self.log_path = os.path.join(tempfile.gettempdir(), "wds_mpv.log")  # съобщения на mpv (за диагностика)
        self._next_rid = 1
        self._waiting: dict[int, tuple[threading.Event, list]] = {}
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._loaded = threading.Event()
        self._path: str | None = None
        self._lock = threading.Lock()
        self._at_start = True                    # файлът чака в позиция 0 (няма нужда от seek)
        self._timer: threading.Timer | None = None  # отложен старт при отрицателен offset
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return shutil.which(self._cmd[0]) is not None or os.path.isfile(self._cmd[0])

    # ---------------- mpv процес и IPC ----------------
    def _start(self) -> None:
        if self._proc and self._proc.poll() is None and self._sock:
            return
        if not self.available:
            raise AudioError("mpv не е инсталиран: sudo apt install mpv")
        self._teardown()
        args = self._cmd + ["--idle=yes", "--pause", "--keep-open=yes", "--no-video",
                            "--force-window=no", "--no-terminal", "--no-config",
                            f"--input-ipc-server={self._sock_path}", f"--log-file={self.log_path}",
                            f"--volume={self._volume}"]
        if self._device:
            args.append(f"--audio-device={self._device}")
        try:
            self._proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            raise AudioError(f"mpv не може да се стартира: {e}") from e
        deadline = time.monotonic() + self._connect_timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise AudioError("mpv се затвори веднага след стартиране")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(self._sock_path)
                break
            except OSError:
                s.close()
                time.sleep(0.05)
        else:
            self._teardown()
            raise AudioError("Няма връзка с mpv (IPC)")
        self._sock = s
        self._reader = threading.Thread(target=self._read_loop, args=(s,), name="MpvReader", daemon=True)
        self._reader.start()

    def _read_loop(self, sock: socket.socket) -> None:
        buf = b""
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    rid = msg.get("request_id")
                    if rid in self._waiting:           # отговор на query()
                        evt, box = self._waiting.pop(rid)
                        box.append(msg)
                        evt.set()
                        continue
                    ev = msg.get("event")
                    if ev == "file-loaded":
                        self._loaded.set()
                    elif ev == "end-file" and msg.get("reason") == "error":
                        self.last_error = "mpv: грешка при зареждане на звука"
        except OSError:
            return

    def query(self, prop: str, timeout: float = 1.0):
        """Чете свойство на mpv (напр. time-pos, pause, current-ao); None при неуспех."""
        if not self._sock:
            return None
        rid = self._next_rid
        self._next_rid += 1
        evt, box = threading.Event(), []
        self._waiting[rid] = (evt, box)
        try:
            self._send("get_property", prop, request_id=rid)
        except AudioError:
            self._waiting.pop(rid, None)
            return None
        if not evt.wait(timeout):
            self._waiting.pop(rid, None)
            return None
        return box[0].get("data") if box[0].get("error") == "success" else None

    def _send(self, *command, request_id=None) -> None:
        msg = {"command": list(command)}
        if request_id is not None:
            msg["request_id"] = request_id
        payload = (json.dumps(msg) + "\n").encode()
        try:
            with self._lock:
                self._sock.sendall(payload)
        except (OSError, AttributeError) as e:
            self._teardown()
            raise AudioError(f"Връзката с mpv е прекъсната: {e}") from e

    def _teardown(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._loaded.clear()
        try:
            os.unlink(self._sock_path)
        except OSError:
            pass

    # ---------------- API ----------------
    def set_offset(self, seconds: float) -> None:
        """+ = звукът върви по-рано от DMX, - = по-късно (важи от следващия старт)."""
        self._offset = float(seconds)

    def set_volume(self, percent: int) -> None:
        """Сила на звука 0..100 % (важи веднага, дори докато свири)."""
        self._volume = min(100, max(0, int(percent)))
        if self._sock:
            try:
                self._send("set_property", "volume", self._volume)
            except AudioError:
                pass  # mpv не върви; силата се прилага при следващия му старт

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _delayed_unpause(self) -> None:
        self._timer = None
        try:
            self._send("set_property", "pause", False)
        except AudioError:
            pass

    def load(self, path: str) -> None:
        """Зарежда файла на пауза, в позиция 0."""
        self._start()
        self._cancel_timer()
        self._at_start = True
        self._loaded.clear()
        self._path = path
        self.last_error = None
        self._send("loadfile", path, "replace")

    def unload(self) -> None:
        self._path = None
        self._loaded.clear()
        if self._sock:
            self._send("stop")

    def play(self, position: float) -> None:
        if not self._path:
            return
        self._start()
        if not self._loaded.is_set():
            self._loaded.wait(2.0)  # само при най-ранен старт, веднага след избора на файл
        self._cancel_timer()
        target = position + self._offset
        if target < 0:
            # Звукът трябва да закъснее спрямо DMX: чакаме в позиция 0 и пускаме по-късно
            self._send("seek", 0, "absolute")
            self._timer = threading.Timer(-target, self._delayed_unpause)
            self._timer.daemon = True
            self._timer.start()
        else:
            # От позиция 0 няма seek - файлът вече чака там, остава само да се пусне (най-бързо)
            if not (self._at_start and target < 0.005):
                self._send("seek", target, "absolute")
            self._send("set_property", "pause", False)
        self._at_start = False

    def pause(self) -> None:
        self._cancel_timer()
        if self._sock:
            self._send("set_property", "pause", True)

    def stop(self) -> None:
        self._cancel_timer()
        if self._sock and self._path:
            self._send("set_property", "pause", True)
            self._send("seek", 0, "absolute")
            self._at_start = True

    def close(self) -> None:
        self._cancel_timer()
        if self._sock:
            try:
                self._send("quit")
            except AudioError:
                pass
        self._teardown()
