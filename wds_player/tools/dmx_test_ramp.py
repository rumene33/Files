#!/usr/bin/env python3
"""Етап 1.1: конзолен тест на DMX хардуера - плавна промяна (Ramp 0-255).

Примери:
    python3 tools/dmx_test_ramp.py --channel 1            # ramp на канал 1
    python3 tools/dmx_test_ramp.py --channel 1 2 3        # едновременно на 1, 2, 3
    python3 tools/dmx_test_ramp.py --rgb 1                # R->G->B, започвайки от канал 1
    python3 tools/dmx_test_ramp.py --static 1=255 4=128   # фиксирани стойности
    python3 tools/dmx_test_ramp.py --channel 1 --dimmer 4 # + master dimmer на канал 4 = 255

Ctrl+C спира теста и изпраща Blackout.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dmx_engine import DEFAULT_PORT, DMXError, DMXOutput, NullDMXOutput  # noqa: E402


def triangle(t: float, period: float) -> int:
    """0 -> 255 -> 0 за `period` секунди."""
    phase = (t % period) / period
    return int(round(255 * (1 - abs(2 * phase - 1))))


def main() -> int:
    ap = argparse.ArgumentParser(description="DMX ramp тест")
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--sim", action="store_true", help="без хардуер")
    ap.add_argument("--break-mode", choices=("break", "baud"), default="break")
    ap.add_argument("--de-gpio", type=int)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--channel", type=int, nargs="+", help="канал(и) 1..512 за ramp")
    g.add_argument("--rgb", type=int, metavar="FIRST", help="R,G,B на FIRST, FIRST+1, FIRST+2")
    g.add_argument("--static", nargs="+", metavar="CH=VAL")
    ap.add_argument("--dimmer", type=int, nargs="*", default=[],
                    help="канали, които се държат на 255 (master dimmer/shutter)")
    ap.add_argument("--period", type=float, default=4.0, help="секунди за цикъл 0-255-0")
    ap.add_argument("--fps", type=float, default=30.0, help="DMX пакети в секунда")
    args = ap.parse_args()

    def check(ch):
        if not 1 <= ch <= 512:
            ap.error(f"канал {ch} е извън 1..512")
        return ch

    out = NullDMXOutput() if args.sim else DMXOutput(args.port, args.break_mode, de_gpio=args.de_gpio)
    try:
        out.open()
    except DMXError as e:
        print(f"ГРЕШКА: {e}", file=sys.stderr)
        return 1

    frame = bytearray(512)
    for ch in args.dimmer:
        frame[check(ch) - 1] = 255
    static = {}
    for item in args.static or []:
        ch, _, val = item.partition("=")
        static[check(int(ch))] = max(0, min(255, int(val)))

    print(f"DMX тест на {out.description}. Ctrl+C за стоп.")
    period = 1.0 / args.fps
    start = next_t = time.perf_counter()
    packets = 0
    try:
        while True:
            t = time.perf_counter() - start
            if args.channel:
                v = triangle(t, args.period)
                for ch in args.channel:
                    frame[check(ch) - 1] = v
                shown = v
            elif args.rgb:
                base = check(args.rgb) - 1
                check(args.rgb + 2)
                color = int(t // args.period) % 3
                v = triangle(t, args.period)
                for i in range(3):
                    frame[base + i] = v if i == color else 0
                shown = f"{'RGB'[color]}={v}"
            else:
                for ch, val in static.items():
                    frame[ch - 1] = val
                shown = static

            out.send(frame)
            packets += 1
            if packets % int(args.fps / 3 or 1) == 0:
                print(f"\r t={t:6.1f}s  пакети={packets:6d}  стойност={shown!s:<12}", end="", flush=True)

            next_t += period
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()
    except KeyboardInterrupt:
        print("\nСтоп - изпращам Blackout.")
    finally:
        try:
            out.blackout()
            out.blackout()
        except DMXError:
            pass
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
