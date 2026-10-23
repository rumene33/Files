"""Тъч интерфейс (Tkinter) за WDS DMX плейъра.

Оптимизиран за официалния 7" дисплей 800x480, работи и на по-големи екрани.
"""

from __future__ import annotations

import glob
import os
import time
import tkinter as tk
from datetime import datetime, timedelta

from audio import AUDIO_EXTENSIONS
from i18n import get_lang, t, toggle_lang, tr_error
from controller import Controller, apply_settings
from player import DMXPlayer, State
import power
import timeplaner
import schedule_file
import agenda_ui
import settings_ui
import ui_kit
from scheduler import applies_on, next_fire
from settings import COMMANDS, DI_COUNT, MAX_TIMERS, VALID_PINS, Settings, new_timer
from wds_parser import format_time

UI_REFRESH_MS = 100
MONITOR_CHANNELS = 32

BG = ui_kit.BG
PANEL = ui_kit.CARD
FG = ui_kit.FG
MUTED = ui_kit.MUTED
ACCENT = ui_kit.ACCENT
STATE_COLORS = {State.IDLE: ui_kit.MUTED, State.PLAYING: ui_kit.GREEN, State.PAUSED: ui_kit.ORANGE}
ERROR = ui_kit.RED

FONT = "DejaVu Sans"


def _cover_master(win, master):
    """Прозорецът покрива главния прозорец (удобно за тъч екран)."""
    w, h = master.winfo_width(), master.winfo_height()
    win.geometry(f"{w}x{h}+{master.winfo_rootx()}+{master.winfo_rooty()}")
    if master.attributes("-fullscreen"):
        win.attributes("-fullscreen", True)


