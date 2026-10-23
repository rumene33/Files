"""Многоезичност (български / английски) за интерфейса на плейъра.

    from i18n import t, set_lang, get_lang
    t("start")            # "СТАРТ" или "START" според избрания език

Изборът се пази във ~/.config/wds_player/lang, за да се запомни след рестарт.
Съобщенията за грешки идват от worker нишката и от парсера на български;
tr_error() ги превежда на английски, когато е избран английски.
"""

from __future__ import annotations

import os
import re

LANGS = ("bg", "en")
DEFAULT_LANG = "bg"
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".config", "wds_player", "lang")

STRINGS: dict[str, dict[str, str]] = {
    # --- прозорец и статус ---
    "window_title":   {"bg": "WDS DMX Player", "en": "WDS DMX Player"},
    "app_title":      {"bg": "WDS DMX Player", "en": "WDS DMX Player"},
    "state_IDLE":     {"bg": "ГОТОВНОСТ (IDLE)", "en": "READY (IDLE)"},
    "state_PLAYING":  {"bg": "ВЪЗПРОИЗВЕЖДАНЕ (PLAYING)", "en": "PLAYING"},
    "state_PAUSED":   {"bg": "ПАУЗА (PAUSED)", "en": "PAUSED"},
    # --- файл ---
    "no_file":        {"bg": "Няма зареден файл", "en": "No file loaded"},
    "press_load":     {"bg": "Натиснете „Зареди WDS“", "en": "Press “Load WDS”"},
    "load_wds":       {"bg": "Зареди WDS", "en": "Load WDS"},
    "show":           {"bg": "Шоу", "en": "Show"},
    "frame_info":     {"bg": "кадър {i} / {n} @ {fps:.0f} fps", "en": "frame {i} / {n} @ {fps:.0f} fps"},
    "dropped":        {"bg": "пропуснати: {n}", "en": "dropped: {n}"},
    # --- бутони ---
    "start":          {"bg": "СТАРТ", "en": "START"},
    "pause":          {"bg": "ПАУЗА", "en": "PAUSE"},
    "stop":           {"bg": "СТОП", "en": "STOP"},
    "loop_on":        {"bg": "ПОВТОРЕНИЕ\n∞", "en": "REPEAT\n∞"},
    "loop_n":         {"bg": "ПОВТОРЕНИЕ\n×{n}", "en": "REPEAT\n×{n}"},
    "loop_off":       {"bg": "ПОВТОРЕНИЕ\nИЗКЛ", "en": "REPEAT\nOFF"},
    # --- долен ред ---
    "dmx_ok":         {"bg": "OK", "en": "OK"},
    "dmx_no_link":    {"bg": "НЯМА ВРЪЗКА", "en": "NO LINK"},
    # --- файлов диалог ---
    "dlg_title":      {"bg": "Избор на WDS файл", "en": "Select WDS file"},
    "dlg_shows":      {"bg": "Шоута", "en": "Shows"},
    "dlg_home":       {"bg": "Начало", "en": "Home"},
    "dlg_usb":        {"bg": "USB: {name}", "en": "USB: {name}"},
    "dlg_up":         {"bg": "⬆ Нагоре", "en": "⬆ Up"},
    "dlg_cancel":     {"bg": "Отказ", "en": "Cancel"},
    "dlg_open":       {"bg": "Отвори", "en": "Open"},
    "dlg_empty":      {"bg": "    (няма подходящи файлове)", "en": "    (no matching files)"},
    "dlg_empty_all":  {"bg": "    (празна папка)", "en": "    (empty folder)"},
    "dlg_all_on":     {"bg": "☑ Всички файлове", "en": "☑ All files"},
    "dlg_all_off":    {"bg": "☐ Всички файлове", "en": "☐ All files"},
    "dlg_audio_title": {"bg": "Избор на аудио/видео файл", "en": "Select audio/video file"},
    "dlg_auto":       {"bg": "Автоматично", "en": "Automatic"},
    # --- аудио ---
    "audio_btn":      {"bg": "♪  Аудио", "en": "♪  Audio"},
    "volume":         {"bg": "Звук", "en": "Volume"},
    "no_audio":       {"bg": "няма звук", "en": "no audio"},
    # --- повторения / пауза / автостарт на главния екран ---
    "loop_info":      {"bg": "повторение {k}/{n}", "en": "loop {k}/{n}"},
    "gap_info":       {"bg": "пауза: {s} сек", "en": "pause: {s} s"},
    "auto_info":      {"bg": "⏰ автостарт {t}", "en": "⏰ auto start {t}"},
    # --- диалог за настройки ---
    "set_title":      {"bg": "Настройки", "en": "Settings"},
    "set_loops":      {"bg": "Повторения (0 = безкрайно)", "en": "Loops (0 = endless)"},
    "set_gap":        {"bg": "Пауза между повторенията (сек)", "en": "Time between loops (s)"},
    "set_auto":       {"bg": "Автоматичен старт всеки ден", "en": "Daily auto start"},
    "set_ask":        {"bg": "Питай за песен, ако шоуто няма", "en": "Ask for a song if none"},
    "set_offset":     {"bg": "Синхрон на звука (ms)", "en": "Audio sync (ms)"},
    "set_offset_hint": {"bg": "+ = звукът върви по-рано, − = по-късно (важи от следващия СТАРТ)", "en": "+ = sound earlier, − = later (applies from the next START)"},
    "set_time":       {"bg": "Начален час", "en": "Start time"},
    "set_on":         {"bg": "ВКЛ", "en": "ON"},
    "set_off":        {"bg": "ИЗКЛ", "en": "OFF"},
    "set_close":      {"bg": "Затвори", "en": "Close"},
    "pw_title":       {"bg": "Изключване на системата", "en": "Shut down the system"},
    "pw_text":        {"bg": "Плейърът ще спре и Raspberry Pi ще се изключи.\nИзчакайте да угасне зеленият светодиод, преди да махнете захранването.",
                       "en": "The player will stop and the Raspberry Pi will power off.\nWait until the green LED stops blinking before removing power."},
    "pw_off":         {"bg": "Изключи", "en": "Shut down"},
    "pw_reboot":      {"bg": "Рестарт", "en": "Reboot"},
    "pw_cancel":      {"bg": "Отказ", "en": "Cancel"},
    "pw_failed":      {"bg": "Неуспешно изключване - опитайте: sudo shutdown -h now", "en": "Shutdown failed - try: sudo shutdown -h now"},
    "pw_going":       {"bg": "Изключване...", "en": "Shutting down..."},
    "set_next":       {"bg": "Следващ старт: {when}  (след {left})", "en": "Next start: {when}  (in {left})"},
    "set_next_off":   {"bg": "Автоматичният старт е изключен", "en": "Auto start is off"},
    # --- графици и цифрови входове ---
    "set_timers":     {"bg": "Графици (старт по час)", "en": "Timers (start at time)"},
    "set_inputs":     {"bg": "Цифрови входове (GPIO)", "en": "Digital inputs (GPIO)"},
    "timers_n":       {"bg": "{n} активни  ›", "en": "{n} active  ›"},
    "timers_none":    {"bg": "няма  ›", "en": "none  ›"},
    "tm_title":       {"bg": "Графици", "en": "Timers"},
    "plan_btn":       {"bg": "TimePlaner: {state}", "en": "TimePlaner: {state}"},
    "plan_missing":   {"bg": "няма шоу за TimePlaner: {names}", "en": "no show file for TimePlaner: {names}"},
    "ag_btn":         {"bg": "Програма", "en": "Plan"},
    "ag_title":       {"bg": "Програма по TimePlaner", "en": "TimePlaner schedule"},
    "ag_none":        {"bg": "Няма TimePlaner.xml - сложете го в папката на шоутата", "en": "No TimePlaner.xml - put it in the shows folder"},
    "ag_summary":     {"bg": "{n} шоута планирани", "en": "{n} shows planned"},
    "ag_summary_1":   {"bg": "1 шоу планирано", "en": "1 show planned"},
    "ag_empty":       {"bg": "(за този ден няма планирани шоута)", "en": "(no shows planned for this day)"},
    "ag_manual":      {"bg": "график", "en": "timer"},
    "ag_end":         {"bg": "КРАЙ - спира всичко", "en": "END - stops everything"},
    "ag_endless":     {"bg": "безкрайно", "en": "endless"},
    "ag_today":       {"bg": "Днес", "en": "Today"},
    "plan_today":     {"bg": "днес", "en": "today"},
    "plan_shows":     {"bg": "шоута", "en": "shows"},
    "plan_end":       {"bg": "край", "en": "end"},
    "wd_0":           {"bg": "понеделник", "en": "Monday"},
    "wd_1":           {"bg": "вторник", "en": "Tuesday"},
    "wd_2":           {"bg": "сряда", "en": "Wednesday"},
    "wd_3":           {"bg": "четвъртък", "en": "Thursday"},
    "wd_4":           {"bg": "петък", "en": "Friday"},
    "wd_5":           {"bg": "събота", "en": "Saturday"},
    "wd_6":           {"bg": "неделя", "en": "Sunday"},
    "tm_add":         {"bg": "+ Добави", "en": "+ Add"},
    "tm_empty":       {"bg": "(няма графици - натиснете + Добави)", "en": "(no timers - press + Add)"},
    "tm_edit":        {"bg": "График", "en": "Timer"},
    "tm_enabled":     {"bg": "Включен", "en": "Enabled"},
    "tm_days":        {"bg": "Дни", "en": "Days"},
    "tm_time":        {"bg": "Час", "en": "Time"},
    "tm_show":        {"bg": "Шоу", "en": "Show"},
    "tm_current":     {"bg": "Текущото шоу", "en": "Current show"},
    "tm_end":         {"bg": "Край", "en": "End"},
    "tm_sidecar_ok":  {"bg": "Записва се и до шоуто: {name}", "en": "Also saved next to the show: {name}"},
    "tm_sidecar_ro":  {"bg": "⚠ Папката на шоуто е само за четене - графикът остава само в плейъра", "en": "⚠ The show folder is read-only - the timer stays in the player only"},
    "tm_sidecar_none": {"bg": "Без шоу (текущото): графикът се пази само в плейъра", "en": "No show (current): the timer is kept in the player only"},
    "tm_save":        {"bg": "Запази", "en": "Save"},
    "tm_delete":      {"bg": "Изтрий", "en": "Delete"},
    "tm_every_day":   {"bg": "всеки ден", "en": "every day"},
    "tm_no_days":     {"bg": "няма дни", "en": "no days"},
    "day_0":          {"bg": "Пн", "en": "Mo"},
    "day_1":          {"bg": "Вт", "en": "Tu"},
    "day_2":          {"bg": "Ср", "en": "We"},
    "day_3":          {"bg": "Чт", "en": "Th"},
    "day_4":          {"bg": "Пт", "en": "Fr"},
    "day_5":          {"bg": "Сб", "en": "Sa"},
    "day_6":          {"bg": "Нд", "en": "Su"},
    "di_title":       {"bg": "Цифрови входове", "en": "Digital inputs"},
    "di_hint":        {"bg": "▲ натиснат (пин към GND)   ▼ пуснат   |   3,3 V! без напрежение", "en": "▲ pressed (pin to GND)   ▼ released   |   3.3 V only! no voltage"},
    "di_pick":        {"bg": "Избор на шоу за входа", "en": "Select show for input"},
    "cmd_NoAction":   {"bg": "—", "en": "—"},
    "cmd_Play":       {"bg": "Старт", "en": "Play"},
    "cmd_Pause":      {"bg": "Пауза", "en": "Pause"},
    "cmd_Stop":       {"bg": "Стоп", "en": "Stop"},
    "cmd_TogglePlay": {"bg": "Старт/Пауза", "en": "Play/Pause"},
    "cmd_VolumeUp":   {"bg": "Звук +", "en": "Vol +"},
    "cmd_VolumeDown": {"bg": "Звук −", "en": "Vol −"},
    "cmd_PlayShow":   {"bg": "Шоу: {name}", "en": "Show: {name}"},
    "ev_input":       {"bg": "⚡ вход {n} {edge}: {cmd}", "en": "⚡ input {n} {edge}: {cmd}"},
    "ev_timer_end":   {"bg": "⏹ край на график", "en": "⏹ timer end"},
    "ev_timer":       {"bg": "⏰ график: {name}", "en": "⏰ timer: {name}"},
    "dlg_error":      {"bg": "Грешка: {e}", "en": "Error: {e}"},
}

