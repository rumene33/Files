"""Графици, цифрови входове и контролер - без хардуер."""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio import NullAudio  # noqa: E402
from controller import Controller  # noqa: E402
from dmx_engine import NullDMXOutput  # noqa: E402
from inputs import InputMonitor  # noqa: E402
from player import DMXPlayer, State  # noqa: E402
from scheduler import Scheduler, next_fire, window  # noqa: E402
from settings import Settings, new_timer  # noqa: E402
from test_player import make_wds  # noqa: E402


def timer(h, m, s=0, days=range(7), show="", on=True, end=None):
    tm = {"on": on, "days": list(days), "h": h, "m": m, "s": s, "show": show}
    if end:
        tm.update(end_on=True, eh=end[0], em=end[1], es=end[2] if len(end) > 2 else 0)
    return tm


class NextFireTest(unittest.TestCase):
    now = datetime(2026, 10, 21, 10, 0, 0)       # сряда (weekday 2)

    def test_none_when_empty_or_off(self):
        self.assertIsNone(next_fire([], self.now))
        self.assertIsNone(next_fire([timer(11, 0, on=False)], self.now))
        self.assertIsNone(next_fire([timer(11, 0, days=[])], self.now))

    def test_today_tomorrow_and_weekday(self):
        self.assertEqual(next_fire([timer(11, 0)], self.now)[0], datetime(2026, 10, 21, 11, 0))
        self.assertEqual(next_fire([timer(9, 0)], self.now)[0], datetime(2026, 10, 22, 9, 0))
        # само събота (5) -> 24.10.
        self.assertEqual(next_fire([timer(9, 0, days=[5])], self.now)[0], datetime(2026, 10, 24, 9, 0))
        # само сряда, но часът мина -> следващата сряда
        self.assertEqual(next_fire([timer(9, 0, days=[2])], self.now)[0], datetime(2026, 10, 28, 9, 0))

    def test_earliest_wins(self):
        a, b = timer(15, 0), timer(12, 30)
        self.assertIs(next_fire([a, b], self.now)[1], b)


class SchedulerTest(unittest.TestCase):
    def make(self, timers, start):
        fired = []
        sch = Scheduler(lambda: timers, fired.append, clock=lambda: start)
        return sch, fired

    def test_fires_once_when_time_passes(self):
        t0 = datetime(2026, 10, 21, 10, 59, 59, 600000)
        tm = timer(11, 0)
        sch, fired = self.make([tm], t0)
        sch.check(t0 + timedelta(seconds=0.25))           # 10:59:59.85
        self.assertEqual(fired, [])
        sch.check(t0 + timedelta(seconds=0.5))            # 11:00:00.1
        self.assertEqual(fired, [tm])
        sch.check(t0 + timedelta(seconds=0.75))
        self.assertEqual(len(fired), 1)

    def test_weekday_filter_and_disabled(self):
        t0 = datetime(2026, 10, 21, 10, 59, 59, 800000)   # сряда
        sch, fired = self.make([timer(11, 0, days=[0, 1]), timer(11, 0, on=False)], t0)
        sch.check(t0 + timedelta(seconds=0.5))
        self.assertEqual(fired, [])

    def test_clock_jump_does_not_fire(self):
        t0 = datetime(2026, 10, 21, 10, 0, 0)
        sch, fired = self.make([timer(11, 0)], t0)
        sch.check(t0 + timedelta(hours=1, seconds=1))     # NTP скок над часа на графика
        self.assertEqual(fired, [])
        sch.check(t0 - timedelta(hours=5))                # скок назад
        self.assertEqual(fired, [])

    def test_midnight_boundary(self):
        t0 = datetime(2026, 10, 21, 23, 59, 59, 900000)
        tm = timer(0, 0, 0)
        sch, fired = self.make([tm], t0)
        sch.check(t0 + timedelta(seconds=0.25))
        self.assertEqual(fired, [tm])

    def test_thread_runs_and_stops(self):
        fired = []
        target = datetime.now() + timedelta(seconds=1.2)
        tm = timer(target.hour, target.minute, target.second)
        sch = Scheduler(lambda: [tm], fired.append, poll=0.05)
        sch.start()
        time.sleep(2.2)
        sch.stop()
        sch.join(1)
        self.assertEqual(len(fired), 1)