def _hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class TouchFileDialog(tk.Toplevel):
    """Едър файлов браузър за тъч екран (стандартният е твърде дребен).

    По подразбиране показва всички файлове; само .wds могат да се отварят,
    останалите са избледнени. Бутонът „Всички файлове“ включва/изключва филтъра.
    """

    show_all = True  # запомня се, докато приложението работи

    def __init__(self, master, start_dir: str, on_select, extensions=(".wds",),
                 title_key="dlg_title", extra=None):
        """extensions - кои файлове могат да се отварят; extra - (надпис, функция) допълнителен бутон"""
        super().__init__(master, bg=BG)
        self.title(t(title_key))
        self.on_select = on_select
        self.extensions = tuple(extensions)
        self.transient(master)
        _cover_master(self, master)

        # Бързи места: папката с шоута + всички USB флашки
        places = tk.Frame(self, bg=BG)
        places.pack(fill="x", padx=8, pady=(8, 4))
        for label, path in self._places(start_dir):
            tk.Button(places, text=label, font=(FONT, 14), bg=PANEL, fg=FG,
                      activebackground=ACCENT, relief="flat", padx=12, pady=8,
                      command=lambda p=path: self.show_dir(p)).pack(side="left", padx=4)

        self.path_var = tk.StringVar()
        tk.Label(self, textvariable=self.path_var, font=(FONT, 12), bg=BG, fg=MUTED,
                 anchor="w").pack(fill="x", padx=12)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        self.listbox = tk.Listbox(body, font=(FONT, 18), bg=PANEL, fg=FG, bd=0,
                                  highlightthickness=0, selectbackground=ACCENT,
                                  activestyle="none")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_tap)
        self.listbox.bind("<Double-Button-1>", lambda e: self._open())

        scroll = tk.Frame(body, bg=BG)
        scroll.pack(side="right", fill="y", padx=(6, 0))
        for text, delta in (("▲", -1), ("▼", 1)):
            tk.Button(scroll, text=text, font=(FONT, 22), width=3, bg=PANEL, fg=FG,
                      relief="flat", command=lambda d=delta: self.listbox.yview_scroll(d, "pages")
                      ).pack(fill="both", expand=True, pady=2)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=8, pady=8)
        btn = dict(font=(FONT, 16, "bold"), relief="flat", padx=16, pady=10, fg="white")
        small = dict(btn, font=(FONT, 13, "bold"), padx=10)
        # „Отвори“ и „Отказ“ се пакетират ПЪРВИ - така винаги остават видими,
        # дори ако страничните бутони не се побират по ширина на екрана.
        self.open_btn = tk.Button(bar, text=t("dlg_open"), bg=ACCENT, state="disabled",
                                  command=self._open, **btn)
        self.open_btn.pack(side="right", padx=(8, 0))
        tk.Button(bar, text=t("dlg_cancel"), bg="#3a3a3c", command=self.destroy, **btn).pack(side="right")
        tk.Button(bar, text=t("dlg_up"), bg=PANEL, command=self._up, **btn).pack(side="left")
        self.filter_btn = tk.Button(bar, bg=PANEL, command=self._toggle_filter, **small)
        self.filter_btn.pack(side="left", padx=6)
        if extra:
            tk.Button(bar, text=extra[0], bg=PANEL, command=lambda: (self.destroy(), extra[1]()),
                      **small).pack(side="left")

        self.entries: list[tuple[str, bool]] = []
        self._update_filter_btn()
        self.show_dir(start_dir if os.path.isdir(start_dir) else os.path.expanduser("~"))
        self.grab_set()

    @staticmethod
    def _places(start_dir):
        places = [(t("dlg_shows"), start_dir)]
        mounts = sorted(set(glob.glob("/media/*/*") + glob.glob("/media/usb*") + glob.glob("/mnt/*")))
        for m in mounts:
            if os.path.isdir(m):
                places.append((t("dlg_usb", name=os.path.basename(m)), m))
        places.append((t("dlg_home"), os.path.expanduser("~")))
        return places

    def show_dir(self, path):
        try:
            names = sorted(os.listdir(path), key=str.lower)
        except OSError as e:
            self.path_var.set(t("dlg_error", e=e))
            return
        self.cwd = path
        self.path_var.set(path)
        dirs = [n for n in names if not n.startswith(".") and os.path.isdir(os.path.join(path, n))]
        if TouchFileDialog.show_all:
            files = [n for n in names if not n.startswith(".") and os.path.isfile(os.path.join(path, n))]
        else:
            files = [n for n in names if self._is_openable(n)]
        self.entries = [(d, True) for d in dirs] + [(f, False) for f in files]
        self.listbox.delete(0, "end")
        for name, is_dir in self.entries:
            self.listbox.insert("end", f"📁  {name}/" if is_dir else f"    {name}")
            if is_dir:
                self.listbox.itemconfig("end", fg="#93c5fd")
            elif not self._is_openable(name):
                self.listbox.itemconfig("end", fg="#6b7280")  # не може да се отвори - само за информация
        if not files and not dirs:
            self.listbox.insert("end", t("dlg_empty_all" if TouchFileDialog.show_all else "dlg_empty"))
        self.open_btn.config(state="disabled")

    def _is_openable(self, name: str) -> bool:
        return name.lower().endswith(self.extensions)

    def _toggle_filter(self):
        TouchFileDialog.show_all = not TouchFileDialog.show_all
        self._update_filter_btn()
        self.show_dir(self.cwd)

    def _update_filter_btn(self):
        if TouchFileDialog.show_all:
            self.filter_btn.config(text=t("dlg_all_on"), bg=ACCENT)
        else:
            self.filter_btn.config(text=t("dlg_all_off"), bg=PANEL)

    def _selected(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self.entries):
            return None
        return self.entries[sel[0]]

    def _on_tap(self, _event):
        entry = self._selected()
        if entry is None:
            return
        name, is_dir = entry
        if is_dir:
            self.show_dir(os.path.join(self.cwd, name))
        else:
            self.open_btn.config(state="normal" if self._is_openable(name) else "disabled")

    def _up(self):
        parent = os.path.dirname(self.cwd.rstrip("/")) or "/"
        self.show_dir(parent)

    def _open(self):
        entry = self._selected()
        if entry and not entry[1] and self._is_openable(entry[0]):
            path = os.path.join(self.cwd, entry[0])
            self.destroy()
            self.on_select(path)


class PowerDialog(tk.Toplevel):
    """Потвърждение за изключване/рестарт на Pi (с голям бутон срещу случайно докосване)."""

    def __init__(self, app: "PlayerApp"):
        super().__init__(app.root, bg=BG)
        self.app = app
        self.title(t("pw_title"))
        self.transient(app.root)
        _cover_master(self, app.root)
        tk.Label(self, text=t("pw_title"), font=(FONT, 22, "bold"), bg=BG, fg=FG).pack(pady=(40, 10))
        tk.Label(self, text=t("pw_text"), font=(FONT, 14), bg=BG, fg=MUTED, justify="center").pack(pady=6)
        self.msg = tk.Label(self, text="", font=(FONT, 14, "bold"), bg=BG, fg=ERROR)
        self.msg.pack(pady=6)
        bar = tk.Frame(self, bg=BG)
        bar.pack(side="bottom", fill="x", padx=20, pady=20)
        for i, (key, color, cmd) in enumerate((
                ("pw_off", "#ff453a", lambda: self._go("poweroff")),
                ("pw_reboot", "#ff9f0a", lambda: self._go("reboot")),
                ("pw_cancel", "#3a3a3c", self.destroy))):
            tk.Button(bar, text=t(key), font=(FONT, 20, "bold"), bg=color, fg="white", relief="flat",
                      pady=14, command=cmd).grid(row=0, column=i, sticky="nsew", padx=6)
            bar.columnconfigure(i, weight=1, uniform="pw")
        self.grab_set()

    def _go(self, action: str):
        self.msg.config(text=t("pw_going"), fg=MUTED)
        self.update_idletasks()
        self.app.player.shutdown()          # DMX към 0 (Blackout), звукът спира
        if power.run(action):
            self.app.root.destroy()
        else:
            self.msg.config(text=t("pw_failed"), fg=ERROR)