# (шаблон на български съобщение, английски превод) - за tr_error()
_ERROR_PATTERNS = [
    (r"Няма зареден \.wds файл", "No .wds file loaded"),
    (r"Грешка при четене: (.*)", r"Read error: \1"),
    (r"Файлът не може да бъде отворен: (.*)", r"Cannot open file: \1"),
    (r"Файлът е твърде малък \((.*)\)", r"File is too small (\1)"),
    (r"Във файла няма DMX кадри", "The file contains no DMX frames"),
    (r"pyserial не е инсталиран: (.*)", r"pyserial is not installed: \1"),
    (r"GPIO (\d+) \(DE/RE\) не може да се управлява: (.*)", r"GPIO \1 (DE/RE) cannot be controlled: \2"),
    (r"Портът (.*) не може да се отвори: (.*)", r"Port \1 cannot be opened: \2"),
    (r"DMX портът не е отворен", "The DMX port is not open"),
    (r"Грешка при запис в (.*): (.*)", r"Write error on \1: \2"),
    (r"симулация \(без хардуер\)", "simulation (no hardware)"),
    (r"mpv не е инсталиран: (.*)", r"mpv is not installed: \1"),
    (r"mpv не може да се стартира: (.*)", r"mpv cannot be started: \1"),
    (r"mpv се затвори веднага след стартиране", "mpv exited right after starting"),
    (r"Няма връзка с mpv \(IPC\)", "No connection to mpv (IPC)"),
    (r"Връзката с mpv е прекъсната: (.*)", r"Connection to mpv lost: \1"),
    (r"mpv: грешка при зареждане на звука", "mpv: failed to load the audio file"),
    (r"Звуковият файл „(.*)“ не е намерен до шоуто", r"Audio file “\1” was not found next to the show"),
]
_COMPILED = [(re.compile(p, re.DOTALL), r) for p, r in _ERROR_PATTERNS]

