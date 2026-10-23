#!/usr/bin/env python3
"""Измерва точността на DMX излъчването БЕЗ графичния интерфейс.

    python3 tools/timing_check.py show.wds                       # 30 s, реалният порт
    python3 tools/timing_check.py show.wds --seconds 60 --audio  # със звук през mpv
    python3 tools/timing_check.py show.wds --sim                 # без порт (само процесорът)

Показва интервалите между кадрите (цел 40 ms), пропуснатите кадри, температура и флагове
за throttling. Ако тук няма пропуснати кадри, а в приложението има - причината е графичният
интерфейс или други процеси; ако ги има и тук - проблемът е в системата/порта/захранването.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import player as player_mod  # noqa: E402
from audio import AudioPlayer, NullAudio  # noqa: E402
from dmx_engine import DEFAULT_PORT, DMXOutput, NullDMXOutput  # noqa: E402
from player import DMXPlayer, State  # noqa: E402


class TimedOutput:
    def __init__(self, inner):
        self.inner = inner
        self.times = []

    def send(self, channels):
        self.times.append(time.perf_counter())
        self.inner.send(channels)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка на времето на DMX кадрите")
    ap.add_argument("file")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--audio", action="store_true", help="със звук (mpv)")
    args = ap.parse_args()

    out = TimedOutput(NullDMXOutput() if args.sim else DMXOutput(args.port))
    p = DMXPlayer(out, audio=AudioPlayer() if args.audio else NullAudio())
    p.set_loops(0)
    p.start()
    p.load(args.file)
    time.sleep(1.0)
    snap = p.snapshot()
    if snap.info is None:
        print("Грешка:", snap.error)
        p.shutdown()
        return 1
    print(f"Шоу: {snap.info.file_name}, {snap.info.duration:.1f} s; измерване {args.seconds:.0f} s ...")
    out.times.clear()
    try:
        os.unlink(player_mod.DROP_LOG)
    except OSError:
        pass
    p.play()
    time.sleep(args.seconds)
    snap = p.snapshot()
    sent = list(out.times)           # само кадрите по време на измерването (без Blackout при стоп)
    p.stop()
    time.sleep(0.3)
    p.shutdown()

    ts = sent[1:]
    gaps = sorted((b - a) * 1000 for a, b in zip(ts, ts[1:]))
    if not gaps:
        print("Няма изпратени кадри.", snap.error or "")
        return 1
    pct = lambda q: gaps[min(len(gaps) - 1, int(len(gaps) * q))]
    print(f"кадри изпратени:      {len(ts)}")
    print(f"интервал, ms:         средно {sum(gaps)/len(gaps):.1f} | p50 {pct(.5):.1f} | p99 {pct(.99):.1f} | макс {gaps[-1]:.1f}  (цел 40.0)")
    print(f"интервали над 60 ms:  {sum(g > 60 for g in gaps)}")
    print(f"пропуснати кадри:     {snap.dropped_frames}")
    print(f"реално-времеви prio:  {'да' if getattr(p, 'realtime', False) else 'не (нормален приоритет)'}")
    print(f"температура:          {player_mod._read_first('/sys/class/thermal/thermal_zone0/temp')} (хилядни °C)")
    print(f"throttled:            {player_mod._throttled()}"
          "  (0x0 = ОК; 0x50005 и подобни = ниско напрежение/спиране)")
    if os.path.exists(player_mod.DROP_LOG):
        print(f"\nЗаписи за пропуснати кадри ({player_mod.DROP_LOG}):")
        print(open(player_mod.DROP_LOG, encoding="utf-8").read()[-1500:])
    return 0 if snap.dropped_frames == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
