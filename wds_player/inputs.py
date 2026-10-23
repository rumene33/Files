"""Цифрови входове (като DI 0..7 на OASE WECS) през GPIO на Raspberry Pi.

Входът е активен, когато пинът е свързан към GND (бутон/сух контакт; вътрешно
издърпване към 3,3 V). "pos" = входът става активен, "neg" = пуска се.
ВНИМАНИЕ: GPIO пиновете са 3,3 V и не понасят 5 V!
"""

from __future__ import annotations

import threading
import time


class GpioReader:
    """Чете пинове през gpiozero (pull-up, активен при ниво 0)."""

    def __init__(self):
        self._dev = {}
        self.error: str | None = None

    def read(self, pin: int) -> bool:
        dev = self._dev.get(pin)
        if dev is None:
            try:
                from gpiozero import DigitalInputDevice
                dev = self._dev[pin] = DigitalInputDevice(pin, pull_up=True)
            except Exception as e:  # няма gpiozero/lgpio, пинът е зает, не е Raspberry Pi
                self.error = f"GPIO {pin}: {e}"
                return False
        return bool(dev.is_active)

    def release(self, keep=()) -> None:
        for pin in [p for p in self._dev if p not in keep]:
            try:
                self._dev.pop(pin).close()
            except Exception:
                pass

    def close(self) -> None:
        self.release()


class InputMonitor(threading.Thread):
    """Опитва пиновете и вика on_event(индекс, "pos"|"neg") след дебаунс."""

    def __init__(self, get_config, on_event, reader=None, poll: float = 0.01, debounce: float = 0.04,
                 clock=time.monotonic):
        """get_config() -> (включени, [пин за всеки вход])"""
        super().__init__(name="InputMonitor", daemon=True)
        self._get_config = get_config
        self._on_event = on_event
        self._reader = reader or GpioReader()
        self._poll = poll
        self._debounce = debounce
        self._clock = clock
        self._stop_evt = threading.Event()
        self.states: list[bool] = []
        self._pins: list = []
        self._cand: list[bool] = []
        self._since: list[float] = []

    @property
    def error(self) -> str | None:
        return getattr(self._reader, "error", None)

    def step(self) -> None:
        enabled, pins = self._get_config()
        if not enabled:
            if self._pins:
                self._reader.release()
                self._pins = []
            self.states = [False] * len(pins)
            return
        if pins != self._pins:                 # (пре)инициализация - без събития
            self._reader.release(keep=set(pins))
            self._pins = list(pins)
            self.states = [bool(self._reader.read(p)) for p in pins]
            self._cand = list(self.states)
            now = self._clock()
            self._since = [now] * len(pins)
            return
        now = self._clock()
        for i, pin in enumerate(pins):
            raw = bool(self._reader.read(pin))
            if raw == self.states[i]:
                self._cand[i] = raw
            elif raw != self._cand[i]:
                self._cand[i], self._since[i] = raw, now
            elif now - self._since[i] >= self._debounce:
                self.states[i] = raw
                self._on_event(i, "pos" if raw else "neg")

    def run(self) -> None:
        while not self._stop_evt.wait(self._poll):
            try:
                self.step()
            except Exception as e:
                if hasattr(self._reader, "error"):
                    self._reader.error = f"GPIO: {e}"

    def stop(self) -> None:
        self._stop_evt.set()
        try:
            self._reader.close()
        except Exception:
            pass
