"""Страници „Настройки“ в стил iOS/Android: списък със секции, превключватели, сегментиран избор
и екранна клавиатура. Строи се върху ui_kit.Navigator; `app` е PlayerApp.

Нужни от app: settings, apply_settings(), shows_dir, planner, pick_file(start, cb), open_inputs(),
open_agenda(), open_power(), switch_language(), root.
"""

from __future__ import annotations

import calendar
import os
import threading
from datetime import date, datetime

import schedule_file
import sysconf
from i18n import get_lang, t
from scheduler import next_fire
from settings import MAX_TIMERS, new_timer
import ui_kit as ui


# ---------------- помощни ----------------
def _hms(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def stepper_row(card, title, get, set_, lo, hi, step=1, fmt=str, subtitle=None, big=None, width=7):
    return ui.row(card, title, subtitle=subtitle,
                  widget=lambda p: ui.Stepper(p, get, set_, lo, hi, step, fmt, big_step=big, width=width))


def seg_row(card, title, options, current, on_change, subtitle=None):
    return ui.row(card, title, subtitle=subtitle,
                  widget=lambda p: ui.Segmented(p, options, current, on_change, font_size=12, pad_x=10))


def action_row(card, text, command, kind="primary"):
    color = {"primary": ui.ACCENT, "danger": ui.RED, "good": ui.GREEN}.get(kind, ui.ACCENT)
    f = ui.row(card, text, command=command, title_fg=color)
    return f


def run_bg(widget, fn, done):
    """Изпълнява fn в нишка (nmcli може да е бавен); done(резултат) се вика в Tk нишката."""
    box = {}

    def work():
        try:
            box["r"] = fn()
        except Exception as e:      # noqa: BLE001
            box["r"] = (False, str(e))

    th = threading.Thread(target=work, daemon=True)
    th.start()

    def poll():
        if not widget.winfo_exists():
            return
        if th.is_alive():
            widget.after(150, poll)
        else:
            done(box.get("r"))

    widget.after(150, poll)


def fail_text(text: str) -> str:
    """Съобщение за неуспех; липсващо sudo правило се обяснява."""
    if "password is required" in (text or "") or "a terminal is required" in (text or ""):
        return "✖ " + t("u_sudo_hint")
    return "✖ " + t("u_failed") + (": " + text if text else "")


def ask_text(nav, title, initial, kind, on_done, secret=False):
    dlg = ui.KeyboardDialog(nav, title, initial, kind, on_done, secret=secret, cover=nav._cover)
    ui.restore_grab(dlg, nav)


def _show_name(path: str) -> str:
    return os.path.basename(path) if path else t("u_show_cur")


def timer_title(tm: dict) -> str:
    when = f"{tm['h']:02d}:{tm['m']:02d}:{tm['s']:02d}"
    if tm.get("end_on"):
        when += f" → {tm['eh']:02d}:{tm['em']:02d}:{tm['es']:02d}"
    return when


def timer_subtitle(tm: dict) -> str:
    if tm.get("date"):
        d = date.fromisoformat(tm["date"])
        day = f"{t('wd_' + str(d.weekday()))} {d.strftime('%d.%m.%Y')}"
    elif len(tm["days"]) == 7:
        day = t("tm_every_day")
    elif not tm["days"]:
        day = t("tm_no_days")
    else:
        day = " ".join(t(f"day_{d}") for d in tm["days"])
    return f"{day}  ·  ▶ {_show_name(tm['show'])}"


# ---------------- главна страница ----------------
def open_settings(app, cover):
    nav = ui.Navigator(app.root, t("u_settings"), lambda n, body: main_page(app, n, body), cover=cover)
    nav._cover = cover
    return nav


def main_page(app, nav, body):
    nav._cover = getattr(nav, "_cover", None)
    st = app.settings
    now = datetime.now()

    card = ui.section(body, None)
    ui.row(card, t("u_playback"), chevron=True,
           value=("∞" if st.loops == 0 else f"×{st.loops}"),
           command=lambda: nav.push(t("u_playback"), lambda n, b: playback_page(app, n, b)))
    n_on = sum(1 for tm in st.timers if tm["on"])
    ui.row(card, t("u_schedules"), chevron=True, value=t("u_sched_n", n=n_on) if n_on else t("u_none"),
           command=lambda: nav.push(t("u_schedules"), lambda n, b: schedules_page(app, n, b)))
    ui.row(card, t("u_agenda"), chevron=True, command=app.open_agenda)
    ui.row(card, t("u_boot"), chevron=True, value=t("u_on") if st.boot_play else t("u_off_s"),
           command=lambda: nav.push(t("u_boot"), lambda n, b: boot_page(app, n, b)))
    nf = next_fire(st.timers, now)
    ui.note(body, f"{t('u_next')}: " + (nf[0].strftime("%d.%m.%Y %H:%M:%S") if nf else t("u_next_none")))

    card = ui.section(body, t("u_dmx"))
    ui.row(card, t("u_dmx"), chevron=True, value=f"{st.dmx_channels} ch · {st.dmx_fps} fps",
           command=lambda: nav.push(t("u_dmx"), lambda n, b: dmx_page(app, n, b)))
    ui.row(card, t("u_inputs"), chevron=True, value=t("u_on") if st.inputs_enabled else t("u_off_s"),
           command=app.open_inputs)

    card = ui.section(body, t("u_system"))
    ui.row(card, t("u_network"), chevron=True,
           command=lambda: nav.push(t("u_network"), lambda n, b: network_page(app, n, b)))
    ui.row(card, t("u_datetime"), chevron=True, value=now.strftime("%H:%M"),
           command=lambda: nav.push(t("u_datetime"), lambda n, b: time_page(app, n, b)))
    seg_row(card, t("u_language"), (("bg", "БГ"), ("en", "EN")), get_lang(),
            lambda v: (app.switch_language(), nav.rebuild()))
    ui.row(card, t("u_power"), chevron=True, title_fg=ui.RED, command=app.open_power)
    tk_pad(body)


def tk_pad(body):
    import tkinter as tk
    tk.Frame(body, height=30, bg=ui.BG).pack()


# ---------------- възпроизвеждане ----------------
def playback_page(app, nav, body):
    st = app.settings

    def setter(attr):
        def f(v):
            setattr(st, attr, v)
            app.apply_settings()
        return f

    card = ui.section(body, None)
    stepper_row(card, t("u_loops"), lambda: st.loops, setter("loops"), 0, 999, 1,
                lambda v: "∞" if v == 0 else str(v), subtitle=t("u_loops_sub"), big=10)
    stepper_row(card, t("u_gap"), lambda: st.loop_gap, setter("loop_gap"), 0, 3600, 1,
                lambda v: f"{v} s", subtitle=t("u_seconds"), big=10)
    stepper_row(card, t("u_offset"), lambda: st.audio_offset_ms, setter("audio_offset_ms"), -1000, 1000, 10,
                lambda v: f"{v:+d} ms", subtitle=t("u_offset_sub"), big=10, width=9)
    ui.switch_row(card, t("u_ask"), st.ask_audio, lambda v: (setattr(st, "ask_audio", v), app.apply_settings()))
    ui.note(body, t("set_offset_hint"))
    tk_pad(body)


# ---------------- автостарт ----------------
def boot_page(app, nav, body):
    st = app.settings
    card = ui.section(body, None)
    ui.switch_row(card, t("u_boot_on"), st.boot_play,
                  lambda v: (setattr(st, "boot_play", v), app.apply_settings(), nav.rebuild()))
    if st.boot_play:
        def pick():
            start = os.path.dirname(st.boot_show) if st.boot_show and os.path.isdir(os.path.dirname(st.boot_show)) \
                else app.shows_dir

            def chosen(path):
                st.boot_show = path
                app.apply_settings()
                nav.rebuild()
            app.pick_file(start, chosen)

        ui.row(card, t("u_boot_show"), chevron=True,
               value=(os.path.basename(st.boot_show) if st.boot_show else t("u_boot_last")), command=pick)
        if st.boot_show:
            ui.row(card, t("u_boot_last"), title_fg=ui.ACCENT,
                   command=lambda: (setattr(st, "boot_show", ""), app.apply_settings(), nav.rebuild()))
        stepper_row(card, t("u_boot_delay"), lambda: st.boot_delay,
                    lambda v: (setattr(st, "boot_delay", v), app.apply_settings()), 0, 300, 1,
                    lambda v: f"{v} s")
    ui.note(body, t("u_boot_hint"))
    tk_pad(body)


# ---------------- DMX ----------------
def dmx_page(app, nav, body):
    st = app.settings

    def setter(attr):
        def f(v):
            setattr(st, attr, v)
            app.apply_settings()
        return f

    card = ui.section(body, None)
    stepper_row(card, t("u_fps"), lambda: st.dmx_fps, setter("dmx_fps"), 1, 44, 1, lambda v: f"{v} fps",
                subtitle=t("u_fps_sub"), width=8)
    stepper_row(card, t("u_channels"), lambda: st.dmx_channels, setter("dmx_channels"), 24, 512, 8,
                str, subtitle=t("u_channels_sub"), big=8)
    presets = tuple((n, str(n)) for n in (24, 128, 256, 512))

    def preset(v):
        st.dmx_channels = v
        app.apply_settings()
        nav.rebuild()
    seg_row(card, "", presets, st.dmx_channels if st.dmx_channels in (24, 128, 256, 512) else None, preset)

    modes = (("hold", t("u_hold")), ("blackout", t("u_blackout")), ("off", t("u_off")))
    card = ui.section(body, t("u_pause"))
    seg_row(card, t("u_pause"), modes, st.pause_mode, setter("pause_mode"))
    ui.note(body, t("u_pause_hint"))
    modes2 = (("blackout", t("u_blackout")), ("hold", t("u_hold")), ("off", t("u_off")))
    card = ui.section(body, t("u_stop"))
    seg_row(card, t("u_stop"), modes2, st.stop_mode, setter("stop_mode"))
    ui.note(body, t("u_stop_hint"))
    tk_pad(body)


# ---------------- графици ----------------
def schedules_page(app, nav, body):
    st = app.settings
    if schedule_file.import_all(st, [app.shows_dir]):
        st.save()
    card = ui.section(body, None)
    planner_has = app.planner is not None
    ui.switch_row(card, t("u_planner"), st.planner_enabled,
                  lambda v: (setattr(st, "planner_enabled", v), st.save()),
                  subtitle=None if planner_has and app.planner.plan is not None else t("u_planner_none"))

    card = ui.section(body, t("u_schedules"))
    if not st.timers:
        ui.note(body, t("u_no_sched"))
    for i, tm in enumerate(st.timers):
        def toggle(v, i=i):
            st.timers[i]["on"] = v
            st.save()
            if st.timers[i]["show"]:
                schedule_file.sync_show(st, st.timers[i]["show"])
        f = ui.row(card, timer_title(tm), subtitle=timer_subtitle(tm),
                   widget=lambda p, tm=tm, toggle=toggle: _switch_chev(p, tm["on"], toggle))
        _bind_tap(f, lambda i=i: (nav.__dict__.pop("_drafts", None),
                                  nav.push(t("u_edit_sched"), lambda n, b: timer_page(app, n, b, i))))
    if len(st.timers) < MAX_TIMERS:
        card = ui.section(body, None)
        ui.row(card, t("u_new_sched"), title_fg=ui.ACCENT,
               command=lambda: (nav.__dict__.pop("_drafts", None),
                                nav.push(t("u_new_sched"), lambda n, b: timer_page(app, n, b, None))))
    nf = next_fire(st.timers, datetime.now())
    ui.note(body, f"{t('u_next')}: " + (nf[0].strftime("%d.%m.%Y %H:%M:%S") if nf else t("u_next_none")))
    tk_pad(body)


def _switch_chev(parent, value, on_change):
    import tkinter as tk
    f = tk.Frame(parent, bg=ui.CARD)
    ui.Switch(f, value, on_change).pack(side="left", padx=(0, 8))
    tk.Label(f, text="›", font=(ui.FONT, 24), bg=ui.CARD, fg=ui.MUTED).pack(side="left")
    return f


def _bind_tap(row_frame, cmd):
    """Докосване върху заглавието/реда (не върху превключвателя) отваря редактора."""
    for w in (row_frame, *row_frame.winfo_children()[:1]):
        w.bind("<ButtonRelease-1>", lambda e: cmd(), add="+")
    for w in row_frame.winfo_children()[0].winfo_children():
        w.bind("<ButtonRelease-1>", lambda e: cmd(), add="+")


def timer_page(app, nav, body, index):
    """Редактор на график. Чернова (draft) – записва се само с „Запази“; „Назад“ я отхвърля."""
    import tkinter as tk
    st = app.settings
    key = ("draft", index)
    draft = getattr(nav, "_drafts", {}).get(key)
    if draft is None:
        draft = dict(st.timers[index]) if index is not None else new_timer()
        draft["days"] = list(draft["days"])
        nav._drafts = getattr(nav, "_drafts", {})
        nav._drafts[key] = draft
    tm = draft

    card = ui.section(body, None)
    ui.switch_row(card, t("u_active"), tm["on"], lambda v: tm.__setitem__("on", v))

    # --- повторение: всяка седмица / само на дата ---
    def set_mode(mode):
        if mode == "date" and not tm["date"]:
            tm["date"] = date.today().isoformat()
        if mode == "week":
            tm["date"] = ""
        nav.rebuild()
    card = ui.section(body, t("u_repeat"))
    seg_row(card, t("u_repeat"), (("week", t("u_weekly")), ("date", t("u_onedate"))),
            "date" if tm["date"] else "week", set_mode)

    if tm["date"]:
        d0 = date.fromisoformat(tm["date"])
        info = {"lbl": None}

        def get(part):
            return getattr(date.fromisoformat(tm["date"]), part)

        def put(part):
            def f(v):
                cur = date.fromisoformat(tm["date"])
                y, m, d = cur.year, cur.month, cur.day
                if part == "year":
                    y = v
                elif part == "month":
                    m = v
                else:
                    d = v
                d = min(d, calendar.monthrange(y, m)[1])
                tm["date"] = date(y, m, d).isoformat()
                _upd()
            return f

        card = ui.section(body, None)
        stepper_row(card, t("u_day"), lambda: get("day"), put("day"), 1, 31, 1, lambda v: f"{v:02d}", width=5)
        stepper_row(card, t("u_month"), lambda: get("month"), put("month"), 1, 12, 1, lambda v: f"{v:02d}", width=5)
        stepper_row(card, t("u_year"), lambda: get("year"), put("year"), date.today().year - 1,
                    date.today().year + 20, 1, str, width=6)
        lbl = tk.Label(body, text="", font=(ui.FONT, 13, "bold"), bg=ui.BG, fg=ui.ACCENT, anchor="w",
                       justify="left", wraplength=740)
        lbl.pack(fill="x", padx=24, pady=(8, 0))

        def _upd():
            d = date.fromisoformat(tm["date"])
            txt = f"{t('wd_' + str(d.weekday()))}, {d.strftime('%d.%m.%Y')}  —  {t('u_onedate_hint')}"
            past = d < date.today()
            if past:
                txt += "\n⚠ " + t("u_past")
            lbl.config(text=txt, fg=ui.ORANGE if past else ui.ACCENT)
            for w in body.winfo_children():          # опреснява етикетите на степерите (31 -> 28 ...)
                _refresh_steppers(w)
        _upd()
    else:
        card = ui.section(body, t("u_days"))
        f = tk.Frame(card, bg=ui.CARD)
        f.pack(fill="x", padx=10, pady=10)
        btns = []

        def paint():
            for d, b in enumerate(btns):
                on = d in tm["days"]
                b.config(bg=ui.ACCENT if on else ui.CARD2, fg="#ffffff" if on else ui.MUTED)

        def flip(d):
            s = set(tm["days"])
            s ^= {d}
            tm["days"] = sorted(s)
            paint()
        for d in range(7):
            b = tk.Button(f, text=t(f"day_{d}"), font=(ui.FONT, 14, "bold"), relief="flat", bd=0, pady=10,
                          activebackground=ui.ACCENT, command=lambda d=d: flip(d))
            b.pack(side="left", expand=True, fill="x", padx=3)
            btns.append(b)
        paint()

    # --- час ---
    card = ui.section(body, t("u_start_time"))
    for key_, title, hi in (("h", t("u_hour"), 23), ("m", t("u_minute"), 59), ("s", t("u_second"), 59)):
        stepper_row(card, title, lambda k=key_: tm[k], lambda v, k=key_: tm.__setitem__(k, v), 0, hi, 1,
                    lambda v: f"{v:02d}", width=5)
    card = ui.section(body, None)
    ui.switch_row(card, t("u_end_time"), tm["end_on"],
                  lambda v: (tm.__setitem__("end_on", v), nav.rebuild()))
    if not tm["end_on"]:
        ui.note(body, t("u_end_hint_off"))
    if tm["end_on"]:
        for key_, title, hi in (("eh", t("u_hour"), 23), ("em", t("u_minute"), 59), ("es", t("u_second"), 59)):
            stepper_row(card, title, lambda k=key_: tm[k], lambda v, k=key_: tm.__setitem__(k, v), 0, hi, 1,
                        lambda v: f"{v:02d}", width=5)

    if tm["end_on"]:
        ui.note(body, t("u_end_hint_on"))

    # --- шоу ---
    card = ui.section(body, t("u_show"))

    def pick():
        start = os.path.dirname(tm["show"]) if tm["show"] and os.path.isdir(os.path.dirname(tm["show"])) \
            else app.shows_dir

        def chosen(path):
            tm["show"] = path
            nav.rebuild()
        app.pick_file(start, chosen)
    ui.row(card, t("u_show"), chevron=True, value=_show_name(tm["show"]), command=pick)
    if tm["show"]:
        ui.row(card, t("u_show_cur"), title_fg=ui.ACCENT, command=lambda: (tm.__setitem__("show", ""), nav.rebuild()))
        show = tm["show"]
        if os.access(os.path.dirname(show) or ".", os.W_OK):
            ui.note(body, t("tm_sidecar_ok", name=os.path.basename(show) + schedule_file.SUFFIX))
        else:
            ui.note(body, t("tm_sidecar_ro"), fg=ui.RED)
    else:
        ui.note(body, t("tm_sidecar_none"))

    # --- запис / изтриване ---
    def save():
        if not tm["date"] and not tm["days"]:
            tm["days"] = list(range(7))
        timers = st.timers
        shows = {tm["show"]}
        if index is None:
            timers.append(dict(tm))
        else:
            shows.add(timers[index]["show"])
            timers[index] = dict(tm)
        st.clamp()
        st.save()
        for s in shows:
            if s:
                schedule_file.sync_show(st, s)
        nav._drafts.pop(key, None)
        nav.back()

    def delete():
        shows = {st.timers[index]["show"]}
        del st.timers[index]
        st.save()
        for s in shows:
            if s:
                schedule_file.sync_show(st, s)
        nav._drafts.pop(key, None)
        nav.back()

    card = ui.section(body, None)
    ui.row(card, t("u_save"), title_fg=ui.GREEN, command=save)
    if index is not None:
        ui.row(card, t("u_delete"), title_fg=ui.RED, command=delete)
    tk_pad(body)


def _refresh_steppers(w):
    if isinstance(w, ui.Stepper):
        w.show()
    for c in w.winfo_children():
        _refresh_steppers(c)


# ---------------- мрежа ----------------
def network_page(app, nav, body):
    import tkinter as tk
    if sysconf.read_only_root():
        ui.note(body, "⚠ " + t("u_ro_warn"), fg=ui.ORANGE)
    devs = sysconf.net_devices()
    card = ui.section(body, None)
    if not devs:
        tk.Label(card, text=t("u_no_devices"), font=(ui.FONT, 14), bg=ui.CARD, fg=ui.MUTED,
                 pady=16).pack()
    for d in devs:
        info = sysconf.net_info(d["dev"])
        ok = d["state"] == "connected"
        ui.row(card, d["dev"] + ("  (Wi‑Fi)" if d["type"] == "wifi" else "  (Ethernet)"),
               subtitle=(info["ip"] or "—") + ("  ·  " + t("u_connected") if ok else "  ·  " + t("u_disconnected")),
               chevron=True,
               command=lambda d=d: (nav.__dict__.pop("_drafts", None),
                                    nav.push(d["dev"], lambda n, b: device_page(app, n, b, d))))
    if any(d["type"] == "wifi" for d in devs):
        card = ui.section(body, t("u_wifi"))
        ui.row(card, t("u_wifi"), chevron=True,
               command=lambda: nav.push(t("u_wifi"), lambda n, b: wifi_page(app, n, b)))
    tk_pad(body)


def device_page(app, nav, body, dev):
    import tkinter as tk
    st = app.settings
    ro = sysconf.read_only_root()
    key = ("net", dev["dev"])
    nav._drafts = getattr(nav, "_drafts", {})
    cfg = nav._drafts.get(key)
    if cfg is None:
        info = sysconf.net_info(dev["dev"])
        cfg = {"method": info["method"], "ip": info["ip"], "prefix": info["prefix"] or "24",
               "gw": info["gw"], "dns": info["dns"], "conn": info["conn"]}
        nav._drafts[key] = cfg
    if ro:
        ui.note(body, "⚠ " + t("u_ro_warn"), fg=ui.ORANGE)

    def set_method(m):
        cfg["method"] = m
        nav.rebuild()
    card = ui.section(body, None)
    seg_row(card, t("u_network"), (("auto", t("u_dhcp")), ("manual", t("u_static"))), cfg["method"], set_method)

    def field(card, label, k, kind):
        def edit():
            def done(v):
                cfg[k] = v.strip()
                nav.rebuild()
            ask_text(nav, label, cfg[k], kind, done)
        ui.row(card, label, value=cfg[k] or "—", chevron=True, command=edit)

    card = ui.section(body, None)
    if cfg["method"] == "manual":
        field(card, t("u_ip"), "ip", "ip")
        field(card, t("u_prefix"), "prefix", "num")
        field(card, t("u_gw"), "gw", "ip")
        field(card, t("u_dns"), "dns", "ip")
    else:
        ui.row(card, t("u_ip"), value=cfg["ip"] or "—")
        ui.row(card, t("u_gw"), value=cfg["gw"] or "—")

    msg = tk.Label(body, text="", font=(ui.FONT, 13, "bold"), bg=ui.BG, fg=ui.MUTED, anchor="w",
                   wraplength=740, justify="left")

    def apply():
        msg.config(text=t("u_applying"), fg=ui.MUTED)
        m = cfg["method"]
        run_bg(nav, lambda: sysconf.set_ip(cfg["conn"] or dev["conn"], m, cfg["ip"], cfg["prefix"], cfg["gw"],
                                           cfg["dns"]), finished)

    def finished(res):
        ok, text = res or (False, "")
        if ok:
            net = st.system.setdefault("net", {})
            if cfg["method"] == "manual":
                net[dev["dev"]] = {k: cfg[k] for k in ("ip", "prefix", "gw", "dns")} | {"method": "manual"}
            else:
                net.pop(dev["dev"], None)
            st.save()
            msg.config(text="✔ " + t("u_done"), fg=ui.GREEN)
        else:
            msg.config(text=fail_text(text), fg=ui.RED)

    card = ui.section(body, None)
    ui.row(card, t("u_apply"), title_fg=ui.ACCENT, command=apply)
    msg.pack(fill="x", padx=24, pady=8)
    tk_pad(body)


def wifi_page(app, nav, body):
    import tkinter as tk
    st = app.settings
    if sysconf.read_only_root():
        ui.note(body, "⚠ " + t("u_ro_warn"), fg=ui.ORANGE)
    holder = tk.Frame(body, bg=ui.BG)
    holder.pack(fill="x")
    msg = tk.Label(body, text=t("u_scan"), font=(ui.FONT, 13, "bold"), bg=ui.BG, fg=ui.MUTED, anchor="w",
                   wraplength=740, justify="left")
    msg.pack(fill="x", padx=24, pady=8)

    def connect(net, password=""):
        msg.config(text=t("u_applying"), fg=ui.MUTED)

        def done(res):
            ok, text = res or (False, "")
            msg.config(text=("✔ " + t("u_done")) if ok else fail_text(text), fg=ui.GREEN if ok else ui.RED)
            if ok:
                st.system["wifi"] = {"ssid": net["ssid"], "password": password}   # помни се и се прилага при старт
                st.save()
                scan()
        run_bg(nav, lambda: sysconf.wifi_connect(net["ssid"], password), done)

    def tap(net):
        saved = st.system.get("wifi") or {}
        if net["secure"] and not net["active"] and saved.get("ssid") == net["ssid"] and saved.get("password"):
            connect(net, saved["password"])
        elif net["secure"] and not net["active"]:
            ask_text(nav, t("u_wifi_pass") + net["ssid"], "", "text", lambda pw: connect(net, pw), secret=True)
        else:
            connect(net)

    def show(nets):
        for w in holder.winfo_children():
            w.destroy()
        card = ui.section(holder, None)
        for n in nets:
            bars = "▂▄▆█"[min(3, n["signal"] // 26)]
            ui.row(card, n["ssid"], subtitle=(t("u_connected") if n["active"] else None),
                   value=("🔒 " if n["secure"] else "") + bars, command=lambda n=n: tap(n))
        ui.row(card, t("u_rescan"), title_fg=ui.ACCENT, command=scan)
        msg.config(text="")

    def scan():
        msg.config(text=t("u_scan"), fg=ui.MUTED)
        run_bg(nav, lambda: (True, sysconf.wifi_scan()), lambda r: show(r[1] if r else []))
    scan()
    tk_pad(body)


# ---------------- дата, час, часова зона ----------------
COMMON_TZ = ["Europe/Sofia", "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Athens",
             "Europe/Bucharest", "Europe/Istanbul", "Europe/Moscow", "America/New_York",
             "America/Chicago", "America/Los_Angeles", "Asia/Dubai", "Asia/Tokyo", "Australia/Sydney", "UTC"]


def time_page(app, nav, body):
    import tkinter as tk
    st = app.settings
    info = sysconf.time_status()
    if sysconf.read_only_root():
        ui.note(body, "⚠ " + t("u_ro_warn"), fg=ui.ORANGE)
    msg = tk.Label(body, text="", font=(ui.FONT, 13, "bold"), bg=ui.BG, fg=ui.MUTED, anchor="w")

    card = ui.section(body, None)
    clock = ui.row(card, t("u_now"), value=datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))

    def tick():
        if clock.winfo_exists() and clock.value_lbl is not None:
            clock.value_lbl.config(text=datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))
            clock.after(1000, tick)
    tick()

    def set_ntp(v):
        msg.config(text=t("u_applying"), fg=ui.MUTED)

        def done(res):
            ok, text = res or (False, "")
            msg.config(text="✔ " + t("u_done") if ok else fail_text(text), fg=ui.GREEN if ok else ui.RED)
            if ok:
                st.system["ntp"] = bool(v)
                st.save()
        run_bg(nav, lambda: sysconf.set_ntp(v), done)
    ui.switch_row(card, t("u_ntp"), info["ntp"], set_ntp)
    ui.row(card, t("u_set_manual"), chevron=True,
           command=lambda: nav.push(t("u_set_manual"), lambda n, b: manual_time_page(app, n, b)))
    tz_now = info["timezone"] or st.system.get("timezone", "")
    ui.row(card, t("u_timezone"), chevron=True, value=_tz_label(tz_now) if tz_now else "—",
           command=lambda: nav.push(t("u_timezone"), lambda n, b: tz_page(app, n, b)))
    msg.pack(fill="x", padx=24, pady=8)
    ui.note(body, t("u_no_rtc"))
    tk_pad(body)


def manual_time_page(app, nav, body):
    import tkinter as tk
    now = datetime.now()
    v = {"y": now.year, "mo": now.month, "d": now.day, "h": now.hour, "mi": now.minute}
    card = ui.section(body, None)

    def put(k):
        def f(x):
            v[k] = x
            v["d"] = min(v["d"], calendar.monthrange(v["y"], v["mo"])[1])
            _refresh_steppers(body)
        return f
    for k, title, lo, hi, fmt in (("d", t("u_day"), 1, 31, "{:02d}"), ("mo", t("u_month"), 1, 12, "{:02d}"),
                                  ("y", t("u_year"), 2024, 2099, "{}"), ("h", t("u_hour"), 0, 23, "{:02d}"),
                                  ("mi", t("u_minute"), 0, 59, "{:02d}")):
        stepper_row(card, title, lambda k=k: v[k], put(k), lo, hi, 1, lambda x, f=fmt: f.format(x), width=5)
    msg = tk.Label(body, text="", font=(ui.FONT, 13, "bold"), bg=ui.BG, fg=ui.MUTED, anchor="w",
                   wraplength=740, justify="left")

    def apply():
        dt = datetime(v["y"], v["mo"], min(v["d"], calendar.monthrange(v["y"], v["mo"])[1]), v["h"], v["mi"], 0)
        msg.config(text=t("u_applying"), fg=ui.MUTED)

        def done(res):
            ok, text = res or (False, "")
            msg.config(text="✔ " + t("u_done") if ok else fail_text(text), fg=ui.GREEN if ok else ui.RED)
        run_bg(nav, lambda: sysconf.set_time(dt), done)
    card = ui.section(body, None)
    ui.row(card, t("u_apply"), title_fg=ui.ACCENT, command=apply)
    msg.pack(fill="x", padx=24, pady=8)
    tk_pad(body)


def tz_page(app, nav, body):
    st = app.settings
    zones = sysconf.list_timezones() or COMMON_TZ
    regions = sorted({z.split("/")[0] for z in zones if "/" in z})
    card = ui.section(body, t("u_pick_tz"))
    for z in COMMON_TZ:
        if z in zones:
            ui.row(card, z, value=sysconf.utc_offset(z), command=lambda z=z: _set_tz(app, nav, z))
    card = ui.section(body, t("u_region"))
    for r in regions:
        ui.row(card, r, chevron=True,
               command=lambda r=r: nav.push(r, lambda n, b: tz_region_page(app, n, b, r, zones)))
    tk_pad(body)


def tz_region_page(app, nav, body, region, zones):
    card = ui.section(body, None)
    for z in zones:
        if z.startswith(region + "/"):
            ui.row(card, z.split("/", 1)[1].replace("_", " "), value=sysconf.utc_offset(z),
                   command=lambda z=z: _set_tz(app, nav, z, pop=2))
    tk_pad(body)


def _tz_label(tz: str) -> str:
    """"Europe/Sofia (UTC+03:00)" - зоната и отместването ѝ от Гринуич."""
    off = sysconf.utc_offset(tz)
    return f"{tz} ({off})" if off else tz


def _set_tz(app, nav, tz, pop=1):
    import tkinter as tk
    w = tk.Label(nav, text=t("u_applying"), bg=ui.CARD2, fg="#ffffff", font=(ui.FONT, 13, "bold"), padx=14, pady=6)
    w.place(relx=0.5, rely=0.95, anchor="s")

    def done(res):
        ok, text = res or (False, "")
        if ok:
            app.settings.system["timezone"] = tz
            app.settings.save()
            w.destroy()
            for _ in range(pop):
                nav.back()
        else:
            w.config(text=fail_text(text), bg=ui.RED)
            nav.after(5000, w.destroy)
    run_bg(nav, lambda: sysconf.set_timezone(tz), done)
