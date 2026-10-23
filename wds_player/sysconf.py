"""Системни настройки на Raspberry Pi: мрежа (NetworkManager/nmcli), дата, час и часова зона
(timedatectl). Всички команди минават през `run()`, за да може да се тестват без Pi.

Права: първо се опитва директно (polkit разрешава на локалния потребител на tty1), после `sudo -n`
(install.sh слага правило в /etc/sudoers.d/wds-player).
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
from datetime import datetime


def run(cmd: list, runner=subprocess.run, timeout: float = 25, use_sudo: bool = True) -> tuple:
    """-> (успех, изход|грешка)"""
    direct = cmd
    if cmd and cmd[0] == "timedatectl" and len(cmd) > 1 and cmd[1].startswith("set-"):      # без това polkit чака парола до изтичане на времето -> замръзва
        direct = [cmd[0], "--no-ask-password"] + cmd[1:]
    attempts = [direct] + ([["sudo", "-n"] + cmd] if use_sudo else [])
    last = ""
    for c in attempts:
        try:
            r = runner(c, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            last = str(e)
            continue
        if r.returncode == 0:
            return True, (r.stdout or "").strip()
        last = ((r.stderr or r.stdout or "").strip()) or f"код {r.returncode}"
    return False, last


def read_only_root(mounts_path: str = "/proc/mounts") -> bool:
    """Системата е само за четене (overlay/ro): системните промени се губят след рестарт."""
    try:
        with open(mounts_path, encoding="utf-8") as f:
            for line in f:
                p = line.split()
                if len(p) >= 4 and p[1] == "/":
                    return p[0] == "overlay" or "ro" in p[3].split(",")
    except OSError:
        pass
    return False


# ---------------- дата, час, часова зона ----------------
def time_status(runner=subprocess.run) -> dict:
    ok, out = run(["timedatectl", "show", "-p", "Timezone", "-p", "NTP", "-p", "NTPSynchronized"],
                  runner, use_sudo=False)
    info = {"timezone": "", "ntp": False, "synced": False}
    if ok:
        for line in out.splitlines():
            k, _, v = line.partition("=")
            if k == "Timezone":
                info["timezone"] = v
            elif k == "NTP":
                info["ntp"] = v == "yes"
            elif k == "NTPSynchronized":
                info["synced"] = v == "yes"
    return info


def list_timezones(runner=subprocess.run) -> list:
    ok, out = run(["timedatectl", "list-timezones"], runner, use_sudo=False)
    return [z for z in out.splitlines() if z] if ok else []


def utc_offset(tz: str, when=None) -> str:
    """Отместване спрямо Гринуич (UTC/GMT) в момента, напр. "UTC+03:00" (с лятното часово време).
    "" ако зоната е непозната."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        off = (when or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo(tz)).utcoffset()
    except Exception:          # няма zoneinfo/tzdata или непозната зона
        return ""
    mins = int(off.total_seconds()) // 60
    sign = "+" if mins >= 0 else "-"
    return f"UTC{sign}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


_TZ_RE = re.compile(r"^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}$")


def set_timezone(tz: str, runner=subprocess.run) -> tuple:
    if not _TZ_RE.match(tz or ""):
        return False, "невалидна часова зона"
    ok, msg = run(["timedatectl", "set-timezone", tz], runner)
    if ok:
        use_in_process(tz)
    return ok, msg


def use_in_process(tz: str) -> None:
    """Работещият процес продължава със старата часова зона, ако не се опресни: графиците и
    часовникът на плейъра щяха да са с часове разлика след смяна на зоната от менюто."""
    import os
    import time
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()


def set_ntp(on: bool, runner=subprocess.run) -> tuple:
    return run(["timedatectl", "set-ntp", "true" if on else "false"], runner)


def set_time(dt: datetime, runner=subprocess.run) -> tuple:
    """Ръчен час: първо се изключва автоматичното синхронизиране (иначе timedatectl отказва)."""
    run(["timedatectl", "set-ntp", "false"], runner)
    return run(["timedatectl", "set-time", dt.strftime("%Y-%m-%d %H:%M:%S")], runner)


# ---------------- мрежа ----------------
def valid_ip(s: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(s.strip()), ipaddress.IPv4Address)
    except ValueError:
        return False


def valid_prefix(p) -> bool:
    try:
        return 1 <= int(p) <= 32
    except (TypeError, ValueError):
        return False


def split_t(line: str) -> list:
    """Разделя ред от `nmcli -t` по ':' (екранираните '\\:' остават в полето)."""
    parts, cur, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
        elif line[i] == ":":
            parts.append(cur)
            cur = ""
            i += 1
        else:
            cur += line[i]
            i += 1
    parts.append(cur)
    return parts


