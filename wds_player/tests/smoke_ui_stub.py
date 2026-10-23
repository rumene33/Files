import sys, types, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
class W:
    def __init__(self, master=None, *a, **k):
        self.children = []; self.master = master; self.alive = True; self.k = dict(k)
        if isinstance(master, W): master.children.append(self)
    def winfo_children(self): return list(self.children)
    def winfo_exists(self): return self.alive
    def winfo_width(self): return 800
    def winfo_height(self): return 480
    def winfo_reqwidth(self): return 800
    def winfo_reqheight(self): return 2000
    def destroy(self):
        self.alive = False
        if isinstance(self.master, W) and self in self.master.children: self.master.children.remove(self)
    def after(self, *a, **k): return 1
    def config(self, **k): self.k.update(k)
    configure = config
    def __getitem__(self, k): return self.k.get(k, "#000000")
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        return lambda *a, **k: 0
class Lbl(W): pass
tk = types.ModuleType("tkinter")
for n in ("Frame","Button","Canvas","Toplevel","Tk","Scale","Listbox"): setattr(tk, n, type(n, (W,), {}))
tk.Label = Lbl; tk.TclError = Exception
sys.modules["tkinter"] = tk
sys.modules["tkinter.ttk"] = types.ModuleType("tkinter.ttk")
import ui_kit as ui, settings_ui as su, sysconf
from settings import Settings
from datetime import date
import schedule_file

# рекордер на редовете
rows = []
orig_row = ui.row
def rec(card, title, *a, **k):
    f = orig_row(card, title, *a, **k); rows.append((title, k.get("command") or (a[2] if len(a) > 2 else None), k.get("widget"), f)); return f
ui.row = rec

# фалшив sysconf
def fake_run(cmd, runner=None, timeout=25, use_sudo=True):
    return True, ""
sysconf.run = lambda cmd, runner=None, timeout=25, use_sudo=True: (True, "")
sysconf.net_devices = lambda *a, **k: [{"dev": "eth0", "type": "ethernet", "state": "connected", "conn": "Wired"},
                                       {"dev": "wlan0", "type": "wifi", "state": "disconnected", "conn": ""}]
sysconf.net_info = lambda dev, *a, **k: {"ip": "192.168.1.50", "prefix": "24", "gw": "192.168.1.1", "dns": "8.8.8.8", "method": "auto", "conn": "Wired"}
sysconf.wifi_scan = lambda *a, **k: [{"ssid": "Home", "signal": 80, "secure": True, "active": False}]
sysconf.list_timezones = lambda *a, **k: ["Europe/Sofia", "Europe/Berlin", "UTC", "Asia/Tokyo"]
sysconf.time_status = lambda *a, **k: {"timezone": "Europe/Sofia", "ntp": True, "synced": True}
sysconf.read_only_root = lambda *a, **k: True
calls = []
sysconf.set_ip = lambda *a, **k: (calls.append(("set_ip", a)) or (True, ""))
sysconf.set_timezone = lambda tz, *a, **k: (calls.append(("tz", tz)) or (True, ""))
sysconf.set_time = lambda dt, *a, **k: (calls.append(("time", dt)) or (True, ""))
sysconf.set_ntp = lambda on, *a, **k: (calls.append(("ntp", on)) or (True, ""))

# run_bg синхронно
su.run_bg = lambda widget, fn, done: done(fn())

class App: pass
d = tempfile.mkdtemp()
app = App()
app.settings = Settings(); app.root = W(); app.shows_dir = d; app.planner = None
app.apply_settings = lambda *a, **k: app.settings.clamp()
app.pick_file = lambda start, cb: cb(os.path.join(d, "Show.wds"))
app.open_inputs = app.open_agenda = app.open_power = lambda: None
app.switch_language = lambda: None
import settings as S
S.CONFIG_FILE = os.path.join(d, "settings.json")
app.settings.save = lambda path=None, _s=app.settings: Settings.save(_s, S.CONFIG_FILE)

