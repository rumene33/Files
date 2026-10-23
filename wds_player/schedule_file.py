"""Графикът се пази и в отделен файл до шоуто: Test.wds -> Test.wds.schedule.

Така графикът пътува със шоуто (копират се двата файла) и не зависи от настройките на плейъра.
Формат (JSON): {"version": 1, "timers": [{on, days, h, m, s, end_on, eh, em, es}, ...]} -
без път до шоуто, понеже е "до" него.

- Запис: при всяка промяна на график с конкретно шоу (gui: редактора на графика).
- Нов график от файл се добавя ИЗКЛЮЧЕН - включвате го с бутона ВКЛ/ИЗКЛ в списъка с графици.
- Четене: при избор на шоу (заменя графиците на това шоу) и при старт на плейъра - за
  шоута в папката на шоутата, които още нямат графици в настройките.
- Графици без шоу (= текущото) остават само в настройките на плейъра.
"""

from __future__ import annotations

import glob
import json
import os

from settings import MAX_TIMERS, clean_timer

SUFFIX = ".schedule"
VERSION = 1


def sidecar_path(wds: str) -> str:
    return wds + SUFFIX


def _same(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


def read_sidecar(wds: str) -> list | None:
    """Графиците от файла до шоуто (без път до шоуто); None ако няма/е повреден."""
    try:
        with open(sidecar_path(wds), encoding="utf-8") as f:
            raw = json.load(f)
        items = raw["timers"] if isinstance(raw, dict) else raw
        out = [c for c in (clean_timer(d) for d in items) if c is not None]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    for tm in out:
        tm["show"] = ""
    return out[:MAX_TIMERS]


def write_sidecar(wds: str, timers: list) -> bool:
    """Записва графиците до шоуто; без графици файлът се маха. False при неуспех."""
    path = sidecar_path(wds)
    try:
        if not timers:
            if os.path.exists(path):
                os.unlink(path)
            return True
        data = {"version": VERSION,
                "timers": [{k: v for k, v in tm.items() if k != "show"} for tm in timers]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def timers_for(settings, wds: str) -> list:
    return [t for t in settings.timers if t["show"] and _same(t["show"], wds)]


def sync_show(settings, wds: str) -> bool:
    """Записва графиците на това шоу от настройките във файла до него."""
    return bool(wds) and write_sidecar(wds, timers_for(settings, wds))


def import_schedule(settings, wds: str) -> bool:
    """Файлът до шоуто е по-важен: заменя графиците на това шоу в настройките."""
    loaded = read_sidecar(wds)
    if loaded is None:
        return False
    is_new = not timers_for(settings, wds)
    others = [t for t in settings.timers if not (t["show"] and _same(t["show"], wds))]
    # Нов график от файл пристига ИЗКЛЮЧЕН: потребителят го включва съзнателно (един бутон).
    new = [dict(t, show=wds, on=False if is_new else t["on"]) for t in loaded]
    settings.timers = (others + new)[:MAX_TIMERS]
    return True


def import_all(settings, dirs) -> int:
    """При старт: намира *.wds.schedule в папките и вкарва графиците на шоута без такива."""
    n = 0
    for d in dict.fromkeys(os.path.abspath(x) for x in dirs if x and os.path.isdir(x)):
        for sc in sorted(glob.glob(os.path.join(glob.escape(d), "*.wds" + SUFFIX))):
            wds = sc[:-len(SUFFIX)]
            if os.path.isfile(wds) and not timers_for(settings, wds) and import_schedule(settings, wds):
                n += 1
    return n
