"""Чете TimePlaner.xml от Depence (Syncronorm_Timeplanerfile_V1.0) и работи по него.

Структура на файла:
  Dayplans  -> Day (GUID, Name) -> events: EventName, EventType (1 = пусни шоу, 2 = спри всичко
               "end all"), StartBy "HH:MM:SS", Counts (0 = безкрайно, N = N пъти), Lenght (секунди),
               ContentGUID (име на шоуто без .wds)
  Weekplans -> Week (GUID, Name) -> event Weekdayname (Montag..Sonntag) -> DayplanGUID
  Yearplans -> Year (Yearnumber) -> event EventGUID (седмичен или дневен план), EventIsDayplan,
               Daynumber, MonthNumber

Годишният план има два вида записи:
  * дневен план (EventIsDayplan="True") - важи САМО на тази дата (без повторение);
  * седмичен план (EventIsDayplan="False") - важи от тази дата, докато не дойде следващият запис
    (в примерния файл са отбелязани 4, 11, 18, 25.10 и 1.03...). Ако за годината няма запис
    преди днешната дата, важи последният запис от по-ранна година; ако няма и такъв - нищо.
Дневен план на точната дата има предимство пред седмичния.

Името на шоуто се търси като .wds в папките на шоутата; интервалите, „_“ и „-“ и главните/малките
букви се игнорират („Test MUSIC“ -> Test_MUSIC.wds).
"""

from __future__ import annotations

import os
import re
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta

FILE_NAME = "TimePlaner.xml"
WEEKDAYS = {"montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
            "samstag": 5, "sonntag": 6,
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
            "saturday": 5, "sunday": 6}
PLAY, STOP = 1, 2


@dataclass(frozen=True)
class Event:
    at: dtime
    name: str            # име на шоуто (ContentGUID)
    kind: int            # PLAY | STOP
    counts: int          # 0 = безкрайно
    length: float        # секунди


@dataclass
class Plan:
    name: str = ""
    days: dict = field(default_factory=dict)     # guid -> [Event]
    weeks: dict = field(default_factory=dict)    # guid -> {weekday: day guid}
    years: dict = field(default_factory=dict)    # година -> [(месец, ден, guid, is_dayplan)]


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _time(text: str) -> dtime | None:
    try:
        h, m, s = (int(x) for x in (text.strip().split(":") + ["0", "0"])[:3])
        return dtime(h, m, s)
    except (ValueError, AttributeError):
        return None