def net_devices(runner=subprocess.run) -> list:
    """[{dev, type, state, conn}] само за ethernet и wifi."""
    ok, out = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], runner, use_sudo=False)
    devs = []
    if ok:
        for line in out.splitlines():
            f = split_t(line)
            if len(f) >= 4 and f[1] in ("ethernet", "wifi"):
                devs.append({"dev": f[0], "type": f[1], "state": f[2], "conn": f[3]})
    return devs


def net_info(dev: str, runner=subprocess.run) -> dict:
    """Текущ адрес (от устройството) и метод/настройки (от връзката)."""
    info = {"ip": "", "prefix": "24", "gw": "", "dns": "", "method": "auto", "conn": ""}
    ok, out = run(["nmcli", "-t", "-f", "GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS",
                   "device", "show", dev], runner, use_sudo=False)
    if not ok:
        return info
    dns = []
    for line in out.splitlines():
        key, _, val = line.partition(":")
        key = re.sub(r"\[\d+\]$", "", key)
        if key == "GENERAL.CONNECTION":
            info["conn"] = val
        elif key == "IP4.ADDRESS" and not info["ip"] and "/" in val:
            info["ip"], info["prefix"] = val.split("/", 1)
        elif key == "IP4.GATEWAY":
            info["gw"] = val
        elif key == "IP4.DNS" and val:
            dns.append(val)
    info["dns"] = ",".join(dns)
    if info["conn"] and info["conn"] != "--":
        ok, out = run(["nmcli", "-g", "ipv4.method", "connection", "show", info["conn"]], runner,
                      use_sudo=False)
        if ok and out.strip() in ("auto", "manual"):
            info["method"] = out.strip()
    return info


def set_ip(conn: str, method: str, ip: str = "", prefix="24", gw: str = "", dns: str = "",
           runner=subprocess.run) -> tuple:
    """Статичен адрес (manual) или DHCP (auto) за връзката; после я рестартира."""
    if not conn:
        return False, "няма активна връзка"
    if method == "manual":
        if not valid_ip(ip) or not valid_prefix(prefix) or (gw and not valid_ip(gw)):
            return False, "невалиден IP адрес, маска или шлюз"
        servers = [d.strip() for d in dns.replace(";", ",").split(",") if d.strip()]
        if any(not valid_ip(d) for d in servers):
            return False, "невалиден DNS"
        args = ["ipv4.method", "manual", "ipv4.addresses", f"{ip.strip()}/{int(prefix)}",
                "ipv4.gateway", gw.strip(), "ipv4.dns", ",".join(servers)]
    else:
        args = ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""]
    ok, msg = run(["nmcli", "connection", "modify", conn] + args, runner)
    if not ok:
        return False, msg
    return run(["nmcli", "connection", "up", conn], runner, timeout=40)


def wifi_scan(runner=subprocess.run) -> list:
    """[{ssid, signal, secure, active}] без дубликати, най-силните първи."""
    run(["nmcli", "device", "wifi", "rescan"], runner, use_sudo=False)
    ok, out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
                  runner, use_sudo=False)
    best = {}
    if ok:
        for line in out.splitlines():
            f = split_t(line)
            if len(f) < 4 or not f[1]:
                continue
            try:
                sig = int(f[2])
            except ValueError:
                sig = 0
            cur = best.get(f[1])
            net = {"ssid": f[1], "signal": sig, "secure": bool(f[3].strip()), "active": f[0] == "*"}
            if cur is None or net["signal"] > cur["signal"] or net["active"]:
                if cur and cur["active"]:
                    net["active"] = True
                best[f[1]] = net
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))


def wifi_connect(ssid: str, password: str = "", runner=subprocess.run) -> tuple:
    if not ssid:
        return False, "няма мрежа"
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    return run(cmd, runner, timeout=60)


# ---------------- възстановяване при старт (система само за четене) ----------------
def apply_saved(system: dict, runner=subprocess.run) -> list:
    """Връща записаните часова зона и статичен IP, ако системата е различна (след рестарт на
    система с overlay промените в /etc се губят). -> списък от направените промени."""
    done = []
    tz = (system or {}).get("timezone") or ""
    if tz and time_status(runner)["timezone"] != tz and set_timezone(tz, runner)[0]:
        done.append("timezone")
    for dev, cfg in ((system or {}).get("net") or {}).items():
        if not isinstance(cfg, dict) or cfg.get("method") != "manual":
            continue
        info = net_info(dev, runner)
        if info["conn"] and info["conn"] != "--" and info["ip"] != cfg.get("ip"):
            if set_ip(info["conn"], "manual", cfg.get("ip", ""), cfg.get("prefix", "24"),
                      cfg.get("gw", ""), cfg.get("dns", ""), runner)[0]:
                done.append(dev)
    wf = (system or {}).get("wifi") or {}
    if isinstance(wf, dict) and wf.get("ssid"):
        online = any(d["type"] == "wifi" and d["state"] == "connected" and d["conn"] == wf["ssid"]
                     for d in net_devices(runner))
        if not online and wifi_connect(wf["ssid"], wf.get("password", ""), runner)[0]:
            done.append("wifi")
    return done
