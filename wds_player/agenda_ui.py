"""Календар / линеен график: ДЕН (времева линия 0–24 ч + списък), МЕСЕЦ (линеен график по дни + мрежа),
ГОДИНА (линеен график за 365 дни + 12 месеца)."""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date

import agenda
import ui_kit as ui
from i18n import get_lang, t

MONTHS = {
    "bg": ["Януари", "Февруари", "Март", "Април", "Май", "Юни", "Юли", "Август", "Септември", "Октомври",
           "Ноември", "Декември"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
}


def month_name(m: int) -> str:
    return MONTHS.get(get_lang(), MONTHS["en"])[m - 1]


def open_agenda(app, cover):
    state = {"view": "day", "day": date.today()}
    nav = ui.Navigator(app.root, t("ag_title"), lambda n, b: page(app, n, b, state), cover=cover)
    return nav


def page(app, nav, body, state):
    pl = app.planner
    if pl is not None:
        pl.reload()
    view, day = state["view"], state["day"]

    def set_view(v):
        state["view"] = v
        nav.rebuild()

    def go(delta):
        state["day"] = agenda.shift(state["view"], state["day"], delta)
        nav.rebuild()

    def today():
        state["day"] = date.today()
        nav.rebuild()

    head = tk.Frame(body, bg=ui.BG)
    head.pack(fill="x", padx=14, pady=(12, 4))
    ui.Segmented(head, (("day", t("ag_day")), ("month", t("ag_month")), ("year", t("ag_year"))), view,
                 set_view, font_size=13, pad_x=18).pack(side="left")
    ui.Pill(head, t("ag_today"), today, kind="quiet", width=96, height=38, font_size=13).pack(side="right")

    nav_row = tk.Frame(body, bg=ui.BG)
    nav_row.pack(fill="x", padx=14, pady=(8, 4))
    for text, d, side in (("‹", -1, "left"), ("›", 1, "right")):
        tk.Button(nav_row, text=text, font=(ui.FONT, 22, "bold"), bg=ui.CARD2, fg=ui.FG, relief="flat", bd=0,
                  width=3, activebackground=ui.ACCENT, command=lambda d=d: go(d)).pack(side=side)
    if view == "day":
        title = f"{t('wd_' + str(day.weekday()))}, {day.strftime('%d.%m.%Y')}"
    elif view == "month":
        title = f"{month_name(day.month)} {day.year}"
    else:
        title = str(day.year)
    tk.Label(nav_row, text=title, font=(ui.FONT, 18, "bold"), bg=ui.BG, fg=ui.FG).pack(expand=True)

    if view == "day":
        _day_view(app, nav, body, state)
    elif view == "month":
        _month_view(app, nav, body, state)
    else:
        _year_view(app, nav, body, state)
    tk.Frame(body, height=30, bg=ui.BG).pack()


# ---------------- ДЕН ----------------
def _day_view(app, nav, body, state):
    day = state["day"]
    rows = agenda.day_rows(app.settings, app.planner, day)
    n = agenda.show_count(rows)
    no_source = (app.planner is None or app.planner.plan is None) and not any(tm["on"] for tm in app.settings.timers)
    if no_source:
        summary, color = t("ag_none"), ui.MUTED
    elif n == 0:
        summary, color = t("ag_empty"), ui.MUTED
    else:
        summary, color = (t("ag_summary_1") if n == 1 else t("ag_summary", n=n)), ui.ACCENT
    tk.Label(body, text=summary, font=(ui.FONT, 14, "bold"), bg=ui.BG, fg=color, anchor="w").pack(
        fill="x", padx=24, pady=(6, 4))

    # --- линейна времева линия 0..24 ч ---
    cv = tk.Canvas(body, height=92, bg=ui.CARD, highlightthickness=0, bd=0)
    cv.pack(fill="x", padx=14, pady=4)
    cv.bind("<Configure>", lambda e: _draw_timeline(cv, rows, day))
    _draw_timeline(cv, rows, day)

    card = ui.section(body, None)
    for r in rows:
        if r["kind"] == "stop":
            name, fg = t("ag_end"), ui.MUTED
        else:
            tag = {"plan": "", "timer": f"  ({t('ag_manual')})"}[r["kind"]]
            if r["kind"] == "plan":
                tag = f"  ({t('ag_endless') if r['counts'] == 0 else '×' + str(r['counts'])})"
            name = ("⚠ " if r["missing"] else "") + (r["name"] or t("tm_current")) + tag
            fg = ui.RED if r["missing"] else ui.FG
        sub = None
        if r["end"] is not None:
            e = r["end"]
            sub = f"→ {min(e, 86399) // 3600:02d}:{e % 3600 // 60:02d}:{e % 60:02d}" if e < 86400 else "→ 24:00"
        ui.row(card, name, value=r["at"], subtitle=sub, title_fg=fg)


def _draw_timeline(cv, rows, day):
    w = cv.winfo_width() if cv.winfo_width() > 100 else 772
    cv.delete("all")
    left, right, y = 18, w - 18, 56
    span = right - left

    def x(secs):
        return left + span * secs / 86400

    ui.rounded_rect(cv, left, y - 6, right, y + 6, 6, fill=ui.TRACK, outline=ui.TRACK)
    for h in range(0, 25, 3):
        cv.create_line(x(h * 3600), y + 8, x(h * 3600), y + 16, fill=ui.MUTED)
        cv.create_text(x(h * 3600), y + 28, text=f"{h:02d}", fill=ui.MUTED, font=(ui.FONT, 9))
    if day == date.today():
        from datetime import datetime
        now = datetime.now()
        cv.create_line(x(now.hour * 3600 + now.minute * 60), 8, x(now.hour * 3600 + now.minute * 60), y + 6,
                       fill=ui.ORANGE, width=2)
    colors = {"plan": ui.GREEN, "timer": ui.ACCENT, "stop": ui.RED}
    last_label = -100            # надписите на близки часове не се застъпват (точният час е в списъка)
    for r in rows:
        c = ui.RED if r["missing"] else colors[r["kind"]]
        if r["end"] is not None:
            ui.rounded_rect(cv, x(r["secs"]), y - 6, max(x(r["end"]), x(r["secs"]) + 6), y + 6, 6, fill=c,
                            outline=c)
        else:
            cv.create_oval(x(r["secs"]) - 6, y - 6, x(r["secs"]) + 6, y + 6, fill=c, outline=c)
        if r["kind"] != "stop" and x(r["secs"]) - last_label >= 40:
            cv.create_text(x(r["secs"]), y - 16, text=r["at"][:5], fill=ui.FG, font=(ui.FONT, 9, "bold"))
            last_label = x(r["secs"])


# ---------------- линеен график за месец / година ----------------
def _bar_chart(body, values, ticks, cur, on_pick, tick_lines=False):
    """Линеен график: по едно стълбче за всеки ден (височина = брой шоута).
    ticks = [(индекс, надпис)], cur = индекс на днешния ден или None, on_pick(индекс) - докосване."""
    cv = tk.Canvas(body, height=118, bg=ui.CARD, highlightthickness=0, bd=0)
    cv.pack(fill="x", padx=14, pady=4)
    geo = {}

    def draw(_e=None):
        w = cv.winfo_width() if cv.winfo_width() > 100 else 772
        cv.delete("all")
        left, right, base, top = 18, w - 18, 84, 14
        step = (right - left) / max(1, len(values))
        geo.update(left=left, step=step)
        peak = max(values) if values else 0
        cv.create_line(left, base, right, base, fill=ui.TRACK, width=2)
        for i, text in ticks:
            x = left + step * (i + 0.5 if not tick_lines else i)
            if tick_lines:
                cv.create_line(x, top, x, base + 6, fill=ui.TRACK)
            else:
                cv.create_line(x, base + 2, x, base + 7, fill=ui.MUTED)
            cv.create_text(x if not tick_lines else x + 3, base + 18, text=text, fill=ui.MUTED,
                           font=(ui.FONT, 9), anchor="center" if not tick_lines else "w")
        bar_w = step if step < 4 else step * 0.7      # година: плътна лента без ивици
        for i, n in enumerate(values):
            x = left + step * (i + 0.5)
            if n:
                h = (base - top) * n / peak
                col = ui.ORANGE if i == cur else ui.GREEN
                cv.create_rectangle(x - bar_w / 2, base - h, x + bar_w / 2, base, fill=col, outline=col)
                if step >= 18:
                    cv.create_text(x, base - h - 7, text=str(n), fill=ui.FG, font=(ui.FONT, 8, "bold"))
        if cur is not None:
            x = left + step * (cur + 0.5)
            cv.create_line(x, top - 6, x, base + 4, fill=ui.ORANGE, width=2)
        if not peak:
            cv.create_text((left + right) / 2, (top + base) / 2, text="—", fill=ui.MUTED, font=(ui.FONT, 14))

    def tap(e):
        if ui.DRAG["moved"] or not geo:
            return
        i = int((e.x - geo["left"]) // geo["step"])
        if 0 <= i < len(values):
            on_pick(i)
    cv.bind("<Configure>", draw)
    cv.bind("<ButtonRelease-1>", tap, add="+")
    draw()
    return cv


# ---------------- МЕСЕЦ ----------------
def _month_view(app, nav, body, state):
    day = state["day"]
    counts = agenda.month_counts(app.settings, app.planner, day.year, day.month)
    today = date.today()
    n_days = len(counts)
    ticks = [(d - 1, str(d)) for d in sorted({1, 5, 10, 15, 20, 25, n_days})]
    cur = today.day - 1 if (today.year, today.month) == (day.year, day.month) else None

    def open_day_at(i):
        state["day"] = date(day.year, day.month, i + 1)
        state["view"] = "day"
        nav.rebuild()
    _bar_chart(body, [counts[d] for d in range(1, n_days + 1)], ticks, cur, open_day_at)

    grid = tk.Frame(body, bg=ui.BG)
    grid.pack(fill="x", padx=14, pady=6)
    for c in range(7):
        grid.columnconfigure(c, weight=1, uniform="d")
        tk.Label(grid, text=t(f"day_{c}"), font=(ui.FONT, 11, "bold"), bg=ui.BG, fg=ui.MUTED).grid(row=0, column=c)
    first = calendar.monthrange(day.year, day.month)[0]
    for d, n in counts.items():
        pos = first + d - 1
        r, c = pos // 7 + 1, pos % 7
        is_today = date(day.year, day.month, d) == today
        cell = tk.Frame(grid, bg=ui.ACCENT if is_today else ui.CARD, height=58)
        cell.grid(row=r, column=c, sticky="nsew", padx=2, pady=2)
        cell.grid_propagate(False)
        fg_main = "#ffffff" if is_today else ui.FG
        tk.Label(cell, text=str(d), font=(ui.FONT, 14, "bold"), bg=cell["bg"], fg=fg_main).pack(pady=(4, 0))
        if n:
            tk.Label(cell, text=f"● {n}", font=(ui.FONT, 11, "bold"), bg=cell["bg"],
                     fg="#ffffff" if is_today else ui.GREEN).pack()

        def open_day(e, d=d):
            if not ui.DRAG["moved"]:
                state["day"] = date(day.year, day.month, d)
                state["view"] = "day"
                nav.rebuild()
        for w in (cell, *cell.winfo_children()):
            w.bind("<ButtonRelease-1>", open_day, add="+")
    total = sum(counts.values())
    ui.note(body, f"{t('ag_total')}: {total}   ·   ● = {t('ag_dot_hint')}")


# ---------------- ГОДИНА ----------------
def _year_view(app, nav, body, state):
    day = state["day"]
    per_day = agenda.year_day_counts(app.settings, app.planner, day.year)
    counts = agenda.year_counts(app.settings, app.planner, day.year, per_day)
    days = sorted(per_day)
    ticks = [(i, month_name(d.month)[:3]) for i, d in enumerate(days) if d.day == 1]
    today = date.today()
    cur = days.index(today) if today in per_day else None

    def open_month_at(i):          # стълбчетата са тесни за пръст - отваря месеца на деня
        state["day"] = days[i]
        state["view"] = "month"
        nav.rebuild()
    _bar_chart(body, [per_day[d] for d in days], ticks, cur, open_month_at, tick_lines=True)

    grid = tk.Frame(body, bg=ui.BG)
    grid.pack(fill="x", padx=14, pady=6)
    for c in range(3):
        grid.columnconfigure(c, weight=1, uniform="m")
    peak = max(counts.values()) or 1
    for m in range(1, 13):
        r, c = (m - 1) // 3, (m - 1) % 3
        cur = (day.year, m) == (date.today().year, date.today().month)
        cell = tk.Frame(grid, bg=ui.CARD, height=92, highlightthickness=2 if cur else 0,
                        highlightbackground=ui.ACCENT)
        cell.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)
        cell.grid_propagate(False)
        tk.Label(cell, text=month_name(m), font=(ui.FONT, 14, "bold"), bg=ui.CARD, fg=ui.FG).pack(pady=(8, 0))
        n = counts[m]
        tk.Label(cell, text=str(n) if n else "—", font=(ui.FONT, 18, "bold"), bg=ui.CARD,
                 fg=ui.GREEN if n else ui.MUTED).pack()
        bar = tk.Canvas(cell, height=8, bg=ui.CARD, highlightthickness=0)
        bar.pack(fill="x", padx=12, pady=(2, 0))
        bar.bind("<Configure>", lambda e, b=bar, n=n: (b.delete("all"),
                 ui.rounded_rect(b, 0, 1, max(8, e.width * n / peak) if n else 0, 7, 3, fill=ui.GREEN,
                                 outline=ui.GREEN) if n else None))

        def open_month(e, m=m):
            if not ui.DRAG["moved"]:
                state["day"] = date(day.year, m, min(day.day, calendar.monthrange(day.year, m)[1]))
                state["view"] = "month"
                nav.rebuild()
        for w in (cell, *cell.winfo_children()):
            w.bind("<ButtonRelease-1>", open_month, add="+")
    ui.note(body, f"{t('ag_total')}: {sum(counts.values())}")
