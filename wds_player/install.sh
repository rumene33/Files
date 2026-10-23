#!/bin/bash
# Инсталация на WDS DMX Player върху Raspberry Pi OS Lite (Bookworm/Trixie, 32/64-bit).
#
#   sudo ./install.sh              # пакети + сериен порт + права
#   sudo ./install.sh --autostart  # + автоматично стартиране на дисплея при включване
#   sudo ./install.sh --data-usb   # + настройки и шоута на USB флашка (/mnt/data), не на SD картата
#   sudo ./install.sh --data-usb=/dev/sda1   # същото, с избран дял (ако няма само един)
#   sudo ./install.sh --readonly   # + система само за четене (overlay): безопасно при спиране на тока
#
# Опциите се комбинират. Препоръчано за устройство, което се изключва с щепсела:
#   sudo ./install.sh --autostart --data-usb --readonly
# Флашката НЕ се форматира - трябва да има файлова система (FAT32/exFAT/ext4), напр. от Windows.
#
# След това: sudo reboot
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Пуснете със sudo: sudo $0 $*" >&2
    exit 1
fi

AUTOSTART=0; DATA_USB=0; DATA_DEV=""; READONLY=0
for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        --data-usb) DATA_USB=1 ;;
        --data-usb=*) DATA_USB=1; DATA_DEV="${arg#*=}" ;;
        --readonly) READONLY=1 ;;
        *) echo "Непозната опция: $arg" >&2; exit 1 ;;
    esac
done

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SUDO_USER:-pi}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
BOOT=/boot/firmware
[ -f "$BOOT/config.txt" ] || BOOT=/boot
CONFIG="$BOOT/config.txt"
CMDLINE="$BOOT/cmdline.txt"

echo "==> Пакети"
apt-get update
apt-get install -y --no-install-recommends \
    python3-serial python3-tk python3-gpiozero mpv \
    xserver-xorg xserver-xorg-input-libinput xinit x11-xserver-utils

echo "==> Права без парола за бутона ⏻ и системните настройки на плейъра (изключване, час, часова зона, мрежа)"
echo "$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot, /usr/sbin/shutdown -h now, /usr/sbin/shutdown -r now, /usr/bin/timedatectl set-time *, /usr/bin/timedatectl set-timezone *, /usr/bin/timedatectl set-ntp *, /usr/bin/nmcli *" > /etc/sudoers.d/wds-player
chmod 440 /etc/sudoers.d/wds-player
visudo -cf /etc/sudoers.d/wds-player >/dev/null || rm -f /etc/sudoers.d/wds-player

echo "==> Реално-времеви приоритет за DMX нишката (по-малко пропуснати кадри; важи след нов вход/рестарт)"
echo "@audio - rtprio 50" > /etc/security/limits.d/wds-player.conf

echo "==> Сериен порт: PL011 (ttyAMA0) за DMX, без конзола и Bluetooth"
cp -n "$CONFIG" "$CONFIG.bak-wds" || true
cp -n "$CMDLINE" "$CMDLINE.bak-wds" || true
grep -q '^enable_uart=1' "$CONFIG" || echo 'enable_uart=1' >> "$CONFIG"
grep -q '^dtoverlay=disable-bt' "$CONFIG" || echo 'dtoverlay=disable-bt' >> "$CONFIG"
sed -i -E 's/console=(serial0|ttyAMA0|ttyS0),[0-9]+ ?//g' "$CMDLINE"
systemctl disable --now hciuart 2>/dev/null || true
systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true
systemctl disable --now serial-getty@ttyS0.service 2>/dev/null || true

echo "==> Права на $APP_USER (сериен порт, дисплей, тъч)"
usermod -aG dialout,video,input,render,tty,audio "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_HOME/shows"
chmod +x "$APP_DIR/kiosk/xinitrc"

