"""Парсване на .wds файлове (Syncronorm Depence / OASE WECS).

Реален формат (разчетен от Test.wds, експортиран от Depence за OASE WECS):

    [0 .. 1023]      хедър, 1024 B
        0x00  "OA"         магически байтове
        0x02  u16          размер на запис в байтове (Test.wds: 15) - хипотеза
        0x04  u16          версия? (2)
        0x06  char[]       име на шоуто, завършва с 0x00
        0x2F  u8 x 3       неизвестни (01 03 01; 03 = брой канали?)
        0x32  char[]       име на аудио файла, завършва с 0x00
        0x5E  u8           100 (сила на звука %?) - хипотеза
    [1024 .. start)  нули (в Test.wds до 17507) - запазена/неизползвана зона
    [start .. EOF]   поредица от записи (little-endian):
        u32  време в ms от началото на шоуто (0, 40, 80 ... = 25 fps)
        u16  N = брой байтове данни (кратно на 3)
        N/3 x { u16 DMX канал (1-базиран), u8 стойност }

Каналите, които не присъстват в запис, запазват предишната си стойност.

Поддържа се и описаният в заданието "суров" формат (хедър 1024 B + кадри по
512 B @ 25 fps) - използва се, ако файлът не съдържа валидна верига записи.

Използване от конзолата:
    python3 wds_parser.py show.wds           # информация за файла
    python3 wds_parser.py show.wds --dump    # + hex дъмп на хедъра и записи
"""

from __future__ import annotations

import os
import re
import struct
from bisect import bisect_right
from dataclasses import dataclass

HEADER_SIZE = 1024
FRAME_SIZE = 512
DMX_CHANNELS = 512
DEFAULT_FPS = 25
MAGIC = b"OA"

FORMAT_RECORDS = "records"
FORMAT_RAW = "raw"

_REC_HEAD = struct.Struct("<IH")
_CHAN = struct.Struct("<HB")
_VALIDATE_RECORDS = 20  # толкова записа трябва да са валидни, за да приемем началото

_ASCII_RE = re.compile(rb"[\x20-\x7e]{3,}")
_UTF16_RE = re.compile(rb"(?:[\x20-\x7e]\x00){3,}")
_AUDIO_EXT = (".mp3", ".wav", ".ogg", ".flac", ".aif", ".aiff")


class WDSError(Exception):
    """Грешка при отваряне/четене на .wds файл."""


@dataclass(frozen=True)
class WDSInfo:
    path: str
    file_size: int
    format: str               # FORMAT_RECORDS или FORMAT_RAW
    data_offset: int          # откъде започват DMX данните
    frame_count: int
    duration: float           # секунди
    show_name: str
    audio_file: str | None
    channels: tuple[int, ...]  # използвани DMX канали (1-базирани)
    warnings: tuple[str, ...] = ()

    @property
    def file_name(self) -> str:
        return os.path.basename(self.path)

    @property
    def fps(self) -> float:
        return self.frame_count / self.duration if self.duration else DEFAULT_FPS


# ---------------------------------------------------------------- хедър
def _decode(raw: bytes) -> str:
    raw = raw.split(b"\x00", 1)[0]
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1").strip()


def extract_header_strings(header: bytes) -> list[str]:
    """Връща четимите текстови низове от хедъра (ASCII и UTF-16LE)."""
    found: list[tuple[int, str]] = []
    for m in _ASCII_RE.finditer(header):
        found.append((m.start(), m.group().decode("ascii").strip()))
    for m in _UTF16_RE.finditer(header):
        found.append((m.start(), m.group().decode("utf-16-le").strip()))
    found.sort()
    result: list[str] = []
    for _, s in found:
        if s and s not in result:
            result.append(s)
    return result


