#!/usr/bin/env python3
"""WDS DMX Player - входна точка.

Примери:
    python3 main.py                       # реален DMX изход на /dev/serial0
    python3 main.py --fullscreen          # за тъч дисплея
    python3 main.py --sim                 # без хардуер (разработка на PC)
    python3 main.py --de-gpio 18          # MAX485 модул без авто-посока
    python3 main.py --file show.wds       # зарежда файл при старт
    python3 main.py --lang en             # английски интерфейс (bg|en)
    python3 main.py --audio-device alsa/plughw:CARD=Headphones   # звук през 3.5 mm жака
    python3 main.py --audio-offset 150    # звукът върви 150 ms пред DMX (компенсация)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import i18n  # noqa: E402
from audio import AudioPlayer, NullAudio  # noqa: E402
from dmx_engine import DEFAULT_PORT, DMXOutput, NullDMXOutput  # noqa: E402
from player import DMXPlayer  # noqa: E402
from controller import Controller, apply_settings  # noqa: E402
from inputs import InputMonitor  # noqa: E402
import schedule_file  # noqa: E402
import timeplaner  # noqa: E402
from scheduler import Scheduler  # noqa: E402
import settings as settings_mod  # noqa: E402
from settings import Settings  # noqa: E402
from wds_parser import DEFAULT_FPS  # noqa: E402


def default_shows_dir() -> str:
    for d in ("/home/pi/shows", os.path.expanduser("~/shows")):
        if os.path.isdir(d):
            return d
    return os.path.expanduser("~")


def use_data_dir(data_dir: str) -> str:
    """Настройките и шоутата живеят в отделна папка за писане (напр. USB флашка), докато
    системата е само за четене. Връща папката с шоута. Липсваща папка -> нищо не се променя."""
    config = os.path.join(data_dir, "config")
    shows = os.path.join(data_dir, "shows")
    for d in (config, shows):
        os.makedirs(d, exist_ok=True)
    settings_mod.CONFIG_FILE = os.path.join(config, "settings.json")
    i18n.CONFIG_FILE = os.path.join(config, "lang")
    return shows


def main() -> int:
    ap = argparse.ArgumentParser(description="WDS DMX Player")
    ap.add_argument("--port", default=DEFAULT_PORT, help=f"сериен порт (по подразбиране {DEFAULT_PORT})")
    ap.add_argument("--sim", action="store_true", help="симулиран DMX изход, без хардуер")
    ap.add_argument("--break-mode", choices=("break", "baud"), default="break",
                    help="начин на генериране на DMX BREAK (вж. dmx_engine.py)")
    ap.add_argument("--de-gpio", type=int, default=None,
                    help="GPIO за DE/RE на MAX485 (напр. 18); без него - авто-посока/твърдо 3.3V")
    ap.add_argument("--fps", type=int, default=None,
                    help="честота на кадрите (по подразбиране от ⚙ Настройки → DMX)")
    ap.add_argument("--no-hold", action="store_true",
                    help="при ПАУЗА спира излъчването изцяло (по подразбиране кадърът се задържа)")
    ap.add_argument("--shows-dir", default=None,
                    help="папка с шоута (по подразбиране shows/ в --data-dir, иначе ~/shows)")
    ap.add_argument("--data-dir", default=os.environ.get("WDS_DATA_DIR"),
                    help="папка за настройки и шоута, напр. на USB флашка (/mnt/data/wds_player); "
                         "позволява системата да е само за четене")
    ap.add_argument("--file", help=".wds файл за зареждане при старт")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--no-audio", action="store_true", help="без звук (mpv не се стартира)")
    ap.add_argument("--audio-device", help="изход за звука за mpv (списък: mpv --audio-device=help)")
    ap.add_argument("--audio-offset", type=int, default=None, metavar="MS",
                    help="милисекунди; положително = звукът върви по-напред от DMX "
                         "(по подразбиране стойността от ⚙ Настройки)")
    ap.add_argument("--no-planner", action="store_true", help="без работа по TimePlaner.xml")
    ap.add_argument("--no-catchup", action="store_true",
                    help="при старт не пуска шоуто, което по TimePlaner.xml трябва да върви в момента")
    ap.add_argument("--no-gpio", action="store_true", help="без цифрови входове (GPIO не се докосва)")
    ap.add_argument("--lang", choices=i18n.LANGS,
                    help="език на интерфейса (по подразбиране последният избран, иначе bg)")
    args = ap.parse_args()
    sys.setswitchinterval(0.001)   # по-бърза размяна на GIL: интерфейсът по-малко бави DMX нишката

    if args.data_dir:
        try:
            data_shows = use_data_dir(args.data_dir)
            if args.shows_dir is None:
                args.shows_dir = data_shows
        except OSError as e:
            print(f"Внимание: папката за данни {args.data_dir} не е достъпна ({e}); "
                  "ползват се стандартните места.", file=sys.stderr)
    if args.shows_dir is None:
        args.shows_dir = default_shows_dir()

    i18n.load_saved()
    if args.lang:
        i18n.set_lang(args.lang)

    if args.sim:
        output = NullDMXOutput()
    else:
        output = DMXOutput(args.port, break_mode=args.break_mode, de_gpio=args.de_gpio)

    settings = Settings.load()
    if args.audio_offset is not None:
        settings.audio_offset_ms = args.audio_offset
    audio = NullAudio() if args.no_audio else AudioPlayer(audio_device=args.audio_device,
                                                          volume=settings.volume)
    if args.fps:
        settings.dmx_fps = args.fps
    if args.no_hold:
        settings.pause_mode = "off"
    settings.clamp()
    player = DMXPlayer(output, fps=settings.dmx_fps, hold_on_pause=not args.no_hold, audio=audio)
    apply_settings(player, settings)
    player.start()
    # Последното шоу се зарежда само - така автостартът работи и след рестарт
    first = args.file or (settings.last_file if os.path.isfile(settings.last_file) else None)
    if first:
        settings.last_file = first
        player.load(first, settings.audio_overrides.get(first))

    dirs = {args.shows_dir, os.path.dirname(settings.last_file)} | {
        os.path.dirname(t["show"]) for t in settings.timers if t["show"]}
    if schedule_file.import_all(settings, dirs):         # Шоу.wds.schedule до шоутата
        settings.save()
    controller = Controller(player, settings)
    scheduler = Scheduler(lambda: settings.timers, controller.on_timer, fire_end=controller.on_timer_end)   # графици (по час и дни)
    scheduler.start()
    if settings.system:                      # система само за четене: часова зона и IP от настройките
        import sysconf
        if sysconf.read_only_root():
            import threading
            threading.Thread(target=sysconf.apply_saved, args=(settings.system,), daemon=True).start()
    if settings.boot_play:                   # автоматично пускане на шоу при включване
        import threading
        boot = threading.Timer(settings.boot_delay, controller.boot_play)
        boot.daemon = True
        boot.start()
    planner = None
    if not args.no_planner:                  # TimePlaner.xml от Depence (в папката на шоутата)
        shows = args.shows_dir
        planner = timeplaner.PlanRunner(
            lambda: [shows, os.path.dirname(shows), os.path.expanduser("~")],
            controller.on_plan_play, controller.on_plan_stop, show_dirs=[shows],
            enabled=lambda: settings.planner_enabled, catchup=not args.no_catchup)
        planner.start()
    monitor = None
    if not args.no_gpio:                                                  # цифрови входове DI 0..7
        monitor = InputMonitor(lambda: (settings.inputs_enabled, [i["pin"] for i in settings.inputs]),
                               controller.on_input)
        monitor.start()

    import tkinter as tk
    from gui import PlayerApp

    root = tk.Tk()
    PlayerApp(root, player, args.shows_dir, output.description, fullscreen=args.fullscreen,
              settings=settings, controller=controller, monitor=monitor, planner=planner)
    try:
        root.mainloop()
    finally:
        scheduler.stop()
        if planner is not None:
            planner.stop()
        if monitor:
            monitor.stop()
        player.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