def parse(path: str) -> Plan:
    """Чете файла; при грешка в структурата - ValueError/OSError."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ValueError(f"повреден XML: {e}") from e
    plan = Plan(name=root.get("PlanName", ""))
    for sec in root:
        kind = _tag(sec)
        for item in sec:
            guid = item.get("GUID")
            events = [e for box in item for e in box if _tag(e) == "event"]
            if kind == "Dayplans" and guid:
                evs = []
                for e in events:
                    at = _time(e.get("StartBy", ""))
                    try:
                        etype = int(e.get("EventType", "1"))
                        counts = max(0, int(e.get("Counts", "1")))
                        length = float(e.get("Lenght", "0"))
                    except ValueError:
                        continue
                    if at is None or etype not in (PLAY, STOP):
                        continue
                    evs.append(Event(at, e.get("ContentGUID") or e.get("EventName", ""), etype,
                                     counts, length))
                plan.days[guid] = sorted(evs, key=lambda x: x.at)
            elif kind == "Weekplans" and guid:
                week = {}
                for e in events:
                    wd = WEEKDAYS.get((e.get("Weekdayname") or "").lower())
                    if wd is not None and e.get("DayplanGUID"):
                        week[wd] = e.get("DayplanGUID")
                plan.weeks[guid] = week
            elif kind == "Yearplans":
                try:
                    year = int(item.get("Yearnumber"))
                except (TypeError, ValueError):
                    continue
                entries = []
                for e in events:
                    try:
                        entries.append((int(e.get("MonthNumber")), int(e.get("Daynumber")),
                                        e.get("EventGUID"), e.get("EventIsDayplan", "").lower() == "true"))
                    except (TypeError, ValueError):
                        continue
                plan.years[year] = sorted(entries)
    return plan


def day_events(plan: Plan, day: date) -> list:
    """Събитията за дадена дата според годишния/седмичния/дневния план."""
    for m, d, guid, is_day in plan.years.get(day.year, []):      # дневен план само на тази дата
        if is_day and (m, d) == (day.month, day.day):
            return list(plan.days.get(guid, []))
    chosen = None
    for year in sorted((y for y in plan.years if y <= day.year), reverse=True):
        past = [e for e in plan.years[year] if not e[3]
                and (year < day.year or (e[0], e[1]) <= (day.month, day.day))]
        if past:
            chosen = past[-1]
            break
    if chosen is None:
        return []
    guid = plan.weeks.get(chosen[2], {}).get(day.weekday())
    return list(plan.days.get(guid, []))


def count_shows(plan: Plan, day: date) -> int:
    """Колко шоута са планирани за деня (събития „пусни шоу“)."""
    return sum(1 for e in day_events(plan, day) if e.kind == PLAY)


def next_events(plan: Plan, now: datetime, days: int = 8):
    """Първото бъдещо събитие: (datetime, Event) или None."""
    for add in range(days):
        d = now.date() + timedelta(days=add)
        for ev in day_events(plan, d):
            at = datetime.combine(d, ev.at)
            if at > now:
                return at, ev
    return None


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s).lower()


def find_show(name: str, dirs) -> str | None:
    """Път до .wds по име на съдържанието (разхлабено сравнение)."""
    want = _norm(name)
    for d in dirs:
        try:
            files = sorted(os.listdir(d))
        except OSError:
            continue
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() == ".wds" and stem == name:
                return os.path.join(d, f)
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() == ".wds" and _norm(stem) == want:
                return os.path.join(d, f)
    return None


def find_file(dirs) -> str | None:
    for d in dirs:
        p = os.path.join(d, FILE_NAME)
        if os.path.isfile(p):
            return p
    return None


class PlanRunner(threading.Thread):
    """Следи часовника и изпълнява събитията от TimePlaner.xml.

    play(път_до_шоу, counts) / stop() - вика Controller. Файлът се чете наново при промяна
    (качване на нов TimePlaner.xml не изисква рестарт). При старт, ако в момента трябва да
    върви шоу (безкрайно или още в рамките на Lenght×Counts), то се пуска отначало (catchup).
    """

    def __init__(self, dirs, play, stop, show_dirs=None, enabled=lambda: True, clock=datetime.now,
                 poll: float = 0.5, max_late: float = 5.0, catchup: bool = True):
        super().__init__(name="PlanRunner", daemon=True)
        self._dirs = dirs                  # къде се търси TimePlaner.xml
        self._shows = show_dirs            # къде се търсят .wds (по подразбиране същите папки)
        self._play = play
        self._stop_cb = stop
        self._enabled = enabled
        self._clock = clock
        self._poll = poll
        self._max_late = max_late
        self._catchup = catchup
        self._stop_evt = threading.Event()
        self._last = clock()
        self._mtime = None
        self.path: str | None = None
        self.plan: Plan | None = None
        self.error: str | None = None
        self.missing: set = set()          # имена без намерен .wds

    # --- файл ---
    def reload(self) -> bool:
        """Чете файла, ако е нов/променен. True при нова версия."""
        path = find_file(self._dirs() if callable(self._dirs) else self._dirs)
        if path is None:
            changed = self.plan is not None
            self.path, self.plan, self.error, self._mtime = None, None, None, None
            return changed
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            return False
        if path == self.path and mtime == self._mtime:
            return False
        self.path, self._mtime = path, mtime
        try:
            self.plan, self.error = parse(path), None
        except (ValueError, OSError) as e:
            self.plan, self.error = None, str(e)
        return True

    def _show_dirs(self):
        src = self._shows if self._shows is not None else self._dirs
        return list(src() if callable(src) else src)

    # --- изпълнение ---
    def _run_event(self, ev: Event) -> None:
        if ev.kind == STOP:
            self._stop_cb()
            return
        path = find_show(ev.name, self._show_dirs())
        if path is None:
            self.missing.add(ev.name)
            return
        self.missing.discard(ev.name)
        self._play(path, ev.counts)

    def _startup_catchup(self, now: datetime) -> None:
        todays = [(datetime.combine(now.date(), e.at), e) for e in day_events(self.plan, now.date())]
        todays = [(at, e) for at, e in todays if at <= now]
        if not todays:
            return
        at, ev = todays[-1]
        if ev.kind == STOP:
            return
        if ev.counts == 0 or (now - at).total_seconds() < ev.length * ev.counts:
            self._run_event(ev)

    def check(self, now: datetime, first: bool = False) -> None:
        self.reload()
        span = (now - self._last).total_seconds()
        last, self._last = self._last, now
        if self.plan is None or not self._enabled():
            return
        if first and self._catchup:
            self._startup_catchup(now)
            return
        if not 0 < span <= self._max_late:
            return
        for d in {last.date(), now.date()}:
            for ev in day_events(self.plan, d):
                if last < datetime.combine(d, ev.at) <= now:
                    self._run_event(ev)

    def run(self) -> None:
        self._last = self._clock()
        self.check(self._clock(), first=True)
        while not self._stop_evt.wait(self._poll):
            self.check(self._clock())

    def stop(self) -> None:
        self._stop_evt.set()

    # --- за показване ---
    def status(self, now: datetime, today_word: str = "днес", shows_word: str = "шоута",
               end_word: str = "край") -> str | None:
        if self.error:
            return "TimePlaner: " + self.error
        if self.plan is None:
            return None
        n = count_shows(self.plan, now.date())
        head = f"TimePlaner ({today_word}: {n} {shows_word})"
        nxt = next_events(self.plan, now)
        if nxt is None:
            return head
        at, ev = nxt
        fmt = "%H:%M:%S" if at.date() == now.date() else "%d.%m %H:%M"
        what = end_word if ev.kind == STOP else ev.name
        return f"{head}: {what} {at.strftime(fmt)}"
