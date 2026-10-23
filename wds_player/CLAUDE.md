# WDS DMX Player – контекст за Claude Code

Самостоятелен плейър на `.wds` DMX шоута за Raspberry Pi 3B (SSH/PuTTY, тъч екран 800x480, Python + Tkinter,
DMX през TTL‑RS485 на /dev/serial0, звук през mpv). Потребителят говори български; отговаряй на български.
Притежава и Syncronorm V:Nano (192.168.1.250).

## Структура
- `main.py` – старт, аргументи (`--data-dir`, `--no-planner`, `--no-catchup`, `--fps`), нишки: Scheduler, PlanRunner, boot_play.
- `player.py`, `dmx_engine.py`, `audio.py`, `wds_parser.py` – възпроизвеждане, DMX изход, звук, формат .wds.
- `settings.py` – настройки (JSON, права 600, атомичен запис); график = `{on, days, date, h, m, s, show, end_on, eh, em, es}`.
- `scheduler.py` – графици (дата или всяка седмица; край на график); `timeplaner.py` – TimePlaner.xml (PlanRunner).
- `controller.py` – команди; график с край => повторения 0 (безкрайно) до края.
- `sysconf.py` – мрежа (nmcli), час/зона (timedatectl), Wi‑Fi; `sudo -n` fallback; `apply_saved` при старт.
- `schedule_file.py` – `Шоу.wds.schedule`; `power.py` – изключване/рестарт.
- UI: `gui.py` (главен екран), `ui_kit.py`, `settings_ui.py`, `agenda.py`, `agenda_ui.py` (календар ден/месец/година, линейни графики за трите изгледа).
- `i18n.py` – BG/EN; `install.sh` – инсталация (sudoers правило, overlay/USB опции).

## Тестове
`python3 -m unittest discover -s tests` (123 теста) и `python3 tests/smoke_ui_stub.py` (UI със заместител на tkinter).
В тази среда няма tkinter – UI не е виждан на реален екран.

## Известни неща / внимание
- На Pi трябва sudoers правилото `/etc/sudoers.d/wds-player` (създава го install.sh), иначе смяната на час/зона/мрежа
  дава „sudo: a password is required“.
- Wi‑Fi паролата се пази в settings.json в чист текст (права 600).
- Pi няма RTC: без NTP часът е грешен; Scheduler пропуска скокове на часовника >5 s.
- Семантиката на годишния план в TimePlaner.xml на V:Nano („само една дата“) е предположение.
- Нищо от Pi специфичните функции не е пробвано на истинския Pi – само тестове.
- Не ползвай `self._w` / `self._name` в наследници на tk widget-и: това са вътрешни имена на Tkinter
  (така `Pill` чупеше „Програма по TimePlaner“). Тест на истински Tk: `xvfb-run python3.12 ...` (тук само 3.12 има tkinter).
