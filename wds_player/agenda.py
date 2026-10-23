"""Данни за календара/линейния график: какво е планирано за ден, месец и година (без tkinter)."""

from __future__ import annotations

import calendar
import os
from datetime import date, timedelta

import timeplaner
from scheduler import applies_on, window


def day_rows(settings, planner, day: date, check_missing: bool = True) -> list:
    """Редове за деня, подредени по час: {secs, at, name, kind, missing, end}.
    kind: "plan" (шоу от TimePlaner), "stop" (край на TimePlaner), "timer" (ръчен график).
    end = секунда от началото на деня, когато спира график с край (ограничено до 24:00) или None.
    check_missing=False - без търсене на .wds на диска (за броенето по месец/година, иначе на Pi
    стотици четения на папката блокират интерфейса)."""
    rows = []
    if planner is not None and settings.planner_enabled and planner.plan is not None:
        dirs = planner._show_dirs() if check_missing else []
        for ev in timeplaner.day_events(planner.plan, day):
            secs = ev.at.hour * 3600 + ev.at.minute * 60 + ev.at.second
            if ev.kind == timeplaner.STOP:
                rows.append({"secs": secs, "name": "", "kind": "stop", "missing": False, "end": None,
                             "counts": 0})
            else:
                rows.append({"secs": secs, "name": ev.name, "kind": "plan", "counts": ev.counts,
                             "missing": check_missing and timeplaner.find_show(ev.name, dirs) is None,
                             "end": None})
    for tm in settings.timers:
        if not tm["on"] or not applies_on(tm, day):
            continue
        start, end = window(tm, day)
        secs = start.hour * 3600 + start.minute * 60 + start.second
        end_secs = None
        if end is not None:
            end_secs = min(86400, int((end - start).total_seconds()) + secs)
        name = os.path.splitext(os.path.basename(tm["show"]))[0] if tm["show"] else ""
        rows.append({"secs": secs, "name": name, "kind": "timer", "missing": False, "end": end_secs,
                     "counts": 0})
    rows.sort(key=lambda r: r["secs"])
    for r in rows:
        r["at"] = f"{r['secs'] // 3600:02d}:{r['secs'] % 3600 // 60:02d}:{r['secs'] % 60:02d}"
    return rows


def show_count(rows) -> int:
    return sum(1 for r in rows if r["kind"] != "stop")


def month_counts(settings, planner, year: int, month: int) -> dict:
    """{ден: брой шоута} за месеца."""
    n = calendar.monthrange(year, month)[1]
    return {d: show_count(day_rows(settings, planner, date(year, month, d), check_missing=False))
            for d in range(1, n + 1)}


def year_day_counts(settings, planner, year: int) -> dict:
    """{дата: брой шоута} за всеки ден от годината (за линейния график на годината)."""
    return {date(year, m, d): n for m in range(1, 13) for d, n in month_counts(settings, planner, year, m).items()}


def year_counts(settings, planner, year: int, days: dict | None = None) -> dict:
    """{месец: общ брой шоута} за годината (days = готов резултат от year_day_counts)."""
    if days is None:
        days = year_day_counts(settings, planner, year)
    out = dict.fromkeys(range(1, 13), 0)
    for d, n in days.items():
        out[d.month] += n
    return out


def shift(view: str, day: date, delta: int) -> date:
    """Предишен/следващ ден, месец или година."""
    if view == "day":
        return day + timedelta(days=delta)
    if view == "month":
        m = day.month - 1 + delta
        y, m = day.year + m // 12, m % 12 + 1
    else:
        y, m = day.year + delta, day.month
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))
