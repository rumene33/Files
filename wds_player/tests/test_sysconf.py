import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sysconf  # noqa: E402


def cp(out="", code=0, err=""):
    return subprocess.CompletedProcess([], code, out, err)


class Fake:
    """runner(cmd, ...) -> отговор по първата дума на командата; запомня командите."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, cmd, **kw):
        cmd = [c for c in cmd if c != "--no-ask-password"]    # флагът се слага само на директния опит
        self.calls.append(cmd)
        key = " ".join(cmd[2:4] if cmd[0] == "sudo" else cmd[:2])
        r = self.replies.get(key, cp())
        return r(cmd) if callable(r) else r


class SysconfTest(unittest.TestCase):
    def test_run_falls_back_to_sudo(self):
        f = Fake({"timedatectl set-ntp": lambda c: cp(code=1, err="Access denied") if c[0] != "sudo" else cp("ok")})
        self.assertEqual(sysconf.run(["timedatectl", "set-ntp", "true"], f), (True, "ok"))
        self.assertEqual(f.calls[1][:2], ["sudo", "-n"])
        bad = Fake({"timedatectl set-ntp": cp(code=1, err="no")})
        self.assertEqual(sysconf.run(["timedatectl", "set-ntp", "true"], bad), (False, "no"))

    def test_time_status_and_timezone(self):
        f = Fake({"timedatectl show": cp("Timezone=Europe/Sofia\nNTP=yes\nNTPSynchronized=no\n")})
        self.assertEqual(sysconf.time_status(f), {"timezone": "Europe/Sofia", "ntp": True, "synced": False})
        self.assertFalse(sysconf.set_timezone("../../etc/passwd", f)[0])
        self.assertFalse(sysconf.set_timezone("Europe/Sofia; rm -rf /", f)[0])
        self.assertTrue(sysconf.set_timezone("Europe/Sofia", f)[0])

    def test_set_time_disables_ntp_first(self):
        f = Fake({})
        sysconf.set_time(datetime(2026, 10, 23, 12, 5, 9), f)
        self.assertEqual(f.calls[0], ["timedatectl", "set-ntp", "false"])
        self.assertEqual(f.calls[1], ["timedatectl", "set-time", "2026-10-23 12:05:09"])

    def test_split_t_escapes(self):
        self.assertEqual(sysconf.split_t(r"a\:b:c::d"), ["a:b", "c", "", "d"])

    def test_net_devices_and_info(self):
        f = Fake({
            "nmcli -t": lambda c: cp("eth0:ethernet:connected:Wired connection 1\nwlan0:wifi:disconnected:--\n"
                                     "lo:loopback:unmanaged:--\n") if "device" == c[-1]
            else cp("GENERAL.CONNECTION:Wired connection 1\nIP4.ADDRESS[1]:192.168.1.203/24\n"
                    "IP4.GATEWAY:192.168.1.1\nIP4.DNS[1]:8.8.8.8\nIP4.DNS[2]:1.1.1.1\n"),
            "nmcli -g": cp("manual\n"),
        })
        devs = sysconf.net_devices(f)
        self.assertEqual([d["dev"] for d in devs], ["eth0", "wlan0"])
        info = sysconf.net_info("eth0", f)
        self.assertEqual((info["ip"], info["prefix"], info["gw"], info["dns"], info["method"]),
                         ("192.168.1.203", "24", "192.168.1.1", "8.8.8.8,1.1.1.1", "manual"))

    def test_set_ip_validation_and_commands(self):
        f = Fake({})
        self.assertFalse(sysconf.set_ip("c", "manual", "999.1.1.1", 24, "", "", f)[0])
        self.assertFalse(sysconf.set_ip("c", "manual", "10.0.0.5", 33, "", "", f)[0])
        self.assertFalse(sysconf.set_ip("c", "manual", "10.0.0.5", 24, "x", "", f)[0])
        self.assertFalse(sysconf.set_ip("c", "manual", "10.0.0.5", 24, "10.0.0.1", "bad", f)[0])
        self.assertEqual(f.calls, [])
        self.assertTrue(sysconf.set_ip("Wired", "manual", "10.0.0.5", 24, "10.0.0.1", "8.8.8.8", f)[0])
        self.assertIn("10.0.0.5/24", f.calls[0])
        self.assertEqual(f.calls[1][:3], ["nmcli", "connection", "up"])
        f2 = Fake({})
        sysconf.set_ip("Wired", "auto", runner=f2)
        self.assertIn("auto", f2.calls[0])

    def test_wifi_scan_dedup_sort(self):
        out = (" :Home:40:WPA2\n*:Home:70:WPA2\n :Cafe:80:\n :Weak:10:WPA2\n :::WPA2\n")
        nets = sysconf.wifi_scan(Fake({"nmcli -t": cp(out)}))
        self.assertEqual([n["ssid"] for n in nets], ["Home", "Cafe", "Weak"])
        self.assertTrue(nets[0]["active"] and nets[0]["signal"] == 70)
        self.assertFalse(nets[1]["secure"])

    def test_wifi_connect_command(self):
        f = Fake({})
        sysconf.wifi_connect("Home", "pw", f)
        self.assertEqual(f.calls[0], ["nmcli", "device", "wifi", "connect", "Home", "password", "pw"])

    def test_read_only_root(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "m")
        open(p, "w").write("overlay / overlay rw 0 0\n")
        self.assertTrue(sysconf.read_only_root(p))
        open(p, "w").write("/dev/mmcblk0p2 / ext4 rw,noatime 0 0\n")
        self.assertFalse(sysconf.read_only_root(p))
        open(p, "w").write("/dev/mmcblk0p2 / ext4 ro,noatime 0 0\n")
        self.assertTrue(sysconf.read_only_root(p))


if __name__ == "__main__":
    unittest.main()


class ApplySavedTest(unittest.TestCase):
    def test_reapplies_only_when_different(self):
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)
            if cmd[:2] == ["timedatectl", "show"]:
                return cp("Timezone=UTC\nNTP=yes\nNTPSynchronized=yes\n")
            if cmd[:3] == ["nmcli", "-t", "-f"] and cmd[-3:-1] == ["device", "show"]:
                return cp("GENERAL.CONNECTION:Wired\nIP4.ADDRESS[1]:192.168.1.50/24\n")
            if cmd[:3] == ["nmcli", "-g", "ipv4.method"]:
                return cp("auto")
            return cp()
        saved = {"timezone": "Europe/Sofia",
                 "net": {"eth0": {"method": "manual", "ip": "192.168.1.203", "prefix": "24", "gw": "192.168.1.1", "dns": ""}}}
        done = sysconf.apply_saved(saved, runner)
        self.assertEqual(done, ["timezone", "eth0"])
        n = len(calls)
        # същият IP -> без промяна
        saved["net"]["eth0"]["ip"] = "192.168.1.50"
        saved["timezone"] = "UTC"
        self.assertEqual(sysconf.apply_saved(saved, runner), [])


class WifiSavedTest(unittest.TestCase):
    def _runner(self, state, calls):
        def runner(cmd, **kw):
            calls.append(cmd)
            if cmd[:5] == ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]:
                return cp(f"wlan0:wifi:{state}:Home\n")
            return cp()
        return runner

    def test_reconnects_when_offline(self):
        calls = []
        done = sysconf.apply_saved({"wifi": {"ssid": "Home", "password": "secret12"}},
                                   self._runner("disconnected", calls))
        self.assertEqual(done, ["wifi"])
        self.assertIn(["nmcli", "device", "wifi", "connect", "Home", "password", "secret12"], calls)

    def test_skips_when_already_connected(self):
        calls = []
        self.assertEqual(sysconf.apply_saved({"wifi": {"ssid": "Home", "password": "x"}},
                                             self._runner("connected", calls)), [])
        self.assertFalse(any(c[:4] == ["nmcli", "device", "wifi", "connect"] for c in calls))


class TzInProcessTest(unittest.TestCase):
    def test_timezone_change_applies_to_running_process(self):
        import os, time
        from datetime import datetime
        old = os.environ.get("TZ")
        try:
            sysconf.use_in_process("UTC")
            a = datetime.now()
            sysconf.use_in_process("Asia/Tokyo")
            b = datetime.now()
            diff = round((b - a).total_seconds() / 3600)
            self.assertEqual(diff, 9)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()


class NoAskPasswordTest(unittest.TestCase):
    def test_direct_attempt_never_waits_for_polkit(self):
        seen = []

        def runner(cmd, **kw):
            seen.append(cmd)
            return cp(code=1, err="Access denied")
        sysconf.run(["timedatectl", "set-timezone", "UTC"], runner)
        self.assertEqual(seen[0], ["timedatectl", "--no-ask-password", "set-timezone", "UTC"])
        self.assertEqual(seen[1], ["sudo", "-n", "timedatectl", "set-timezone", "UTC"])


class UtcOffsetTest(unittest.TestCase):
    def test_offsets_with_dst(self):
        from datetime import timezone
        winter = datetime(2026, 1, 15, tzinfo=timezone.utc)
        summer = datetime(2026, 7, 15, tzinfo=timezone.utc)
        self.assertEqual(sysconf.utc_offset("Europe/Sofia", winter), "UTC+02:00")
        self.assertEqual(sysconf.utc_offset("Europe/Sofia", summer), "UTC+03:00")
        self.assertEqual(sysconf.utc_offset("America/New_York", winter), "UTC-05:00")
        self.assertEqual(sysconf.utc_offset("Asia/Kathmandu", winter), "UTC+05:45")
        self.assertEqual(sysconf.utc_offset("UTC", winter), "UTC+00:00")
        self.assertEqual(sysconf.utc_offset("Няма/Такава"), "")
