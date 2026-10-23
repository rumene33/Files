#!/usr/bin/env python3
"""Проверка на звука: пуска файл през същия mpv като плейъра и показва състоянието му.

    python3 tools/audio_check.py "/home/rpi/New folder/Audio Video Sync Test.mp3"
    python3 tools/audio_check.py песен.mp3 --audio-device alsa/plughw:CARD=Headphones --seconds 6

Ако позицията (time-pos) расте, плейърът изпраща звука правилно; тогава липсата на звук е
проблем на аудио изхода (колона, сила на звука, избрано устройство).
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio import AudioError, AudioPlayer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка на звука през mpv")
    ap.add_argument("file")
    ap.add_argument("--audio-device")
    ap.add_argument("--seconds", type=float, default=4.0)
    args = ap.parse_args()

    audio = AudioPlayer(audio_device=args.audio_device)
    print(f"mpv намерен:        {audio.available}")
    if not audio.available:
        print("-> sudo apt install mpv")
        return 1
    try:
        audio.load(args.file)
        time.sleep(1.0)
        audio.play(0.0)
        print(f"Пускам {args.seconds:.0f} s ...")
        time.sleep(args.seconds)
        pos = audio.query("time-pos")
        print(f"позиция (time-pos): {pos}")
        for prop in ("pause", "mute", "volume", "current-ao", "audio-device", "audio-codec-name",
                     "audio-params/samplerate", "audio-params/channel-count"):
            print(f"{prop:20s}{audio.query(prop)}")
        audio.stop()
    except AudioError as e:
        print("ГРЕШКА:", e)
        return 1
    finally:
        audio.close()

    print(f"\nДневник на mpv: {audio.log_path}")
    try:
        with open(audio.log_path, encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines()[-12:]:
                print("  ", line)
    except OSError:
        pass
    if pos and pos > args.seconds * 0.5:
        print("\nВЕРДИКТ: mpv възпроизвежда (позицията расте). Ако не чувате звук - проверете "
              "колоната/кабела, силата (alsamixer) и избраното устройство (--audio-device).")
        return 0
    print("\nВЕРДИКТ: mpv не възпроизвежда. Вижте дневника по-горе.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