class _Spin(tk.Frame):
    """− стойност +  (докосване = стъпка, задържане = автоматично повтаряне)."""

    def __init__(self, master, choices, index, on_change, fmt=str, wrap=True, label_width=5,
                 bg=PANEL, size=15):
        super().__init__(master, bg=bg)
        self.choices, self.index, self.on_change = list(choices), index, on_change
        self.fmt, self.wrap = fmt, wrap
        self._job = None
        btn = dict(font=(FONT, size, "bold"), bg=BG, fg=FG, activebackground=ACCENT,
                   relief="flat", width=2, pady=0)
        minus = tk.Button(self, text="−", **btn)
        minus.pack(side="left")
        self.lbl = tk.Label(self, font=(FONT, size + 2, "bold"), bg=bg, fg=FG, width=label_width)
        self.lbl.pack(side="left", padx=2)
        plus = tk.Button(self, text="+", **btn)
        plus.pack(side="left")
        for b, d in ((minus, -1), (plus, 1)):
            b.bind("<ButtonPress-1>", lambda e, d=d: self._press(d))
            b.bind("<ButtonRelease-1>", lambda e: self._release())
        self._show()

    def _show(self):
        self.lbl.config(text=self.fmt(self.choices[self.index]))

    def _step(self, d):
        n = len(self.choices)
        i = (self.index + d) % n if self.wrap else min(n - 1, max(0, self.index + d))
        if i != self.index:
            self.index = i
            self._show()
            self.on_change(self.choices[i])

    def _press(self, d):
        self._step(d)
        self._release()
        self._job = self.after(450, lambda: self._repeat(d))

    def _repeat(self, d):
        self._step(d)
        self._job = self.after(110, lambda: self._repeat(d))

    def _release(self):
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def destroy(self):
        self._release()
        super().destroy()


def _on_off(btn, on: bool):
    if on:
        btn.config(text=t("set_on"), bg="#30d158", activebackground="#24a844")
    else:
        btn.config(text=t("set_off"), bg="#3a3a3c", activebackground="#48484a")