if [ "$DATA_USB" = 1 ]; then
    echo "==> Данни на USB флашка (/mnt/data)"
    MNT=/mnt/data
    if [ -z "$DATA_DEV" ]; then
        # дяловете на USB устройства с файлова система (без системната SD карта)
        mapfile -t CAND < <(lsblk -rpno NAME,TYPE,FSTYPE | awk '$2=="part" && NF>=3 {print $1}' |
            while read -r p; do
                disk="/dev/$(lsblk -no PKNAME "$p" | head -1)"
                [ "$(lsblk -dno TRAN "$disk" 2>/dev/null)" = "usb" ] && echo "$p"
            done)
        if [ "${#CAND[@]}" -ne 1 ]; then
            echo "Намерени USB дялове: ${#CAND[@]}. Посочете: --data-usb=/dev/sdXN" >&2
            lsblk -o NAME,SIZE,FSTYPE,LABEL,TRAN >&2
            exit 1
        fi
        DATA_DEV="${CAND[0]}"
    fi
    [ -b "$DATA_DEV" ] || { echo "Няма такова устройство: $DATA_DEV" >&2; exit 1; }
    UUID="$(blkid -o value -s UUID "$DATA_DEV")"
    FSTYPE="$(blkid -o value -s TYPE "$DATA_DEV")"
    [ -n "$UUID" ] && [ -n "$FSTYPE" ] || { echo "$DATA_DEV няма файлова система (не се форматира автоматично)" >&2; exit 1; }
    APP_UID="$(id -u "$APP_USER")"; APP_GID="$(id -g "$APP_USER")"
    case "$FSTYPE" in
        vfat)         OPTS="noatime,nofail,x-systemd.device-timeout=5,flush,uid=$APP_UID,gid=$APP_GID,umask=0022" ;;
        exfat|ntfs3)  OPTS="noatime,nofail,x-systemd.device-timeout=5,uid=$APP_UID,gid=$APP_GID,umask=0022" ;;
        ext4|ext3|ext2) OPTS="noatime,nofail,x-systemd.device-timeout=5" ;;
        *) echo "Неподдържана файлова система: $FSTYPE (ползвайте FAT32, exFAT или ext4)" >&2; exit 1 ;;
    esac
    mkdir -p "$MNT"
    cp -n /etc/fstab /etc/fstab.bak-wds || true
    sed -i '\|[[:space:]]/mnt/data[[:space:]]|d' /etc/fstab
    echo "UUID=$UUID $MNT $FSTYPE $OPTS 0 0" >> /etc/fstab
    systemctl daemon-reload
    mountpoint -q "$MNT" || mount "$MNT"
    install -d -o "$APP_USER" -g "$APP_USER" "$MNT/wds_player" "$MNT/wds_player/shows" "$MNT/wds_player/config"
    # съществуващите шоута и настройки се копират веднъж (без да се презаписва нищо)
    cp -n "$APP_HOME"/shows/*.wds "$MNT/wds_player/shows/" 2>/dev/null || true
    cp -n "$APP_HOME"/shows/*.schedule "$MNT/wds_player/shows/" 2>/dev/null || true
    cp -n "$APP_HOME"/.config/wds_player/* "$MNT/wds_player/config/" 2>/dev/null || true
    printf 'WDS_MOUNT=%s\nWDS_DATA_DIR=%s\n' "$MNT" "$MNT/wds_player" > /etc/default/wds-player
    echo "    $DATA_DEV ($FSTYPE) -> $MNT ; шоута: $MNT/wds_player/shows"
fi

if [ "$AUTOSTART" = 1 ]; then
    echo "==> Автоматичен вход в конзолата и стартиране на плейъра на tty1"
    raspi-config nonint do_boot_behaviour B2
    PROFILE="$APP_HOME/.bash_profile"
    MARK="# wds-player autostart"
    touch "$PROFILE"
    if ! grep -q "$MARK" "$PROFILE"; then
        cat >> "$PROFILE" <<PROF

$MARK
if [ -z "\$DISPLAY" ] && [ "\$(tty)" = "/dev/tty1" ]; then
    exec startx "$APP_DIR/kiosk/xinitrc" -- -nocursor
fi
PROF
        chown "$APP_USER:$APP_USER" "$PROFILE"
    fi
fi

if [ "$READONLY" = 1 ]; then
    echo "==> Система само за четене (overlay) - след рестарт SD картата не се пише"
    if [ ! -f /etc/default/wds-player ]; then
        echo "ВНИМАНИЕ: без --data-usb настройките и графиците няма да се запазват след рестарт." >&2
    fi
    raspi-config nonint do_overlayfs 0
    raspi-config nonint do_bootro 0
    echo "    За промени по системата: sudo raspi-config nonint do_overlayfs 1 ; sudo reboot (и после пак включване)"
fi

echo
echo "Готово. Рестартирайте: sudo reboot"
echo "След рестарта проверете:  ls -l /dev/serial0   (трябва да сочи към ttyAMA0)"
