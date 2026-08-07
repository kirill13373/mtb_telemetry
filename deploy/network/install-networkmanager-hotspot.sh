#!/bin/bash
set -euo pipefail

SOURCE_DIR=/home/pi/mtb_telemetry/deploy/network
CONFIG_FILE=/etc/mtb-wifi-mode.conf
HOSTAPD_CONFIG=/etc/hostapd/mtb-telemetry.conf
DNSMASQ_CONFIG=/etc/dnsmasq.d/mtb-telemetry.conf

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

if ! systemctl is-active --quiet NetworkManager; then
    echo "NetworkManager is not active. This installer makes no changes." >&2
    exit 1
fi

if ! command -v nmcli >/dev/null; then
    echo "nmcli is unavailable. This installer makes no changes." >&2
    exit 1
fi

: "${HOME_CONNECTION_NAME:?Set HOME_CONNECTION_NAME to the existing NetworkManager home profile.}"
: "${AP_PASSPHRASE:?Set AP_PASSPHRASE to a new WPA2 password (8-63 characters).}"

if (( ${#AP_PASSPHRASE} < 8 || ${#AP_PASSPHRASE} > 63 )); then
    echo "AP_PASSPHRASE must contain 8-63 characters." >&2
    exit 1
fi

if [[ "$AP_PASSPHRASE" == *$'\n'* || "$AP_PASSPHRASE" == *$'\r'* ]]; then
    echo "AP_PASSPHRASE must not contain line breaks." >&2
    exit 1
fi

if ! nmcli -g NAME connection show | grep -Fxq "$HOME_CONNECTION_NAME"; then
    echo "NetworkManager connection '$HOME_CONNECTION_NAME' does not exist. No changes made." >&2
    exit 1
fi

if systemctl is-active --quiet hostapd.service || systemctl is-active --quiet dnsmasq.service; then
    echo "hostapd.service or dnsmasq.service is already active. Resolve that existing configuration first; no changes made." >&2
    exit 1
fi

apt update
apt install -y hostapd dnsmasq
systemctl disable --now hostapd.service dnsmasq.service 2>/dev/null || true

install -Dm755 "$SOURCE_DIR/mtb-wifi-mode" /usr/local/sbin/mtb-wifi-mode
install -Dm644 "$SOURCE_DIR/mtb-wifi-mode.service" /etc/systemd/system/mtb-wifi-mode.service
install -Dm644 "$SOURCE_DIR/mtb-hostapd.service" /etc/systemd/system/mtb-hostapd.service
install -Dm644 "$SOURCE_DIR/mtb-dnsmasq.service" /etc/systemd/system/mtb-dnsmasq.service
install -Dm644 "$SOURCE_DIR/dnsmasq-mtb-telemetry.conf" "$DNSMASQ_CONFIG"
sed -i 's/\r$//' \
    /usr/local/sbin/mtb-wifi-mode \
    /etc/systemd/system/mtb-wifi-mode.service \
    /etc/systemd/system/mtb-hostapd.service \
    /etc/systemd/system/mtb-dnsmasq.service \
    "$DNSMASQ_CONFIG"
escaped_passphrase=$(printf '%s' "$AP_PASSPHRASE" | sed 's/[\\&|]/\\&/g')
sed "s|REPLACE_WITH_A_UNIQUE_PASSWORD|$escaped_passphrase|" \
    "$SOURCE_DIR/hostapd-mtb-telemetry.conf" > "$HOSTAPD_CONFIG"
sed -i 's/\r$//' "$HOSTAPD_CONFIG"
chmod 600 "$HOSTAPD_CONFIG"

cat > "$CONFIG_FILE" <<EOF
# This file is local-only. It is intentionally not kept in the Git repository.
HOME_CONNECTION_NAME='$HOME_CONNECTION_NAME'
WLAN_INTERFACE='wlan0'
HOME_CONNECT_TIMEOUT=30
EOF
chmod 600 "$CONFIG_FILE"

systemctl daemon-reload
systemctl enable mtb-wifi-mode.service
echo "Installed. Reboot to perform the first automatic mode selection."