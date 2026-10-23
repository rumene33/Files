"""Запазвани настройки на плейъра (JSON във ~/.config/wds_player/settings.json).

Пазят се повторенията, паузата между тях, автостартът по час, последно
зареденото шоу и ръчно избраните звукови файлове - за да работи автостартът
и след рестарт на Raspberry Pi.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date as _date

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".config", "wds_player", "settings.json")

# --- графици (като TimePlaner в Depence) и цифрови входове (като DI 0..7 на WECS) ---
MAX_TIMERS = 8
DI_COUNT = 8
DEFAULT_PINS = (5, 6, 13, 19, 26, 16, 20, 21)           # BCM; без 14/15 (UART на DMX)
VALID_PINS = tuple(p for p in range(2, 28) if p not in (14, 15))
COMMANDS = ("NoAction", "Play", "Pause", "Stop", "TogglePlay", "VolumeUp", "VolumeDown", "PlayShow")


def default_inputs() -> list:
    return [{"pin": p, "pos": {"cmd": "NoAction", "param": ""},
             "neg": {"cmd": "NoAction", "param": ""}} for p in DEFAULT_PINS]


def new_timer() -> dict:
    """Нов график: всеки ден в 12:00:00, текущото шоу."""
    return {"on": True, "days": list(range(7)), "date": "", "h": 12, "m": 0, "s": 0, "show": "",
            "end_on": False, "eh": 13, "em": 0, "es": 0}


def _int(v, lo, hi, default):
    try:
        return min(hi, max(lo, int(v)))
    except (TypeError, ValueError):
        return default


def clean_timer(d) -> dict | None:
    if not isinstance(d, dict):
        return None
    days = sorted({x for x in d.get("days", range(7)) if isinstance(x, int) and 0 <= x <= 6})
    try:
        day = _date.fromisoformat(str(d.get("date") or "")).isoformat()   # "" = всяка седмица
    except ValueError:
        day = ""
    return {"on": bool(d.get("on", True)), "days": days, "date": day,
            "h": _int(d.get("h"), 0, 23, 12), "m": _int(d.get("m"), 0, 59, 0),
            "s": _int(d.get("s"), 0, 59, 0), "show": str(d.get("show") or ""),
            "end_on": bool(d.get("end_on", False)), "eh": _int(d.get("eh"), 0, 23, 13),
            "em": _int(d.get("em"), 0, 59, 0), "es": _int(d.get("es"), 0, 59, 0)}


def clean_action(d) -> dict:
    d = d if isinstance(d, dict) else {}
    cmd = d.get("cmd") if d.get("cmd") in COMMANDS else "NoAction"
    return {"cmd": cmd, "param": str(d.get("param") or "")}


def clean_inputs(lst) -> list:
    out = default_inputs()
    if isinstance(lst, list):
        for i, d in enumerate(lst[:DI_COUNT]):
            if isinstance(d, dict):
                pin = d.get("pin")
                out[i] = {"pin": pin if pin in VALID_PINS else DEFAULT_PINS[i],
                          "pos": clean_action(d.get("pos")), "neg": clean_action(d.get("neg"))}
    return out


@dataclass
class Settings:
    loops: int = 1                 # 0 = безкрайно, 1 = веднъж (като в Depence: Loops 0=endless)
    loop_gap: int = 0              # секунди между повторенията
    start_enabled: bool = False    # автоматичен старт всеки ден
    start_h: int = 0
    start_m: int = 0
    start_s: int = 0
    audio_offset_ms: int = 0       # синхрон на звука: + = по-рано, - = по-късно
    timers: list = field(default_factory=list)            # до 8 графика (вж. new_timer)
    inputs_enabled: bool = False                           # цифрови входове (GPIO)
    inputs: list = field(default_factory=default_inputs)   # DI 0..7: пин + действие при pos/neg
    volume: int = 100              # сила на звука, %
    planner_enabled: bool = True   # работа по TimePlaner.xml (ако файлът е намерен)
    dmx_fps: int = 25              # честота за суров формат и опресняване при пауза/задържане
    dmx_channels: int = 512        # слотове в DMX пакета (24..512)
    pause_mode: str = "hold"       # hold | blackout | off
    stop_mode: str = "blackout"    # blackout | hold | off
    boot_play: bool = False        # автоматично пускане на шоу при включване
    boot_show: str = ""            # "" = последното заредено шоу
    boot_delay: int = 3            # секунди след старта на плейъра
    system: dict = field(default_factory=dict)   # {"timezone": "...", "net": {устройство: {method, ip, prefix, gw, dns}}}
                                                 # - прилага се наново при старт, когато системата е само за четене
    ask_audio: bool = True         # при зареждане на шоу без песен отвори избора на аудио
    last_file: str = ""
    audio_overrides: dict = field(default_factory=dict)  # {wds път: звуков файл}

    def clamp(self) -> "Settings":
        self.loops = min(999, max(0, int(self.loops)))
        self.loop_gap = min(3600, max(0, int(self.loop_gap)))
        self.start_h = min(23, max(0, int(self.start_h)))
        self.start_m = min(59, max(0, int(self.start_m)))
        self.start_s = min(59, max(0, int(self.start_s)))
        self.audio_offset_ms = min(1000, max(-1000, int(self.audio_offset_ms)))
        self.volume = min(100, max(0, int(self.volume)))
        self.start_enabled = bool(self.start_enabled)
        self.timers = [c for c in (clean_timer(d) for d in (self.timers if isinstance(self.timers, list) else []))
                       if c is not None][:MAX_TIMERS]
        self.inputs_enabled = bool(self.inputs_enabled)
        self.inputs = clean_inputs(self.inputs)
        self.ask_audio = bool(self.ask_audio)
        self.planner_enabled = bool(self.planner_enabled)
        self.dmx_fps = _int(self.dmx_fps, 1, 44, 25)
        self.dmx_channels = _int(self.dmx_channels, 24, 512, 512)
        self.pause_mode = self.pause_mode if self.pause_mode in ("hold", "blackout", "off") else "hold"
        self.stop_mode = self.stop_mode if self.stop_mode in ("blackout", "hold", "off") else "blackout"
        self.boot_play = bool(self.boot_play)
        self.boot_show = str(self.boot_show or "")
        self.boot_delay = _int(self.boot_delay, 0, 300, 3)
        if not isinstance(self.system, dict):
            self.system = {}
        if not isinstance(self.audio_overrides, dict):
            self.audio_overrides = {}
        return self

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        try:
            with open(path or CONFIG_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
            st = cls(**known)
            if st.start_enabled and "timers" not in raw:   # стар единичен автостарт -> график
                st.timers = [{"on": True, "days": list(range(7)), "h": st.start_h,
                              "m": st.start_m, "s": st.start_s, "show": ""}]
            st.start_enabled = False
            return st.clamp()
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: str | None = None) -> None:
        path = path or CONFIG_FILE
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # съдържа Wi‑Fi парола
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())      # на диска преди преименуването - сигурно при спиране на тока
            os.replace(tmp, path)
        except OSError:
            pass  # файлова система само за четене - настройките просто не се помнят
