"""Изпълнява команди от графици и цифрови входове върху плейъра."""

from __future__ import annotations

import os
import time

from player import State


def apply_settings(player, st) -> None:
    """Прилага настройките върху плейъра (повторения, звук, DMX поведение)."""
    player.set_loops(st.loops)
    player.set_loop_gap(st.loop_gap)
    player.set_audio_offset(st.audio_offset_ms)
    player.set_volume(st.volume)
    player.set_fps(st.dmx_fps)
    player.set_channels(st.dmx_channels)
    player.set_pause_mode(st.pause_mode)
    player.set_stop_mode(st.stop_mode)


class Controller:
    def __init__(self, player, settings):
        self.player = player
        self.settings = settings
        self.last_event: tuple | None = None   # (време, вид, ...) - за показване в GUI

    # --- команди ---
    def execute(self, cmd: str, param: str = "") -> None:
        p = self.player
        if cmd == "Play":
            p.play()
        elif cmd == "Pause":
            p.pause()
        elif cmd == "Stop":
            p.stop()
        elif cmd == "TogglePlay":
            if p.snapshot().state is State.PLAYING:
                p.pause()
            else:
                p.play()
        elif cmd in ("VolumeUp", "VolumeDown"):
            v = min(100, max(0, self.settings.volume + (5 if cmd == "VolumeUp" else -5)))
            self.settings.volume = v
            p.set_volume(v)
            self.settings.save()
        elif cmd == "PlayShow" and param:
            self._play_show(param)

    def _play_show(self, path: str) -> None:
        self.settings.last_file = path
        p = self.player
        p.load(path, self.settings.audio_overrides.get(path))
        p.play()

    def boot_play(self) -> bool:
        """Автоматично пускане при включване: избраното (или последното) шоу, ако плейърът е
        свободен - шоу, което вече е пуснато от TimePlaner (catch-up), не се прекъсва."""
        show = self.settings.boot_show or self.settings.last_file
        if not show or not os.path.isfile(show):
            return False
        if self.player.snapshot().state is not State.IDLE:
            return False
        self.last_event = (time.monotonic(), "timer", os.path.basename(show))
        self._play_show(show)
        return True

    # --- TimePlaner.xml ---
    def on_plan_play(self, path: str, counts: int) -> None:
        """Събитие от TimePlaner: шоуто с неговите повторения (Counts 0 = безкрайно)."""
        self.last_event = (time.monotonic(), "timer", os.path.basename(path))
        self.player.set_loops(counts)
        self._play_show(path)

    def on_plan_stop(self) -> None:
        """„end all“: всичко спира, повторенията се връщат към настройките."""
        self.last_event = (time.monotonic(), "timer_end", "")
        self.player.stop()
        self.player.set_loops(self.settings.loops)

    # --- източници ---
    def on_input(self, index: int, trigger: str) -> None:
        try:
            act = self.settings.inputs[index][trigger]
        except (IndexError, KeyError):
            return
        if act["cmd"] == "NoAction":
            return
        self.last_event = (time.monotonic(), "input", index, trigger, act["cmd"])
        self.execute(act["cmd"], act["param"])

    def on_timer_end(self, tm: dict) -> None:
        """Краят на графика: шоуто и звукът спират (Blackout)."""
        self.last_event = (time.monotonic(), "timer_end", "")
        self.player.stop()
        self.player.set_loops(self.settings.loops)      # повторенията се връщат към настройките

    def on_timer(self, tm: dict) -> None:
        show = tm.get("show") or ""
        if tm.get("end_on"):
            self.player.set_loops(0)    # има край -> шоуто се повтаря до края на графика, не до края на песента
        self.last_event = (time.monotonic(), "timer", os.path.basename(show) if show else "")
        if show:
            self._play_show(show)
        else:                       # текущото шоу - отначало
            self.player.stop()
            self.player.play()