def parse_header(header: bytes, fallback_name: str) -> tuple[str, str | None]:
    """Връща (име на шоуто, име на аудио файла)."""
    if header[:2] == MAGIC:
        show = _decode(header[0x06:0x2F])
        audio = _decode(header[0x32:0x5E]) or None
        return show or fallback_name, audio

    # Непознат хедър - търсим текстови низове.
    strings = extract_header_strings(header)
    audio = next((s for s in strings if s.lower().endswith(_AUDIO_EXT)), None)
    if audio:
        audio = re.split(r"[\\/]", audio)[-1]
    show = next(
        (s for s in strings
         if s != audio and not s.lower().endswith(_AUDIO_EXT)
         and sum(c.isalpha() for c in s) >= 3),
        None,
    )
    return show or fallback_name, audio


# ---------------------------------------------------------------- записи
def _valid_record(data: bytes, pos: int, prev_ms: int | None) -> tuple[int, int] | None:
    """Проверява запис на `pos`; връща (време_ms, следваща позиция) или None."""
    if pos + _REC_HEAD.size > len(data):
        return None
    ms, n = _REC_HEAD.unpack_from(data, pos)
    end = pos + _REC_HEAD.size + n
    if n == 0 or n % 3 or end > len(data):
        return None
    if prev_ms is not None and ms < prev_ms:
        return None
    for k in range(pos + _REC_HEAD.size, end, 3):
        ch, _ = _CHAN.unpack_from(data, k)
        if ch == 0:
            return None
    return ms, end


def find_records_start(data: bytes) -> int | None:
    """Намира началото на веригата записи след хедъра.

    Зоната след хедъра е запълнена с нули, а първият запис е с време 0,
    затова кандидатите са позициите преди първия ненулев байт.
    """
    first = next((i for i in range(HEADER_SIZE, len(data)) if data[i]), None)
    if first is None:
        return None
    # Записът започва с u32 време (може да е 0) и u16 дължина (ненулева).
    for start in range(max(HEADER_SIZE, first - 5), first + 1):
        pos, prev, ok = start, None, 0
        while ok < _VALIDATE_RECORDS:
            r = _valid_record(data, pos, prev)
            if r is None:
                break
            prev, pos = r
            ok += 1
        if ok == _VALIDATE_RECORDS or (ok and pos == len(data)):
            return start
    return None


