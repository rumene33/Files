"""Графици (като TimePlaner в Depence): старт на шоу в зададен час и дни от седмицата.

График = {"on": bool, "days": [0..6] (0 = понеделник), "date": "" или "YYYY-MM-DD", "h", "m", "s",
"show": път или ""}. Със зададена "date" графикът важи САМО на тази дата (без повторение след
седмица); иначе се повтаря всяка седмица в избраните дни.
Празно "show" = текущо заредено шоу. Стартът винаги започва шоуто отначало.
"""

from __future__ import annotations

import threading
from datetime import date as _date, datetime, time as dtime, timedelta


def applies_on(tm: dict, day) -> bool:
    """Важи ли графикът за деня: еднократен (точна дата) или седмичен (дни от седмицата)."""
    if tm.get("date"):
        return tm["date"] == day.isoformat()
    return day.weekday() in tm.get("days", ())


def fire_time(tm: dict, day) -> datetime:
    return datetime.combine(day, dtime(tm["h"], tm["m"], tm["s"]))


def window(tm: dict, day):
    """(начало, край|None) на графика, започващ в деня `day`. Край <= начало = на следващия ден."""
    start = fire_time(tm, day)
    if not tm.get("end_on"):
        return start, None
    end = datetime.combine(day, dtime(tm["eh"], tm["em"], tm["es"]))
    if end <= start:
        end += timedelta(days=1)
    return start, end


def next_fire(timers, now: datetime):
    """Най-близкият бъдещ старт: (datetime, график) или None."""
    best = None
    for tm in timers:
        if not tm.get("on"):
            continue
        if tm.get("date"):
            try:
                cand = fire_time(tm, _date.fromisoformat(tm["date"]))
            except ValueError:
                continue
            if cand > now and (best is None or cand < best[0]):
                best = (cand, tm)
            continue
        if not tm.get("days"):
            continue
        for add in range(8):
            cand = fire_time(tm, (now + timedelta(days=add)).date())
            if cand > now and cand.weekday() in tm["days"]:
                if best is None or cand < best[0]:
                    best = (cand, tm)
                break
    return best


class Scheduler(threading.Thread):
    """Следи часовника и вика fire(график), когато настъпи часът му.

    Закъснение над max_late секунди (скок на часовника, напр. NTP след старт на
    Pi, който няма RTC) не задейства стартове - иначе шоуто би тръгнало погрешно.
    """

    def __init__(self, get_timers, fire, clock=datetime.now, poll: float = 0.25, max_late: float = 5.0,
                 fire_end=None):
        super().__init__(name="Scheduler", daemon=True)
        self._get_timers = get_timers
        self._fire = fire
        self._fire_end = fire_end
        self._clock = clock
        self._poll = poll
        self._max_late = max_late
        self._stop_evt = threading.Event()
        self._last = clock()

    def check(self, now: datetime) -> None:
        span = (now - self._last).total_seconds()
        last, self._last = self._last, now
        if not 0 < span <= self._max_late:
            return
        for tm in list(self._get_timers()):
            if not tm.get("on"):
                continue
            # дни на начало: вчера (край след полунощ), днес и деня на предишната проверка
            for day in {last.date() - timedelta(days=1), last.date(), now.date()}:
                if not applies_on(tm, day):
                    continue
                start, end = window(tm, day)
                try:      # грешка в едно шоу не бива да убива нишката на графиците
                    if last < start <= now:
                        self._fire(tm)
                    if end is not None and last < end <= now and self._fire_end:
                        self._fire_end(tm)
                except Exception as e:      # noqa: BLE001
                    print(f"[scheduler] грешка при старт: {e}")

    def run(self) -> None:
        self._last = self._clock()
        while not self._stop_evt.wait(self._poll):
            self.check(self._clock())

    def stop(self) -> None:
        self._stop_evt.set()