class EndTimeTest(unittest.TestCase):
    def test_window_same_day_and_over_midnight(self):
        day = datetime(2026, 10, 21).date()
        self.assertEqual(window(timer(18, 0), day), (datetime(2026, 10, 21, 18), None))
        self.assertEqual(window(timer(18, 0, end=(22, 30)), day),
                         (datetime(2026, 10, 21, 18), datetime(2026, 10, 21, 22, 30)))
        self.assertEqual(window(timer(22, 0, end=(2, 0)), day)[1], datetime(2026, 10, 22, 2, 0))
        self.assertEqual(window(timer(22, 0, end=(22, 0)), day)[1], datetime(2026, 10, 22, 22, 0))

    def run_scheduler(self, tm, t0, t1):
        starts, ends = [], []
        sch = Scheduler(lambda: [tm], starts.append, clock=lambda: t0, fire_end=ends.append)
        sch.check(t1)
        return starts, ends

    def test_end_fires_once_at_end_time(self):
        tm = timer(18, 0, end=(22, 0))
        t0 = datetime(2026, 10, 21, 21, 59, 59, 800000)
        starts, ends = self.run_scheduler(tm, t0, t0 + timedelta(seconds=0.5))
        self.assertEqual((starts, ends), ([], [tm]))

    def test_end_after_midnight_belongs_to_start_day(self):
        tm = timer(22, 0, days=[2], end=(2, 0))               # само сряда -> край четвъртък 02:00
        t0 = datetime(2026, 10, 22, 1, 59, 59, 800000)        # четвъртък
        starts, ends = self.run_scheduler(tm, t0, t0 + timedelta(seconds=0.5))
        self.assertEqual(ends, [tm])
        t0 = datetime(2026, 10, 23, 1, 59, 59, 800000)        # петък - сряда не е вчера
        self.assertEqual(self.run_scheduler(tm, t0, t0 + timedelta(seconds=0.5))[1], [])

    def test_no_end_when_disabled(self):
        tm = timer(18, 0)
        t0 = datetime(2026, 10, 21, 18, 0, 0) - timedelta(seconds=0.2)
        starts, ends = self.run_scheduler(tm, t0, t0 + timedelta(seconds=0.5))
        self.assertEqual((starts, ends), ([tm], []))

    def test_settings_keep_end_fields_and_old_timers_get_defaults(self):
        st = Settings(timers=[timer(18, 0, end=(22, 15, 30)), {"h": 5, "m": 0}]).clamp()
        self.assertEqual((st.timers[0]["end_on"], st.timers[0]["eh"], st.timers[0]["em"],
                          st.timers[0]["es"]), (True, 22, 15, 30))
        self.assertFalse(st.timers[1]["end_on"])
        self.assertEqual(new_timer()["end_on"], False)


class FakeReader:
    def __init__(self):
        self.level = {}
        self.released = 0
        self.error = None

    def read(self, pin):
        return self.level.get(pin, False)

    def release(self, keep=()):
        self.released += 1

    def close(self):
        pass


class InputMonitorTest(unittest.TestCase):
    def setUp(self):
        self.reader = FakeReader()
        self.events = []
        self.cfg = [True, [5, 6]]
        self.now = 0.0
        self.mon = InputMonitor(lambda: (self.cfg[0], self.cfg[1]), lambda i, e: self.events.append((i, e)),
                                reader=self.reader, debounce=0.04, clock=lambda: self.now)

    def tick(self, dt=0.01, n=1):
        for _ in range(n):
            self.now += dt
            self.mon.step()

    def test_edges_with_debounce(self):
        self.tick()                                   # инициализация
        self.reader.level[5] = True
        self.tick(n=3)                                # 30 ms < дебаунс
        self.assertEqual(self.events, [])
        self.tick(n=3)
        self.assertEqual(self.events, [(0, "pos")])
        self.reader.level[5] = False
        self.tick(n=6)
        self.assertEqual(self.events, [(0, "pos"), (0, "neg")])
        self.assertEqual(self.mon.states, [False, False])

    def test_bounce_is_ignored(self):
        self.tick()
        for _ in range(10):                           # трептене на контакта
            self.reader.level[6] = not self.reader.level.get(6, False)
            self.tick(n=2)
        self.assertEqual(self.events, [])

    def test_already_pressed_at_start_gives_no_event(self):
        self.reader.level[5] = True
        self.tick(n=10)
        self.assertEqual(self.events, [])
        self.assertEqual(self.mon.states[0], True)

    def test_disabled_releases_and_reenable_has_no_event(self):
        self.tick()
        self.cfg[0] = False
        self.tick()
        self.assertGreaterEqual(self.reader.released, 1)
        self.reader.level[5] = True
        self.tick(n=10)
        self.assertEqual(self.events, [])
        self.cfg[0] = True
        self.tick(n=10)
        self.assertEqual(self.events, [])             # започва от текущото ниво

    def test_pin_change_reinitialises(self):
        self.tick()
        self.reader.level[9] = True
        self.cfg[1] = [9, 6]
        self.tick(n=10)
        self.assertEqual(self.events, [])