class InputsDialog(tk.Toplevel):
    """Цифрови входове DI 0..7 (като OASE WECS): GPIO пин и действие при натискане/пускане."""

    def __init__(self, app: "PlayerApp"):
        super().__init__(app.root, bg=BG)
        self.app = app
        self.title(t("di_title"))
        self.transient(app.root)
        _cover_master(self, app.root)

        tk.Button(self, text=t("set_close"), font=(FONT, 17, "bold"), bg=ACCENT, fg="white",
                  relief="flat", pady=4, command=self.destroy).pack(side="bottom", fill="x",
                                                                     padx=12, pady=6)
        self.hint = tk.Label(self, text=t("di_hint"), font=(FONT, 11), bg=BG, fg=MUTED, anchor="w")
        self.hint.pack(side="bottom", fill="x", padx=16)
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(6, 2))
        tk.Label(top, text=t("di_title"), font=(FONT, 16, "bold"), bg=BG, fg=FG).pack(side="left", padx=4)
        self.en_btn = tk.Button(top, font=(FONT, 14, "bold"), fg="white", relief="flat", width=7,
                                command=self._toggle_enabled)
        self.en_btn.pack(side="right")
        self.err = tk.Label(top, text="", font=(FONT, 11), bg=BG, fg=ERROR, anchor="e")
        self.err.pack(side="right", fill="x", expand=True, padx=8)

        rows = tk.Frame(self, bg=BG)
        rows.pack(fill="both", expand=True, padx=12)
        self.dots, self.btns = [], {}
        for i in range(DI_COUNT):
            row = tk.Frame(rows, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"DI{i}", font=(FONT, 13, "bold"), bg=PANEL, fg=FG, width=4,
                     anchor="w").pack(side="left", padx=(8, 0))
            dot = tk.Label(row, text="●", font=(FONT, 14), bg=PANEL, fg=MUTED)
            dot.pack(side="left", padx=4)
            self.dots.append(dot)
            pin = app.settings.inputs[i]["pin"]
            _Spin(row, VALID_PINS, VALID_PINS.index(pin), lambda p, i=i: self._set_pin(i, p),
                  fmt=lambda p: f"GPIO{p}", label_width=7, size=12).pack(side="left", padx=6)
            for trig in ("neg", "pos"):
                b = tk.Button(row, font=(FONT, 12, "bold"), fg="white", relief="flat", width=15,
                              pady=1, command=lambda i=i, k=trig: self._cycle(i, k))
                b.pack(side="right", padx=3, pady=1)
                self.btns[(i, trig)] = b
                self._update_btn(i, trig)
        _on_off(self.en_btn, app.settings.inputs_enabled)
        self._poll()
        self.grab_set()

    # --- текст/цвят на бутоните за действие ---
    def _action_text(self, i, trig):
        act = self.app.settings.inputs[i][trig]
        name = os.path.splitext(os.path.basename(act["param"]))[0] if act["param"] else "?"
        label = t("cmd_" + act["cmd"], name=name[:9]) if act["cmd"] == "PlayShow" else t("cmd_" + act["cmd"])
        return ("▲ " if trig == "pos" else "▼ ") + label

    def _update_btn(self, i, trig):
        idle = self.app.settings.inputs[i][trig]["cmd"] == "NoAction"
        self.btns[(i, trig)].config(text=self._action_text(i, trig),
                                    bg="#3a3a3c" if idle else ACCENT,
                                    activebackground="#48484a" if idle else "#0060df")

    def _set_action(self, i, trig, cmd, param=""):
        self.app.settings.inputs[i][trig] = {"cmd": cmd, "param": param}
        self.app.settings.save()
        self._update_btn(i, trig)

    def _cycle(self, i, trig):
        cur = self.app.settings.inputs[i][trig]["cmd"]
        nxt = COMMANDS[(COMMANDS.index(cur) + 1) % len(COMMANDS)]
        if nxt == "PlayShow":
            self._choose_show(i, trig)
        else:
            self._set_action(i, trig, nxt)

    def _choose_show(self, i, trig):
        chosen = []
        dlg = TouchFileDialog(self, self.app.shows_dir, chosen.append, title_key="di_pick")

        def finished():   # диалогът първо се затваря и после вика on_select
            if chosen:
                self._set_action(i, trig, "PlayShow", chosen[0])
            else:         # отказ -> прескача към следващата команда (NoAction)
                self._set_action(i, trig, "NoAction")

        dlg.bind("<Destroy>", lambda e: self.after(150, finished) if e.widget is dlg else None, add="+")

    def _set_pin(self, i, pin):
        self.app.settings.inputs[i]["pin"] = pin
        self.app.settings.save()

    def _toggle_enabled(self):
        st = self.app.settings
        st.inputs_enabled = not st.inputs_enabled
        st.save()
        _on_off(self.en_btn, st.inputs_enabled)

    def _poll(self):
        if not self.winfo_exists():
            return
        mon = self.app.monitor
        states = mon.states if mon is not None and self.app.settings.inputs_enabled else []
        for i, dot in enumerate(self.dots):
            dot.config(fg="#22c55e" if i < len(states) and states[i] else MUTED)
        err = mon.error if mon is not None and self.app.settings.inputs_enabled else None
        self.err.config(text=tr_error(err) or "")
        self.after(100, self._poll)