class WDSFile:
    """Отворен .wds файл: всички DMX кадри са разгънати в памет по 512 B.

    Кадър i е пълното състояние на 512-те канала и трябва да се изпрати в
    момент frame_time(i) секунди от началото на шоуто.
    """

    def __init__(self, path: str, fps: int = DEFAULT_FPS):
        self.path = path
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            raise WDSError(f"Файлът не може да бъде отворен: {e}") from e
        if len(data) < HEADER_SIZE + _REC_HEAD.size:
            raise WDSError(f"Файлът е твърде малък ({len(data)} B)")

        self.header = data[:HEADER_SIZE]
        stem = os.path.splitext(os.path.basename(path))[0]
        show, audio = parse_header(self.header, stem)

        start = find_records_start(data)
        if start is not None:
            self._load_records(data, start)
            fmt = FORMAT_RECORDS
        else:
            self._load_raw(data, fps)
            start = HEADER_SIZE
            fmt = FORMAT_RAW
        if not self._times:
            raise WDSError("Във файла няма DMX кадри")

        self.info = WDSInfo(
            path=path,
            file_size=len(data),
            format=fmt,
            data_offset=start,
            frame_count=len(self._times),
            duration=self._duration,
            show_name=show,
            audio_file=audio,
            channels=self._channels,
            warnings=tuple(self._warnings),
        )

    def _load_records(self, data: bytes, start: int) -> None:
        state = bytearray(DMX_CHANNELS)
        frames = bytearray()
        times: list[float] = []
        used: set[int] = set()
        warnings: list[str] = []
        ignored: set[int] = set()
        pos, prev = start, None
        while pos < len(data):
            r = _valid_record(data, pos, prev)
            if r is None:
                warnings.append(f"Невалиден/непълен запис на offset {pos}; "
                                f"пропуснати {len(data) - pos} B в края")
                break
            ms, end = r
            for k in range(pos + _REC_HEAD.size, end, 3):
                ch, val = _CHAN.unpack_from(data, k)
                if ch > DMX_CHANNELS:
                    ignored.add(ch)  # 2-ри и следващ universe - не се поддържа
                    continue
                state[ch - 1] = val
                used.add(ch)
            times.append(ms / 1000.0)
            frames += state
            prev, pos = ms, end
        if ignored:
            warnings.append(f"Канали над 512 се игнорират ({min(ignored)}..{max(ignored)})")

        # Продължителност = последен кадър + типичния интервал между кадрите.
        step = (times[-1] - times[0]) / (len(times) - 1) if len(times) > 1 else 1 / DEFAULT_FPS
        self._times = times
        self._frames = bytes(frames)
        self._duration = times[-1] + step
        self._channels = tuple(sorted(used))
        self._warnings = warnings

    def _load_raw(self, data: bytes, fps: int) -> None:
        payload = data[HEADER_SIZE:]
        count = len(payload) // FRAME_SIZE
        self._frames = payload[:count * FRAME_SIZE]
        self._times = [i / fps for i in range(count)]
        self._duration = count / fps
        self._channels = tuple(
            ch for ch in range(1, DMX_CHANNELS + 1)
            if any(self._frames[i * FRAME_SIZE + ch - 1] for i in range(count))
        )
        self._warnings = []
        if len(payload) % FRAME_SIZE:
            self._warnings.append(f"{len(payload) % FRAME_SIZE} B след последния пълен кадър")

    @property
    def frame_count(self) -> int:
        return len(self._times)

    def frame_time(self, index: int) -> float:
        """Момент (s от началото), в който кадър `index` трябва да се изпрати."""
        return self._times[index]

    def frame_at(self, seconds: float) -> int:
        """Индекс на кадъра, валиден в момент `seconds`."""
        return max(0, bisect_right(self._times, seconds) - 1)

    def read_frame(self, index: int) -> bytes:
        """Пълното състояние на 512-те канала за кадър `index` (0-базиран)."""
        if not 0 <= index < len(self._times):
            raise IndexError(f"Кадър {index} е извън 0..{len(self._times) - 1}")
        off = index * FRAME_SIZE
        return self._frames[off:off + FRAME_SIZE]

    def frames(self, start: int = 0):
        for i in range(start, self.frame_count):
            yield self.read_frame(i)

    def close(self) -> None:
        self._frames = b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _hexdump(data: bytes, base: int = 0, width: int = 16) -> str:
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 0x20 <= b < 0x7f else "." for b in chunk)
        lines.append(f"{base + off:06x}  {hexs:<{width * 3}} {text}")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Информация за .wds файл")
    ap.add_argument("file")
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS, help="само за суров формат")
    ap.add_argument("--dump", action="store_true", help="hex дъмп на хедъра и първите записи")
    ap.add_argument("--changes", action="store_true", help="списък с промените на стойностите")
    args = ap.parse_args(argv)

    with WDSFile(args.file, fps=args.fps) as wds:
        i = wds.info
        print(f"Файл:          {i.file_name}")
        print(f"Размер:        {i.file_size} B")
        print(f"Формат:        {i.format} (данни от offset {i.data_offset})")
        print(f"Шоу:           {i.show_name}")
        print(f"Аудио:         {i.audio_file or '-'}")
        print(f"Кадри:         {i.frame_count} (~{i.fps:.2f} fps)")
        print(f"Времетраене:   {format_time(i.duration)} ({i.duration:.2f} s)")
        print(f"Канали:        {', '.join(map(str, i.channels)) or '-'}")
        for w in i.warnings:
            print(f"ВНИМАНИЕ:      {w}")
        if args.changes:
            prev = None
            for n in range(wds.frame_count):
                vals = tuple(wds.read_frame(n)[c - 1] for c in i.channels)
                if vals != prev:
                    print(f"  {wds.frame_time(n):8.3f}s  {vals}")
                    prev = vals
        if args.dump:
            with open(args.file, "rb") as fh:
                raw = fh.read()
            print(_hexdump(raw[:0x60]))
            print("...")
            print(_hexdump(raw[i.data_offset:i.data_offset + 0x60], i.data_offset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
