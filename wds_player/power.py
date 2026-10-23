"""Изключване / рестарт на Raspberry Pi от плейъра (замества `sudo shutdown -h now`).

Опитва се по ред: systemctl (logind/polkit - работи за локалния потребител на tty1),
после `sudo -n` (install.sh слага правило без парола), после shutdown.
"""

from __future__ import annotations

import subprocess

COMMANDS = {
    "poweroff": [["systemctl", "poweroff"], ["sudo", "-n", "systemctl", "poweroff"],
                 ["sudo", "-n", "shutdown", "-h", "now"]],
    "reboot":   [["systemctl", "reboot"], ["sudo", "-n", "systemctl", "reboot"],
                 ["sudo", "-n", "shutdown", "-r", "now"]],
}


def run(action: str, runner=subprocess.run) -> bool:
    """Изпълнява действието; True ако някоя от командите успее."""
    for cmd in COMMANDS[action]:
        try:
            if runner(cmd, timeout=15, capture_output=True).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False
