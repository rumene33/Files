#!/usr/bin/env python3
"""Генерира синтетичен .wds файл във формата на Depence/OASE WECS.

    python3 tools/make_test_wds.py ~/shows/test_rgb.wds --seconds 60 --rgb 1

Хедър 1024 B ("OA", име на шоуто, MP3), нулева зона до DATA_OFFSET и записи
{u32 ms, u16 N, N/3 x (u16 канал, u8 стойност)} на всеки 40 ms:
RGB преливане на каналите FIRST..FIRST+2 (+ dimmer канал, ако е зададен).
С --raw се генерира суровият формат от заданието (кадри по 512 B).
"""

import argparse
import colorsys
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wds_parser import DEFAULT_FPS, FRAME_SIZE, HEADER_SIZE  # noqa: E402

DATA_OFFSET = 17507  # както в Test.wds от Depence


def build_header(name: str, mp3: str, record_size: int, channels: int) -> bytes:
    h = bytearray(HEADER_SIZE)
    h[0:2] = b"OA"
    struct.pack_into("<HH", h, 2, record_size & 0xFFFF, 2)
    n = name.encode("utf-8")[:40]
    h[0x06:0x06 + len(n)] = n
    h[0x2F:0x32] = bytes([1, channels & 0xFF, 1])
    a = mp3.encode("utf-8")[:43]
    h[0x32:0x32 + len(a)] = a
    h[0x5E] = 100
    return bytes(h)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS)
    ap.add_argument("--rgb", type=int, default=1, help="първи канал на RGB тялото")
    ap.add_argument("--dimmer", type=int, help="канал за master dimmer (държи се на 255)")
    ap.add_argument("--name", default="Test Show RGB")
    ap.add_argument("--mp3", default="test_show.mp3")
    ap.add_argument("--raw", action="store_true", help="суров формат: кадри по 512 B")
    args = ap.parse_args()

    n = int(args.seconds * args.fps)
    chans = [args.rgb, args.rgb + 1, args.rgb + 2] + ([args.dimmer] if args.dimmer else [])

    def values(i):
        r, g, b = colorsys.hsv_to_rgb((i / args.fps / 10) % 1.0, 1.0, 1.0)
        return [int(c * 255) for c in (r, g, b)] + ([255] if args.dimmer else [])

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as f:
        if args.raw:
            f.write(build_header(args.name, args.mp3, FRAME_SIZE, len(chans)))
            for i in range(n):
                frame = bytearray(FRAME_SIZE)
                for ch, v in zip(chans, values(i)):
                    frame[ch - 1] = v
                f.write(frame)
        else:
            f.write(build_header(args.name, args.mp3, 6 + 3 * len(chans), len(chans)))
            f.write(bytes(DATA_OFFSET - HEADER_SIZE))
            for i in range(n):
                f.write(struct.pack("<IH", round(i * 1000 / args.fps), 3 * len(chans)))
                for ch, v in zip(chans, values(i)):
                    f.write(struct.pack("<HB", ch, v))
    print(f"{args.output}: {n} кадъра, {n / args.fps:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