class PlayerApp:
    def __init__(self, root: tk.Tk, player: DMXPlayer, shows_dir: str,
                 output_desc: str, fullscreen: bool = False, settings: Settings | None = None,
                 controller: Controller | None = None, monitor=None, planner=None):
        self.root = root
        self.player = player
        self.settings = settings or Settings()
        self.controller = controller or Controller(player, self.settings)
        self.monitor = monitor            # InputMonitor (за индикаторите в диалога за входове)
        self.planner = planner            # PlanRunner (TimePlaner.xml) или None
        self._prompt_after = None  # load_count, след който да се предложи избор на песен
        self.apply_settings(save=False)
        self.shows_dir = shows_dir
        self.output_desc = output_desc
        self._last_state = None
        self._mon_size = None      # кеш за DMX монитора (рисува се само при промяна)
        self._mon_vals = None
        self._mon_items = []

        root.title(t("window_title"))
        root.configure(bg=BG)
        root.geometry("800x480")
        root.minsize(640, 400)
        if fullscreen:
            # Без прозоречен мениджър (Raspberry Pi OS Lite + xinit) атрибутът
            # -fullscreen няма ефект, затова прозорецът се оразмерява и ръчно.
            root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
            root.attributes("-fullscreen", True)
            root.config(cursor="none")
        root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
        root.protocol("WM_DELETE_WINDOW", self.quit)

        self._build()
        self._tick()

    # ---------------- изграждане ----------------
    def _build(self):
        r = self.root
        pad = dict(padx=14)

        top = tk.Frame(r, bg=BG)
        top.pack(fill="x", pady=(10, 4), **pad)
        self.title_lbl = tk.Label(top, text=t("app_title"), font=(FONT, 16, "bold"), bg=BG, fg=FG)
        self.title_lbl.pack(side="left")
        tk.Button(top, text="✕", font=(FONT, 14), bg=BG, fg=MUTED, relief="flat", bd=0,
                  activebackground=PANEL, command=self.quit).pack(side="right")
        tk.Button(top, text="⏻", font=(FONT, 15, "bold"), bg="#ff453a", fg="white",
                  activebackground="#d0342b", relief="flat", padx=10, pady=0,
                  command=self.open_power).pack(side="right", padx=(12, 0))
        # Бутон за език: показва езика, НА който ще превключи (EN <-> БГ)
        self.lang_btn = tk.Button(top, font=(FONT, 13, "bold"), bg=PANEL, fg=FG,
                                  activebackground=ACCENT, relief="flat", padx=12, pady=2,
                                  command=self.switch_language)
        self.lang_btn.pack(side="right", padx=(12, 0))
        tk.Button(top, text="⚙", font=(FONT, 15), bg=PANEL, fg=FG, activebackground=ACCENT,
                  relief="flat", padx=10, pady=0, command=self.open_settings).pack(side="right", padx=(12, 0))
        tk.Button(top, text=t("ag_btn"), font=(FONT, 13, "bold"), bg=PANEL, fg=FG, activebackground=ACCENT,
                  relief="flat", padx=8, pady=0,
                  command=self.open_agenda).pack(side="right", padx=(12, 0))
        self.status = tk.Label(top, text="", font=(FONT, 15, "bold"), bg=BG)
        self.status.pack(side="right", padx=12)

        # Индикатор за файл + бутон "Зареди WDS"
        file_row = tk.Frame(r, bg=PANEL)
        file_row.pack(fill="x", pady=4, **pad)
        self.load_btn = tk.Button(file_row, text=t("load_wds"), font=(FONT, 16, "bold"),
                                  bg=ACCENT, fg="white", activebackground="#0060df",
                                  relief="flat", padx=18, pady=12, command=self.open_dialog)
        self.load_btn.pack(side="right", padx=8, pady=8)
        self.audio_btn = tk.Button(file_row, text=t("audio_btn"), font=(FONT, 16, "bold"),
                                   bg="#3a3a3c", fg="white", activebackground="#48484a",
                                   disabledforeground="#6b7280", relief="flat", padx=14, pady=12,
                                   command=self.open_audio_dialog)
        self.audio_btn.pack(side="right", padx=(8, 0), pady=8)
        info = tk.Frame(file_row, bg=PANEL)
        info.pack(side="left", fill="x", expand=True, padx=12, pady=8)
        self.file_lbl = tk.Label(info, text=t("no_file"), font=(FONT, 17, "bold"),
                                 bg=PANEL, fg=FG, anchor="w")
        self.file_lbl.pack(fill="x")
        self.meta_lbl = tk.Label(info, text=t("press_load"), font=(FONT, 12),
                                 bg=PANEL, fg=MUTED, anchor="w")
        self.meta_lbl.pack(fill="x")

        # Прогрес бар + времена
        prog = tk.Frame(r, bg=BG)
        prog.pack(fill="x", pady=(10, 0), **pad)
        self.progress = ui_kit.ProgressBar(prog, height=34, bg=BG)     # status bar на шоуто
        self.progress.pack(fill="x")
        times = tk.Frame(prog, bg=BG)
        times.pack(fill="x", pady=2)
        self.elapsed_lbl = tk.Label(times, text="00:00", font=(FONT, 20, "bold"), bg=BG, fg=FG)
        self.elapsed_lbl.pack(side="left")
        self.remaining_lbl = tk.Label(times, text="-00:00", font=(FONT, 20, "bold"), bg=BG, fg=FG)
        self.remaining_lbl.pack(side="right")
        self.pct_lbl = tk.Label(times, text="0 %", font=(FONT, 20, "bold"), bg=BG, fg=ACCENT)
        self.pct_lbl.pack()
        self.frames_lbl = tk.Label(prog, text="", font=(FONT, 11), bg=BG, fg=MUTED)
        self.frames_lbl.pack()

        # Бутони за контрол
        ctrl = tk.Frame(r, bg=BG)
        ctrl.pack(fill="x", pady=8, **pad)
        btn = dict(font=(FONT, 20, "bold"), fg="white", relief="flat", height=2,
                   disabledforeground="#6b7280")
        self.play_btn = tk.Button(ctrl, text="", bg="#30d158", activebackground="#24a844",
                                  command=self.player.play, **btn)
        self.pause_btn = tk.Button(ctrl, text="", bg="#ff9f0a", activebackground="#d9870a",
                                   command=self.player.pause, **btn)
        self.stop_btn = tk.Button(ctrl, text="", bg="#ff453a", activebackground="#d0342b",
                                  command=self.player.stop, **btn)
        for i, b in enumerate((self.play_btn, self.pause_btn, self.stop_btn)):
            b.grid(row=0, column=i, sticky="nsew", padx=5)
            ctrl.columnconfigure(i, weight=3, uniform="ctrl")
        self.loop_btn = tk.Button(ctrl, font=(FONT, 14, "bold"), fg="white", relief="flat",
                                  height=2, command=self.toggle_loop)
        self.loop_btn.grid(row=0, column=3, sticky="nsew", padx=5)
        ctrl.columnconfigure(3, weight=2)
        self._update_loop_btn()
        self._apply_language()

        # Сила на звука: − / плъзгач / +
        vol = tk.Frame(r, bg=BG)
        vol.pack(fill="x", pady=(0, 6), **pad)
        self.vol_lbl = tk.Label(vol, text="♪ " + t("volume"), font=(FONT, 14, "bold"), bg=BG, fg=FG)
        self.vol_lbl.pack(side="left", padx=(0, 8))
        vbtn = dict(font=(FONT, 16, "bold"), bg=PANEL, fg=FG, activebackground=ACCENT,
                    relief="flat", width=3, pady=0)
        tk.Button(vol, text="−", command=lambda: self._nudge_volume(-5), **vbtn).pack(side="left")
        self.vol_pct = tk.Label(vol, text="", font=(FONT, 16, "bold"), bg=BG, fg=FG, width=5, anchor="e")
        self.vol_pct.pack(side="right")
        tk.Button(vol, text="+", command=lambda: self._nudge_volume(5), **vbtn).pack(side="right", padx=(0, 4))
        self.vol_var = tk.IntVar(value=self.settings.volume)
        self.vol_scale = tk.Scale(vol, from_=0, to=100, orient="horizontal", variable=self.vol_var,
                                  showvalue=False, sliderlength=60, width=30, bg=BG, fg=FG,
                                  troughcolor=PANEL, activebackground=ACCENT, highlightthickness=0,
                                  bd=0, command=self._on_volume)
        self.vol_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.vol_scale.bind("<ButtonRelease-1>", lambda e: self.settings.save())
        self.vol_pct.config(text=f"{self.settings.volume} %")

        # DMX монитор (канали 1..32) + ред за грешки/порт
        bottom = tk.Frame(r, bg=BG)
        bottom.pack(fill="both", expand=True, pady=(0, 8), **pad)
        self.monitor = tk.Canvas(bottom, height=60, bg=PANEL, highlightthickness=0)
        self.monitor.pack(fill="both", expand=True)
        self.footer = tk.Label(bottom, text="", font=(FONT, 11), bg=BG, fg=MUTED, anchor="w")
        self.footer.pack(fill="x", pady=(4, 0))

    # ---------------- действия ----------------
    def open_dialog(self):
        TouchFileDialog(self.root, self.shows_dir, self.load_show)

    def load_show(self, path: str):
        self.settings.last_file = path
        schedule_file.import_schedule(self.settings, path)   # график до шоуто (ако има)
        self.settings.save()
        # След зареждането, ако шоуто няма песен, се отваря изборът на аудио (веднъж)
        self._prompt_after = (self.player.snapshot().load_count + 1) if self.settings.ask_audio else None
        self.player.load(path, self.settings.audio_overrides.get(path))

    def open_audio_dialog(self):
        wds = self.settings.last_file
        start = os.path.dirname(wds) if wds and os.path.isdir(os.path.dirname(wds)) else self.shows_dir
        TouchFileDialog(self.root, start, self.choose_audio, extensions=AUDIO_EXTENSIONS,
                        title_key="dlg_audio_title",
                        extra=(t("dlg_auto"), lambda: self.choose_audio(None)))

    def choose_audio(self, path):
        """path = ръчно избран файл; None = обратно към автоматичния."""
        wds = self.settings.last_file
        if path:
            self.settings.audio_overrides[wds] = path
        else:
            self.settings.audio_overrides.pop(wds, None)
        self.settings.save()
        self.player.set_audio(path)

    def _top(self):
        """Горният модален прозорец (ако има) – родител за нови диалози."""
        try:
            return self.root.grab_current() or self.root
        except tk.TclError:
            return self.root

    def open_settings(self):
        settings_ui.open_settings(self, _cover_master)

    def pick_file(self, start, callback):
        parent = self._top()
        dlg = TouchFileDialog(parent, start, callback)
        ui_kit.restore_grab(dlg, parent)

    def _open_modal(self, cls):
        parent = self._top()
        dlg = cls(self)
        ui_kit.restore_grab(dlg, parent)

    def open_inputs(self):
        self._open_modal(InputsDialog)

    def open_agenda(self):
        parent = self._top()
        nav = agenda_ui.open_agenda(self, _cover_master)
        ui_kit.restore_grab(nav, parent)

    def open_power(self):
        self._open_modal(PowerDialog)

    def apply_settings(self, save: bool = True):
        """Прилага настройките върху плейъра (и ги запазва)."""
        st = self.settings.clamp()
        apply_settings(self.player, st)
        self.player.set_schedule(False)   # стартовете по час вече са в графиците (scheduler.py)
        if save:
            self.settings.save()
        if hasattr(self, "loop_btn"):
            self._update_loop_btn()

    def _on_volume(self, value):
        """Плъзгачът се движи: прилага силата веднага (записва се при отпускане)."""
        v = int(float(value))
        self.settings.volume = v
        self.player.set_volume(v)
        self.vol_pct.config(text=f"{v} %")

    def _nudge_volume(self, delta):
        self.vol_var.set(min(100, max(0, self.vol_var.get() + delta)))
        self._on_volume(self.vol_var.get())
        self.settings.save()

    def toggle_loop(self):
        """Бърз превключвател: веднъж <-> безкрайно (точният брой е в Настройки)."""
        self.settings.loops = 0 if self.player.loops == 1 else 1
        self.apply_settings()

    def _update_loop_btn(self):
        n = self.player.loops
        if n != 1:
            text = t("loop_on") if n == 0 else t("loop_n", n=n)
            self.loop_btn.config(text="↻  " + text, bg=ACCENT, activebackground="#0060df")
        else:
            self.loop_btn.config(text="↻  " + t("loop_off"), bg="#3a3a3c", activebackground="#48484a")

    def switch_language(self):
        toggle_lang()
        self._apply_language()

    def _apply_language(self):
        """Прилага избрания език върху всички статични надписи."""
        self.root.title(t("window_title"))
        self.title_lbl.config(text=t("app_title"))
        self.lang_btn.config(text="EN" if get_lang() == "bg" else "БГ")
        self.load_btn.config(text=t("load_wds"))
        self.audio_btn.config(text=t("audio_btn"))
        if hasattr(self, "vol_lbl"):
            self.vol_lbl.config(text="♪ " + t("volume"))
        self.play_btn.config(text="▶  " + t("start"))
        self.pause_btn.config(text="❚❚  " + t("pause"))
        self.stop_btn.config(text="■  " + t("stop"))
        self._update_loop_btn()
        self._last_state = None  # принуждава _tick да обнови статуса

    def quit(self):
        self.player.shutdown()
        self.root.destroy()

    # ---------------- опресняване ----------------
    def _tick(self):
        snap = self.player.snapshot()
        info = snap.info

        if snap.state != self._last_state:
            self._last_state = snap.state
            self.status.config(text=t("state_" + snap.state.value), fg=STATE_COLORS[snap.state])
            loaded = info is not None
            self.play_btn.config(state="normal" if loaded and snap.state != State.PLAYING else "disabled")
            self.pause_btn.config(state="normal" if snap.state == State.PLAYING else "disabled")
            self.stop_btn.config(state="normal" if snap.state != State.IDLE else "disabled")

        if self._prompt_after is not None and snap.load_count >= self._prompt_after:
            self._prompt_after = None
            if info is not None and snap.audio_path is None:
                self.open_audio_dialog()

        if info is not None:
            self.file_lbl.config(text=info.file_name)
            audio = f"   ♪ {os.path.basename(snap.audio_path) if snap.audio_path else t('no_audio')}"
            self.meta_lbl.config(text=f"{t('show')}: {info.show_name}{audio}   ·   {format_time(info.duration)}")
            if snap.state == State.IDLE:
                self.play_btn.config(state="normal")
            self.progress["value"] = snap.progress * 1000
            self.pct_lbl.config(text=f"{int(snap.progress * 100)} %")
            self.elapsed_lbl.config(text=format_time(snap.elapsed))
            self.remaining_lbl.config(text="-" + format_time(snap.remaining))
            extra = ""
            if snap.loop_number and self.player.loops != 1:
                total = "∞" if self.player.loops == 0 else self.player.loops
                extra += f"   ·   {t('loop_info', k=snap.loop_number, n=total)}"
            left = snap.waiting_until - time.perf_counter()
            if snap.waiting_until and left > 0:
                extra += f"   ·   {t('gap_info', s=int(left) + 1)}"
            if snap.dropped_frames:
                extra += f"   ·   {t('dropped', n=snap.dropped_frames)}"
            self.frames_lbl.config(text=t("frame_info", i=snap.frame_index, n=info.frame_count,
                                          fps=info.fps) + extra)
            self.audio_btn.config(state="normal")
        else:
            self.audio_btn.config(state="disabled")
            self.file_lbl.config(text=t("no_file"))
            self.meta_lbl.config(text=t("press_load"))
            self.frames_lbl.config(text="")
            self.play_btn.config(state="disabled")
            self.progress["value"] = 0
            self.pct_lbl.config(text="0 %")

        port = f"DMX: {tr_error(self.output_desc)}  " + (
            "●  " + t("dmx_ok") if snap.output_ok else "●  " + t("dmx_no_link"))
        parts = [port]
        now_dt = datetime.now()
        nf = next_fire(self.settings.timers, now_dt)
        if nf is not None:
            fmt = "%H:%M:%S" if nf[0].date() == now_dt.date() else "%d.%m %H:%M"
            parts.insert(0, t("auto_info", t=nf[0].strftime(fmt)))
        if self.planner is not None and self.settings.planner_enabled:
            ps = self.planner.status(now_dt, t("plan_today"), t("plan_shows"), t("plan_end"))
            if ps:
                parts.insert(0, ps)
            if self.planner.missing:
                parts.insert(0, "⚠ " + t("plan_missing", names=", ".join(sorted(self.planner.missing))))
        ev = self.controller.last_event
        if ev and time.monotonic() - ev[0] < 6:
            if ev[1] == "timer_end":
                parts.insert(0, t("ev_timer_end"))
            elif ev[1] == "input":
                cmd = t("cmd_" + ev[4], name="") if ev[4] != "PlayShow" else t("cmd_PlayShow", name="…")
                parts.insert(0, t("ev_input", n=ev[2], edge="▲" if ev[3] == "pos" else "▼", cmd=cmd))
            else:
                parts.insert(0, t("ev_timer", name=ev[2] or t("tm_current")))
        if self.vol_var.get() != self.settings.volume:       # силата е сменена от вход/график
            self.vol_var.set(self.settings.volume)
            self.vol_pct.config(text=f"{self.settings.volume} %")
        if snap.error:
            parts.insert(0, f"⚠ {tr_error(snap.error)}")
        self.footer.config(text="    |    ".join(parts), fg=ERROR if snap.error else MUTED)

        self._draw_monitor(snap.last_frame)
        self.root.after(UI_REFRESH_MS, self._tick)

    def _draw_monitor(self, frame: bytes):
        """DMX монитор: елементите се създават веднъж, после се сменят само промененото
        (преначертаването на цялото платно 10 пъти/сек бави DMX нишката на Pi)."""
        c = self.monitor
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 30:
            return
        n = MONITOR_CHANNELS
        top, base = 4, h - 16
        slot = w / n
        if (w, h) != self._mon_size:
            c.delete("all")
            self._mon_items = []
            for i in range(n):
                x0, x1 = i * slot + 2, (i + 1) * slot - 2
                c.create_rectangle(x0, top, x1, base, fill="#1b1d23", width=0)
                bar = c.create_rectangle(x0, base, x1, base, fill=ACCENT, width=0, state="hidden")
                c.create_text((x0 + x1) / 2, h - 7, text=str(i + 1), fill=MUTED, font=(FONT, 7))
                self._mon_items.append(bar)
            self._mon_size = (w, h)
            self._mon_vals = None
        vals = tuple(frame[:n])
        if vals == self._mon_vals:
            return
        old = self._mon_vals
        for i, v in enumerate(vals):
            if old is not None and old[i] == v:
                continue
            x0, x1 = i * slot + 2, (i + 1) * slot - 2
            if v:
                c.coords(self._mon_items[i], x0, base - (base - top) * v / 255, x1, base)
                c.itemconfigure(self._mon_items[i], state="normal")
            else:
                c.itemconfigure(self._mon_items[i], state="hidden")
        self._mon_vals = vals