class SettingsTest(unittest.TestCase):
    def test_defaults_and_roundtrip(self):
        st = Settings()
        self.assertEqual(len(st.inputs), 8)
        st.timers = [new_timer()]
        st.inputs[0]["pos"] = {"cmd": "Play", "param": ""}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            st.save(p)
            back = Settings.load(p)
        self.assertEqual(back.timers, st.timers)
        self.assertEqual(back.inputs[0]["pos"]["cmd"], "Play")

    def test_garbage_is_sanitised(self):
        st = Settings(timers=[{"h": 99, "m": -3, "days": [9, 1, 1, "x"]}, "bad"] + [new_timer()] * 20,
                      inputs=[{"pin": 14, "pos": {"cmd": "Hack"}}, 7]).clamp()
        self.assertEqual(len(st.timers), 8)
        self.assertEqual((st.timers[0]["h"], st.timers[0]["m"], st.timers[0]["days"]), (23, 0, [1]))
        self.assertEqual(st.inputs[0]["pin"], 5)                  # 14 (UART) не е позволен
        self.assertEqual(st.inputs[0]["pos"]["cmd"], "NoAction")
        self.assertEqual(len(st.inputs), 8)

    def test_old_daily_autostart_migrates(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            json.dump({"start_enabled": True, "start_h": 7, "start_m": 30, "start_s": 5}, open(p, "w"))
            st = Settings.load(p)
        self.assertEqual(len(st.timers), 1)
        self.assertEqual((st.timers[0]["h"], st.timers[0]["m"], st.timers[0]["s"]), (7, 30, 5))
        self.assertEqual(st.timers[0]["days"], list(range(7)))
        self.assertFalse(st.start_enabled)


class DropLogTest(unittest.TestCase):
    def test_log_drop_writes_line(self):
        import player as pm
        with tempfile.TemporaryDirectory() as d:
            old, pm.DROP_LOG = pm.DROP_LOG, os.path.join(d, "drops.log")
            try:
                pm.log_drop(120, 2, 83.4)
                line = open(pm.DROP_LOG, encoding="utf-8").read()
            finally:
                pm.DROP_LOG = old
        self.assertIn("кадър=120", line)
        self.assertIn("пропуснати=2", line)
        self.assertIn("закъснение=83ms", line)

    def test_worker_logs_when_it_drops(self):
        import player as pm
        with tempfile.TemporaryDirectory() as d:
            old, pm.DROP_LOG = pm.DROP_LOG, os.path.join(d, "drops.log")
            wds = os.path.join(d, "s.wds")
            make_wds(wds, 100)

            class SlowOut(NullDMXOutput):
                n = 0

                def send(self, ch):
                    SlowOut.n += 1
                    if SlowOut.n == 5:
                        time.sleep(0.2)      # забавяне над 4 кадъра
                    super().send(ch)

            pl = DMXPlayer(SlowOut())
            pl.start()
            try:
                pl.load(wds)
                time.sleep(0.2)
                pl.play()
                time.sleep(1.2)
                dropped = pl.snapshot().dropped_frames
                logged = os.path.exists(pm.DROP_LOG)
            finally:
                pl.shutdown()
                pm.DROP_LOG = old
        self.assertGreater(dropped, 0)
        self.assertTrue(logged)


class FakeSerialModule:
    """Заместител на pyserial: пази времената на BREAK/запис/flush."""
    EIGHTBITS, PARITY_NONE, STOPBITS_TWO = 8, "N", 2

    class SerialException(Exception):
        pass

    events = []

    class Serial:
        def __init__(self, *a, **k):
            self.is_open = True
            self.out_waiting = 0
            self._brk = False

        @property
        def break_condition(self):
            return self._brk

        @break_condition.setter
        def break_condition(self, v):
            if v:
                FakeSerialModule.events.append(("break", time.perf_counter()))
            self._brk = v

        def write(self, data):
            FakeSerialModule.events.append(("write", time.perf_counter()))

        def flush(self):
            FakeSerialModule.events.append(("flush", time.perf_counter()))

        def close(self):
            self.is_open = False


class DMXOutputTimingTest(unittest.TestCase):
    def test_send_does_not_block_and_break_waits_for_previous_packet(self):
        import dmx_engine
        old = dmx_engine.serial
        dmx_engine.serial = FakeSerialModule
        FakeSerialModule.events = []
        try:
            out = dmx_engine.DMXOutput("/dev/fake")
            out.open()
            t = time.perf_counter()
            out.send(bytes(512))
            first = time.perf_counter() - t
            out.send(bytes(512))                       # веднага след първия
            out.close()
        finally:
            dmx_engine.serial = old
        self.assertLess(first, 0.005)                  # записът не чака 22.6 ms (без tcdrain)
        ev = FakeSerialModule.events
        writes = [e[1] for e in ev if e[0] == "write"]
        breaks = [e[1] for e in ev if e[0] == "break"]
        self.assertEqual(len(writes), 2)
        # вторият BREAK не започва преди първият пакет да е излязъл (513 байта * 44 us)
        self.assertGreaterEqual(breaks[1] - writes[0], 513 * 11 / 250_000)
        self.assertNotIn("flush", [e[0] for e in ev])  # out_waiting = 0 -> flush не е нужен


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = os.path.join(self.tmp.name, "a.wds")
        self.b = os.path.join(self.tmp.name, "b.wds")
        make_wds(self.a, 100)       # 4 s
        make_wds(self.b, 100, name=b"B")
        self.audio = NullAudio()
        self.player = DMXPlayer(NullDMXOutput(), audio=self.audio)
        self.player.start()
        self.st = Settings()
        self.st.save = lambda *a, **k: None
        self.ctl = Controller(self.player, self.st)

    def tearDown(self):
        self.player.shutdown()
        self.tmp.cleanup()

    def wait_for(self, cond, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            s = self.player.snapshot()
            if cond(s):
                return s
            time.sleep(0.01)
        self.fail(f"timeout, snapshot={self.player.snapshot()}")

    def test_play_show_loads_and_plays(self):
        self.ctl.execute("PlayShow", self.b)
        s = self.wait_for(lambda s: s.state is State.PLAYING and s.info is not None)
        self.assertEqual(s.info.path, self.b)
        self.assertEqual(self.st.last_file, self.b)

    def test_transport_commands(self):
        self.player.load(self.a)
        self.wait_for(lambda s: s.info is not None)
        self.ctl.execute("Play")
        self.wait_for(lambda s: s.state is State.PLAYING)
        self.ctl.execute("TogglePlay")
        self.wait_for(lambda s: s.state is State.PAUSED)
        self.ctl.execute("TogglePlay")
        self.wait_for(lambda s: s.state is State.PLAYING)
        self.ctl.execute("Pause")
        self.wait_for(lambda s: s.state is State.PAUSED)
        self.ctl.execute("Stop")
        self.wait_for(lambda s: s.state is State.IDLE)

    def test_volume_commands(self):
        self.ctl.execute("VolumeDown")
        self.ctl.execute("VolumeDown")
        self.assertEqual(self.st.volume, 90)
        self.st.volume = 98
        self.ctl.execute("VolumeUp")
        self.assertEqual(self.st.volume, 100)
        self.assertEqual([c for c in self.audio.calls if c[0] == "volume"][-1], ("volume", 100))

    def test_input_maps_to_action(self):
        self.st.inputs[2]["pos"] = {"cmd": "PlayShow", "param": self.a}
        self.st.inputs[2]["neg"] = {"cmd": "Stop", "param": ""}
        self.ctl.on_input(2, "pos")
        self.wait_for(lambda s: s.state is State.PLAYING)
        self.ctl.on_input(2, "neg")
        self.wait_for(lambda s: s.state is State.IDLE)
        self.ctl.on_input(3, "pos")                 # NoAction - нищо
        self.assertEqual(self.ctl.last_event[1:4], ("input", 2, "neg"))

    def test_timer_end_stops_show(self):
        self.player.load(self.a)
        self.wait_for(lambda s: s.info is not None)
        self.ctl.on_timer(timer(0, 0))
        self.wait_for(lambda s: s.state is State.PLAYING)
        self.ctl.on_timer_end(timer(0, 0, end=(1, 0)))
        self.wait_for(lambda s: s.state is State.IDLE)
        self.assertEqual(self.ctl.last_event[1], "timer_end")

    def test_timer_restarts_current_show_and_switches_show(self):
        self.player.load(self.a)
        self.wait_for(lambda s: s.info is not None)
        self.ctl.on_timer(timer(0, 0))
        self.wait_for(lambda s: s.state is State.PLAYING)
        time.sleep(0.4)
        before = self.player.snapshot().position
        self.ctl.on_timer(timer(0, 0))              # рестарт отначало
        s = self.wait_for(lambda s: s.state is State.PLAYING and s.position < before)
        self.assertLess(s.position, before)
        self.ctl.on_timer(timer(0, 0, show=self.b))
        s = self.wait_for(lambda s: s.state is State.PLAYING and s.info and s.info.path == self.b)
        self.assertEqual(s.info.path, self.b)


if __name__ == "__main__":
    unittest.main()


class TestScheduleFile(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.wds = os.path.join(self.d, "Test.wds")
        open(self.wds, "wb").write(b"x")

    def _s(self):
        from settings import Settings
        s = Settings()
        return s

    def _tm(self, show, h=16):
        from settings import new_timer
        tm = new_timer(); tm.update(h=h, m=10, show=show); return tm

    def test_roundtrip(self):
        import schedule_file as sf
        s = self._s(); s.timers = [self._tm(self.wds), self._tm("")]
        self.assertTrue(sf.sync_show(s, self.wds))
        self.assertTrue(os.path.isfile(self.wds + ".schedule"))
        got = sf.read_sidecar(self.wds)
        self.assertEqual(len(got), 1); self.assertEqual((got[0]["h"], got[0]["m"]), (16, 10))
        s2 = self._s(); self.assertTrue(sf.import_schedule(s2, self.wds))
        self.assertEqual(s2.timers[0]["show"], self.wds)

    def test_import_replaces_not_duplicates(self):
        import schedule_file as sf
        s = self._s(); s.timers = [self._tm(self.wds)]
        sf.sync_show(s, self.wds)
        sf.import_schedule(s, self.wds); sf.import_schedule(s, self.wds)
        self.assertEqual(len(s.timers), 1)

    def test_import_all_only_when_missing(self):
        import schedule_file as sf
        s = self._s(); s.timers = [self._tm(self.wds)]
        sf.sync_show(s, self.wds)
        s2 = self._s(); self.assertEqual(sf.import_all(s2, [self.d]), 1)
        self.assertEqual(sf.import_all(s2, [self.d]), 0)
        self.assertEqual(len(s2.timers), 1)

    def test_removed_when_empty(self):
        import schedule_file as sf
        s = self._s(); s.timers = [self._tm(self.wds)]
        sf.sync_show(s, self.wds); s.timers = []
        sf.sync_show(s, self.wds)
        self.assertFalse(os.path.exists(self.wds + ".schedule"))

    def test_corrupt_and_missing(self):
        import schedule_file as sf
        self.assertIsNone(sf.read_sidecar(self.wds))
        open(self.wds + ".schedule", "w").write("{bad")
        self.assertIsNone(sf.read_sidecar(self.wds))
        s = self._s(); self.assertFalse(sf.import_schedule(s, self.wds))

    def test_readonly_dir(self):
        import schedule_file as sf
        s = self._s(); s.timers = [self._tm(self.wds)]
        os.chmod(self.d, 0o555)
        try:
            if os.access(self.d, os.W_OK):
                self.skipTest("root")
            self.assertFalse(sf.sync_show(s, self.wds))
        finally:
            os.chmod(self.d, 0o755)


class TestPower(unittest.TestCase):
    def test_fallback_chain(self):
        import power, subprocess
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:
                raise OSError("no systemctl")
            return subprocess.CompletedProcess(cmd, 1 if len(calls) == 2 else 0)
        self.assertTrue(power.run("poweroff", runner))
        self.assertEqual(calls[2][-3:], ["shutdown", "-h", "now"])

    def test_all_fail(self):
        import power, subprocess
        self.assertFalse(power.run("reboot", lambda c, **k: subprocess.CompletedProcess(c, 1)))


class TestDataDir(unittest.TestCase):
    def test_data_dir_redirects_config(self):
        import tempfile, importlib
        import i18n, main, settings as sm
        old = (sm.CONFIG_FILE, i18n.CONFIG_FILE)
        d = tempfile.mkdtemp()
        try:
            shows = main.use_data_dir(d)
            self.assertEqual(shows, os.path.join(d, "shows"))
            st = sm.Settings(volume=42); st.save()
            self.assertTrue(os.path.isfile(os.path.join(d, "config", "settings.json")))
            self.assertEqual(sm.Settings.load().volume, 42)
            self.assertFalse(os.path.exists(os.path.join(d, "config", "settings.json.tmp")))
        finally:
            sm.CONFIG_FILE, i18n.CONFIG_FILE = old


class TestScheduleArrivesOff(unittest.TestCase):
    def test_new_schedule_is_disabled_until_user_enables(self):
        import tempfile, schedule_file as sf
        from settings import Settings, new_timer
        d = tempfile.mkdtemp(); wds = os.path.join(d, "A.wds")
        with open(wds, "wb") as f: f.write(b"x")
        s = Settings(); tm = new_timer(); tm.update(show=wds, on=True); s.timers = [tm]
        sf.sync_show(s, wds)
        s2 = Settings()
        self.assertEqual(sf.import_all(s2, [d]), 1)
        self.assertFalse(s2.timers[0]["on"])
        s2.timers[0]["on"] = True
        sf.sync_show(s2, wds)
        sf.import_schedule(s2, wds)          # вече има график за шоуто -> състоянието от файла
        self.assertTrue(s2.timers[0]["on"])


class TestTimePlaner(unittest.TestCase):
    SAMPLE = os.path.join(os.path.dirname(__file__), "TimePlaner_sample.xml")

    def setUp(self):
        import tempfile
        from datetime import datetime
        self.dt = datetime
        self.d = tempfile.mkdtemp()
        import shutil
        shutil.copy(self.SAMPLE, os.path.join(self.d, "TimePlaner.xml"))
        for n in ("Test_MUSIC", "Test_2", "Test_3"):
            with open(os.path.join(self.d, n + ".wds"), "wb") as f:
                f.write(b"x")
        self.played, self.stops = [], []

    def _runner(self, **kw):
        import timeplaner as tp
        return tp.PlanRunner([self.d], lambda p, c: self.played.append((os.path.basename(p), c)),
                             lambda: self.stops.append(1), **kw)

    def test_parse_and_resolution(self):
        import timeplaner as tp
        from datetime import date
        p = tp.parse(os.path.join(self.d, "TimePlaner.xml"))
        ev = tp.day_events(p, date(2026, 10, 23))
        self.assertEqual((ev[0].name, ev[0].counts, ev[0].kind), ("Test_3", 0, tp.PLAY))
        self.assertEqual(ev[-1].kind, tp.STOP)
        self.assertEqual(tp.day_events(p, date(2026, 3, 12))[0].name, "Test MUSIC")   # MUSIC WEEK
        self.assertEqual(tp.day_events(p, date(2026, 2, 1)), [])                     # преди първия запис

    def test_find_show_fuzzy(self):
        import timeplaner as tp
        self.assertTrue(tp.find_show("Test MUSIC", [self.d]).endswith("Test_MUSIC.wds"))
        self.assertIsNone(tp.find_show("Nope", [self.d]))

    def test_fires_events_in_time(self):
        r = self._runner(catchup=False)
        r._last = self.dt(2026, 10, 23, 7, 34, 59)
        r.check(self.dt(2026, 10, 23, 7, 35, 0))
        self.assertEqual(self.played, [("Test_MUSIC.wds", 1)])
        r.check(self.dt(2026, 10, 23, 7, 35, 1))
        self.assertEqual(len(self.played), 1)                          # не се повтаря

    def test_end_all_stops(self):
        r = self._runner(catchup=False)
        r._last = self.dt(2026, 10, 23, 23, 58, 59)
        r.check(self.dt(2026, 10, 23, 23, 59, 0))
        self.assertEqual(self.stops, [1])

    def test_clock_jump_ignored(self):
        r = self._runner(catchup=False)
        r._last = self.dt(2026, 10, 23, 6, 0, 0)
        r.check(self.dt(2026, 10, 23, 8, 0, 0))
        self.assertEqual(self.played, [])

    def test_startup_catchup(self):
        r = self._runner()
        r.check(self.dt(2026, 10, 23, 8, 0, 0), first=True)   # Test_3 от 07:43 е безкрайно
        self.assertEqual(self.played, [("Test_3.wds", 0)])

    def test_startup_no_catchup_when_finished(self):
        r = self._runner()
        r.check(self.dt(2026, 10, 23, 7, 40, 0), first=True)  # Test MUSIC (63 s) от 07:35 е свършило, но Test_3...
        # последното събитие до 07:40 е Test MUSIC 07:35, 63 s -> свършило
        self.assertEqual(self.played, [])

    def test_disabled_and_missing_show(self):
        r = self._runner(catchup=False, enabled=lambda: False)
        r._last = self.dt(2026, 10, 23, 7, 34, 59)
        r.check(self.dt(2026, 10, 23, 7, 35, 0))
        self.assertEqual(self.played, [])
        os.unlink(os.path.join(self.d, "Test_MUSIC.wds"))
        r2 = self._runner(catchup=False)
        r2._last = self.dt(2026, 10, 23, 7, 34, 59)
        r2.check(self.dt(2026, 10, 23, 7, 35, 0))
        self.assertEqual(r2.missing, {"Test MUSIC"})

    def test_corrupt_file(self):
        with open(os.path.join(self.d, "TimePlaner.xml"), "w") as f:
            f.write("<broken")
        r = self._runner()
        r.check(self.dt(2026, 10, 23, 8, 0, 0), first=True)
        self.assertIsNotNone(r.error)
        self.assertEqual(self.played, [])

    def test_controller_plan_methods(self):
        from controller import Controller
        from settings import Settings

        class P:
            def __init__(s): s.calls = []
            def set_loops(s, n): s.calls.append(("loops", n))
            def load(s, path, audio=None): s.calls.append(("load", os.path.basename(path)))
            def play(s): s.calls.append(("play",))
            def stop(s): s.calls.append(("stop",))
        p = P(); c = Controller(p, Settings(loops=3))
        c.on_plan_play(os.path.join(self.d, "Test_2.wds"), 0)
        c.on_plan_stop()
        self.assertEqual(p.calls, [("loops", 0), ("load", "Test_2.wds"), ("play",), ("stop",), ("loops", 3)])


class TestAgendaCount(unittest.TestCase):
    def test_count_shows_per_day(self):
        import timeplaner as tp
        from datetime import date
        p = tp.parse(os.path.join(os.path.dirname(__file__), "TimePlaner_sample.xml"))
        self.assertEqual(tp.count_shows(p, date(2026, 10, 23)), 7)   # "new": 7 шоута + "end all"
        self.assertEqual(tp.count_shows(p, date(2026, 3, 12)), 6)    # "MUSIC DAY"
        self.assertEqual(tp.count_shows(p, date(2026, 2, 1)), 0)


class TestDatedTimer(unittest.TestCase):
    def _tm(self, **kw):
        from settings import new_timer
        tm = new_timer(); tm.update(h=12, m=0, s=0, **kw); return tm

    def test_fires_only_on_its_date_not_next_week(self):
        from datetime import datetime
        from scheduler import Scheduler
        fired = []
        tm = self._tm(date="2026-10-23")
        s = Scheduler(lambda: [tm], lambda t: fired.append(1))
        s._last = datetime(2026, 10, 23, 11, 59, 59)
        s.check(datetime(2026, 10, 23, 12, 0, 0))
        self.assertEqual(len(fired), 1)
        s._last = datetime(2026, 10, 30, 11, 59, 59)          # същият ден от седмицата, седмица по-късно
        s.check(datetime(2026, 10, 30, 12, 0, 0))
        self.assertEqual(len(fired), 1)

    def test_next_fire_dated(self):
        from datetime import datetime
        from scheduler import next_fire
        tm = self._tm(date="2026-12-24")
        nf = next_fire([tm], datetime(2026, 10, 23, 8, 0, 0))
        self.assertEqual(nf[0], datetime(2026, 12, 24, 12, 0, 0))
        self.assertIsNone(next_fire([tm], datetime(2026, 12, 25, 8, 0, 0)))   # изтекъл

    def test_clean_timer_date(self):
        from settings import clean_timer
        self.assertEqual(clean_timer({"date": "2026-10-23"})["date"], "2026-10-23")
        self.assertEqual(clean_timer({"date": "23.10.2026"})["date"], "")
        self.assertEqual(clean_timer({"date": "2026-02-30"})["date"], "")

    def test_planner_dayplan_is_single_day(self):
        import timeplaner as tp
        from datetime import date
        p = tp.parse(os.path.join(os.path.dirname(__file__), "TimePlaner_oneday.xml"))
        self.assertEqual(len(tp.day_events(p, date(2026, 10, 23))), 1)
        self.assertEqual(tp.day_events(p, date(2026, 10, 24)), [])
        self.assertEqual(tp.day_events(p, date(2026, 10, 30)), [])


class TestDmxSettings(unittest.TestCase):
    def test_settings_clamp(self):
        from settings import Settings
        s = Settings(dmx_fps=999, dmx_channels=3, pause_mode="x", stop_mode="y", boot_delay=-5).clamp()
        self.assertEqual((s.dmx_fps, s.dmx_channels, s.pause_mode, s.stop_mode, s.boot_delay),
                         (44, 24, "hold", "blackout", 0))

    def test_channels_shorten_packet(self):
        import dmx_engine as de
        out = de.NullDMXOutput(simulate_timing=False)
        out.set_channels(100)
        self.assertEqual(out.channels, 100)
        out.set_channels(5)
        self.assertEqual(out.channels, 24)
        self.assertEqual(len(de._normalize(bytes(512), 24)), 24)

    def test_apply_settings_to_player(self):
        from controller import apply_settings
        from settings import Settings

        class P:
            def __init__(s): s.c = {}
            def __getattr__(s, n):
                return lambda *a: s.c.__setitem__(n, a)
        p = P()
        apply_settings(p, Settings(dmx_fps=30, dmx_channels=64, pause_mode="blackout", stop_mode="off"))
        self.assertEqual(p.c["set_fps"], (30,))
        self.assertEqual(p.c["set_channels"], (64,))
        self.assertEqual(p.c["set_pause_mode"], ("blackout",))
        self.assertEqual(p.c["set_stop_mode"], ("off",))

    def test_boot_play_only_when_idle(self):
        import tempfile
        from controller import Controller
        from player import State
        from settings import Settings
        d = tempfile.mkdtemp(); show = os.path.join(d, "A.wds")
        with open(show, "wb") as f: f.write(b"x")

        class Snap: pass

        class P:
            def __init__(s, state): s.state, s.calls = state, []
            def snapshot(s):
                x = Snap(); x.state = s.state; return x
            def load(s, path, audio=None): s.calls.append("load")
            def play(s): s.calls.append("play")
        idle, busy = P(State.IDLE), P(State.PLAYING)
        self.assertTrue(Controller(idle, Settings(boot_show=show)).boot_play())
        self.assertEqual(idle.calls, ["load", "play"])
        self.assertFalse(Controller(busy, Settings(boot_show=show)).boot_play())
        self.assertFalse(Controller(P(State.IDLE), Settings(boot_show="/nope.wds")).boot_play())


class TestPauseStopModes(unittest.TestCase):
    """Поведение на DMX при пауза и стоп (запис на изпратените кадри)."""

    def _player(self, **modes):
        import tempfile
        from dmx_engine import NullDMXOutput
        from player import DMXPlayer
        from test_player import make_wds

        class Rec(NullDMXOutput):
            def __init__(s):
                super().__init__(simulate_timing=False); s.sent = []
            def send(s, ch):
                s.sent.append(bytes(ch)); super().send(ch)
        self.out = Rec()
        p = DMXPlayer(self.out, fps=50)
        d = tempfile.mkdtemp(); path = os.path.join(d, "S.wds")
        make_wds(path, 100)                      # 4 s, канал 1 расте
        if "pause" in modes: p.set_pause_mode(modes["pause"])
        if "stop" in modes: p.set_stop_mode(modes["stop"])
        p.start(); p.load(path); time.sleep(0.2); p.play(); time.sleep(0.5)
        self.p = p
        return p

    def tearDown(self):
        if hasattr(self, "p"):
            self.p._cmd.put(("quit",))
            self.p._thread.join(2)

    def _tail_after(self, action, wait=0.4):
        action()
        time.sleep(0.15)
        n = len(self.out.sent)
        time.sleep(wait)
        return self.out.sent[n:]

    def test_pause_hold_repeats_last_frame(self):
        p = self._player(pause="hold")
        tail = self._tail_after(p.pause)
        self.assertTrue(len(tail) >= 5 and any(tail[0]) and all(f == tail[0] for f in tail))

    def test_pause_blackout_sends_zeros(self):
        p = self._player(pause="blackout")
        tail = self._tail_after(p.pause)
        self.assertTrue(len(tail) >= 5 and not any(any(f) for f in tail))

    def test_pause_off_sends_nothing(self):
        p = self._player(pause="off")
        self.assertEqual(self._tail_after(p.pause), [])

    def test_stop_blackout_then_silent(self):
        p = self._player(stop="blackout")
        tail = self._tail_after(p.stop)
        self.assertTrue(len(tail) <= 1 and not any(any(f) for f in tail))

    def test_stop_hold_keeps_last_frame(self):
        p = self._player(stop="hold")
        tail = self._tail_after(p.stop)
        self.assertTrue(len(tail) >= 5 and any(tail[0]) and all(f == tail[0] for f in tail))

    def test_stop_off_sends_nothing(self):
        p = self._player(stop="off")
        self.assertEqual(self._tail_after(p.stop), [])


class TestTimerEndLoops(unittest.TestCase):
    def test_end_time_means_endless_until_end(self):
        from controller import Controller
        from settings import Settings, new_timer

        class P:
            def __init__(s): s.loops = 1; s.log = []
            def set_loops(s, n): s.loops = n; s.log.append(("loops", n))
            def stop(s): s.log.append("stop")
            def play(s): s.log.append("play")
            def load(s, *a): s.log.append("load")
        p, st = P(), Settings()
        c = Controller(p, st)
        tm = new_timer(); tm["end_on"] = True
        c.on_timer(tm)
        self.assertEqual(p.loops, 0)
        c.on_timer_end(tm)
        self.assertEqual(p.loops, st.loops)
        tm2 = new_timer()
        p.loops = 1
        c.on_timer(tm2)
        self.assertEqual(p.loops, 1)