nav = ui.Navigator(app.root, "Настройки", lambda n, b: su.main_page(app, n, b), cover=lambda w, m: None)
nav._cover = lambda w, m: None
print("main rows:", [r[0] for r in rows])
rows.clear()

def push(title_sub):
    # намира ред по заглавие и вика командата му
    for r in rows: pass
for page, fn in (("playback", su.playback_page), ("boot", su.boot_page), ("dmx", su.dmx_page),
                 ("schedules", su.schedules_page), ("network", su.network_page), ("time", su.time_page),
                 ("manual", su.manual_time_page), ("tz", su.tz_page), ("wifi", su.wifi_page)):
    rows.clear(); b = W(nav)
    fn(app, nav, b)
    print(page, "OK", len(rows), "rows")

# --- график по дата: нов, запис ---
nav2 = nav
b = W(nav); tm_page = su.timer_page
nav._drafts = {}
rows.clear(); tm_page(app, nav, b, None)
draft = nav._drafts[("draft", None)]
draft["date"] = "2026-10-23"; draft["h"] = 12; draft["show"] = os.path.join(d, "Show.wds")
open(draft["show"], "wb").close()
rows.clear(); b = W(nav); tm_page(app, nav, b, None)       # прерисува в режим дата
titles = [r[0] for r in rows]; print("date-mode rows:", titles)
save = [r for r in rows if r[0] == "Запази"][0][1]
backs = []
nav.back = lambda: backs.append(1)
save()
print("saved timers:", app.settings.timers)
assert app.settings.timers[0]["date"] == "2026-10-23"
print("sidecar exists:", os.path.exists(os.path.join(d, "Show.wds.schedule")))
# правилата за дата
from scheduler import next_fire, applies_on
from datetime import datetime
print("applies 23.10:", applies_on(app.settings.timers[0], date(2026,10,23)), " 30.10:", applies_on(app.settings.timers[0], date(2026,10,30)))
# изтриване
rows.clear(); b = W(nav); nav._drafts = {}; tm_page(app, nav, b, 0)
[r for r in rows if r[0] == "Изтрий графика"][0][1]()
print("after delete:", app.settings.timers)
# степер: дата 31 -> месец със 30 дни
st = ui.Stepper.__new__(ui.Stepper)
# мрежа: прилагане
nav._drafts = {}; b = W(nav); rows.clear(); su.device_page(app, nav, b, {"dev": "eth0", "type": "ethernet", "state": "connected", "conn": "Wired"})
cfg = nav._drafts[("net", "eth0")]; cfg["method"] = "manual"; cfg["ip"] = "192.168.1.60"
rows.clear(); b = W(nav); su.device_page(app, nav, b, {"dev": "eth0", "type": "ethernet", "state": "connected", "conn": "Wired"})
print("device rows:", [r[0] for r in rows])
[r for r in rows if r[0] == "Приложи"][0][1]()
print("calls:", calls); print("system:", app.settings.system)
# часова зона
su._set_tz(app, nav, "Asia/Tokyo"); print("tz saved:", app.settings.system.get("timezone"))
import agenda_ui, timeplaner, shutil
from settings import new_timer
from datetime import date
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "TimePlaner_sample.xml"), d + "/TimePlaner.xml")
for nm in ("Test_MUSIC", "Test_3"): open(f"{d}/{nm}.wds", "wb").close()
app.planner = timeplaner.PlanRunner([d], lambda *a: 0, lambda: 0); app.planner.reload()
tm = new_timer(); tm["date"] = "2026-10-23"; tm["end_on"] = True; app.settings.timers = [tm]
for view in ("day", "month", "year"):
    rows.clear()
    state = {"view": view, "day": date(2026, 10, 23)}
    agenda_ui.page(app, nav, W(nav), state)
    print("agenda", view, "OK", len(rows), "rows")
print("SMOKE OK")