_lang = DEFAULT_LANG


STRINGS.update({
    'ag_day': {"bg": "Ден", "en": "Day"}, 'ag_month': {"bg": "Месец", "en": "Month"}, 'ag_year': {"bg": "Година", "en": "Year"},
    'ag_total': {"bg": "Общо шоута", "en": "Total shows"}, 'ag_dot_hint': {"bg": "брой шоута за деня", "en": "shows that day"},
    'u_sudo_hint': {"bg": "Няма право без парола. Пусни install.sh отново (или добави sudoers правилото от README) и рестартирай плейъра.", "en": "No passwordless permission. Re-run install.sh (or add the sudoers rule from the README) and restart."},
    'u_end_hint_on': {"bg": "Шоуто се повтаря непрекъснато до часа на край и тогава спира.", "en": "The show repeats until the end time, then stops."},
    'u_end_hint_off': {"bg": "Без край шоуто свири веднъж (или по зададените повторения) и спира със песента.", "en": "Without an end time the show plays once (or per the repeat setting) and stops with the song."},
    'u_settings': {"bg": 'Настройки', "en": 'Settings'},
    'u_playback': {"bg": 'Възпроизвеждане', "en": 'Playback'},
    'u_schedules': {"bg": 'Графици', "en": 'Schedules'},
    'u_planner': {"bg": 'Работа по TimePlaner.xml', "en": 'Follow TimePlaner.xml'},
    'u_agenda': {"bg": 'Програма по дни', "en": 'Agenda by day'},
    'u_boot': {"bg": 'Автостарт при включване', "en": 'Autoplay at power-on'},
    'u_dmx': {"bg": 'DMX изход', "en": 'DMX output'},
    'u_inputs': {"bg": 'Цифрови входове', "en": 'Digital inputs'},
    'u_network': {"bg": 'Мрежа', "en": 'Network'},
    'u_datetime': {"bg": 'Дата и час', "en": 'Date & time'},
    'u_system': {"bg": 'Система', "en": 'System'},
    'u_loops': {"bg": 'Повторения', "en": 'Repeats'},
    'u_loops_sub': {"bg": '0 = безкрайно', "en": '0 = endless'},
    'u_gap': {"bg": 'Пауза между повторенията', "en": 'Pause between repeats'},
    'u_seconds': {"bg": 'секунди', "en": 'seconds'},
    'u_offset': {"bg": 'Синхрон на звука', "en": 'Audio sync'},
    'u_offset_sub': {"bg": '+ звукът е по-рано, − по-късно (ms)', "en": '+ earlier, − later (ms)'},
    'u_ask': {"bg": 'Питай за песен при зареждане', "en": 'Ask for audio when loading'},
    'u_new_sched': {"bg": 'Нов график', "en": 'New schedule'},
    'u_no_sched': {"bg": 'Няма графици. Добави с „Нов график“.', "en": 'No schedules yet. Add one with “New schedule”.'},
    'u_edit_sched': {"bg": 'График', "en": 'Schedule'},
    'u_active': {"bg": 'Включен', "en": 'Enabled'},
    'u_repeat': {"bg": 'Повторение', "en": 'Repeat'},
    'u_weekly': {"bg": 'Всяка седмица', "en": 'Every week'},
    'u_onedate': {"bg": 'Само на дата', "en": 'One date only'},
    'u_days': {"bg": 'Дни', "en": 'Days'},
    'u_day': {"bg": 'Ден', "en": 'Day'},
    'u_month': {"bg": 'Месец', "en": 'Month'},
    'u_year': {"bg": 'Година', "en": 'Year'},
    'u_hour': {"bg": 'Час', "en": 'Hour'},
    'u_minute': {"bg": 'Минути', "en": 'Minutes'},
    'u_second': {"bg": 'Секунди', "en": 'Seconds'},
    'u_start_time': {"bg": 'Начало', "en": 'Start'},
    'u_end_time': {"bg": 'Край (спира шоуто)', "en": 'End (stops the show)'},
    'u_show': {"bg": 'Шоу', "en": 'Show'},
    'u_show_cur': {"bg": 'Текущото шоу', "en": 'Current show'},
    'u_save': {"bg": 'Запази', "en": 'Save'},
    'u_delete': {"bg": 'Изтрий графика', "en": 'Delete schedule'},
    'u_onedate_hint': {"bg": 'Звучи само на тази дата и повече не се повтаря.', "en": 'Plays on this date only and never repeats.'},
    'u_past': {"bg": 'Датата е в миналото – графикът няма да се изпълни.', "en": 'The date is in the past – it will not run.'},
    'u_every_week': {"bg": 'всяка седмица', "en": 'every week'},
    'u_next': {"bg": 'Следващ старт', "en": 'Next start'},
    'u_next_none': {"bg": 'Няма предстоящи стартове', "en": 'No upcoming starts'},
    'u_boot_on': {"bg": 'Пускай шоу при включване', "en": 'Play a show at power-on'},
    'u_boot_show': {"bg": 'Шоу', "en": 'Show'},
    'u_boot_last': {"bg": 'Последното заредено', "en": 'Last loaded show'},
    'u_boot_delay': {"bg": 'Изчакване след старт', "en": 'Delay after start'},
    'u_boot_hint': {"bg": 'Шоуто тръгва само след включване на захранването/рестарт, не и при всяко отваряне на настройките.', "en": 'The show starts only after power-on/restart.'},
    'u_fps': {"bg": 'Кадри в секунда', "en": 'Frame rate'},
    'u_fps_sub': {"bg": 'Честота на обновяване при пауза/задържане и за суров формат', "en": 'Refresh rate for hold/pause and raw format'},
    'u_channels': {"bg": 'Брой канали', "en": 'Channel count'},
    'u_channels_sub': {"bg": 'Слотове в DMX пакета (24–512). По-малко = по-бързо', "en": 'Slots per DMX packet (24–512). Fewer = faster'},
    'u_pause': {"bg": 'При пауза', "en": 'On pause'},
    'u_stop': {"bg": 'При стоп', "en": 'On stop'},
    'u_hold': {"bg": 'Задържа', "en": 'Hold'},
    'u_blackout': {"bg": 'Тъмно', "en": 'Blackout'},
    'u_off': {"bg": 'Спира', "en": 'Off'},
    'u_pause_hint': {"bg": 'Задържа = последният кадър свети; Тъмно = всички канали 0; Спира = не се излъчва DMX.', "en": 'Hold = last frame stays; Blackout = all channels 0; Off = no DMX output.'},
    'u_stop_hint': {"bg": 'Тъмно = всички канали 0; Задържа = последният кадър; Спира = не се излъчва DMX.', "en": 'Blackout = all channels 0; Hold = last frame; Off = no DMX output.'},
    'u_ro_warn': {"bg": 'Системата е защитена (само за четене): промените се връщат автоматично след рестарт от записаните настройки.', "en": 'Read-only system: changes are re-applied from saved settings after reboot.'},
    'u_no_devices': {"bg": 'Не са намерени мрежови устройства (NetworkManager).', "en": 'No network devices found (NetworkManager).'},
    'u_connected': {"bg": 'Свързано', "en": 'Connected'},
    'u_disconnected': {"bg": 'Не е свързано', "en": 'Disconnected'},
    'u_dhcp': {"bg": 'Автоматично (DHCP)', "en": 'Automatic (DHCP)'},
    'u_static': {"bg": 'Статичен IP', "en": 'Static IP'},
    'u_ip': {"bg": 'IP адрес', "en": 'IP address'},
    'u_prefix': {"bg": 'Маска (бита)', "en": 'Prefix (bits)'},
    'u_gw': {"bg": 'Шлюз', "en": 'Gateway'},
    'u_dns': {"bg": 'DNS', "en": 'DNS'},
    'u_apply': {"bg": 'Приложи', "en": 'Apply'},
    'u_applying': {"bg": 'Прилагане…', "en": 'Applying…'},
    'u_done': {"bg": 'Готово', "en": 'Done'},
    'u_failed': {"bg": 'Неуспех', "en": 'Failed'},
    'u_wifi': {"bg": 'Wi‑Fi мрежи', "en": 'Wi‑Fi networks'},
    'u_scan': {"bg": 'Търсене…', "en": 'Scanning…'},
    'u_rescan': {"bg": 'Търси отново', "en": 'Scan again'},
    'u_wifi_pass': {"bg": 'Парола за ', "en": 'Password for '},
    'u_wifi_note': {"bg": 'Паролата се пази в настройките и се прилага при всеки старт.', "en": 'Password is saved in settings and re-applied at every start.'},
    'u_ntp': {"bg": 'Автоматично време (интернет)', "en": 'Set time automatically'},
    'u_now': {"bg": 'Сега', "en": 'Now'},
    'u_set_manual': {"bg": 'Задай дата и час ръчно', "en": 'Set date & time manually'},
    'u_timezone': {"bg": 'Часова зона', "en": 'Time zone'},
    'u_no_rtc': {"bg": 'Pi няма батерия за часовника: без интернет часът се губи при изключване.', "en": 'The Pi has no clock battery: without internet the time resets on power-off.'},
    'u_language': {"bg": 'Език', "en": 'Language'},
    'u_power': {"bg": 'Изключване / рестарт', "en": 'Power off / restart'},
    'u_back': {"bg": '‹  Назад', "en": '‹  Back'},
    'u_on': {"bg": 'Вкл', "en": 'On'},
    'u_off_s': {"bg": 'Изкл', "en": 'Off'},
    'u_planner_none': {"bg": 'TimePlaner.xml не е намерен', "en": 'TimePlaner.xml not found'},
    'u_shows_dir': {"bg": 'Показва се при следващия старт', "en": 'Applied at next start'},
    'u_sched_n': {"bg": '{n} вкл.', "en": '{n} on'},
    'u_none': {"bg": 'няма', "en": 'none'},
    'u_scroll_hint': {"bg": 'Плъзни с пръст за повече', "en": 'Drag to scroll'},
    'u_region': {"bg": 'Регион', "en": 'Region'},
    'u_pick_tz': {"bg": 'Избери часова зона', "en": 'Choose time zone'},
})


def get_lang() -> str:
    return _lang


def set_lang(lang: str, save: bool = True) -> None:
    global _lang
    if lang not in LANGS:
        raise ValueError(f"unknown language: {lang!r}")
    _lang = lang
    if save:
        _save()


def toggle_lang() -> str:
    set_lang("en" if _lang == "bg" else "bg")
    return _lang


def t(key: str, **kw) -> str:
    entry = STRINGS[key]
    text = entry.get(_lang) or entry[DEFAULT_LANG]
    return text.format(**kw) if kw else text


def tr_error(message: str | None) -> str | None:
    """Превежда известните съобщения за грешки; непознатите остават непроменени."""
    if not message or _lang == "bg":
        return message
    for rx, repl in _COMPILED:
        if rx.fullmatch(message):
            return rx.sub(repl, message)
    return message


def load_saved() -> str:
    """Зарежда запазения избор (ако има) и го прилага; връща текущия език."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            lang = f.read().strip()
        if lang in LANGS:
            set_lang(lang, save=False)
    except OSError:
        pass
    return _lang


def _save() -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(_lang)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass  # само-за-четене файлова система (kiosk) - езикът просто не се запомня
