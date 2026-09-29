#!/usr/bin/env bash
set -euo pipefail
APP="$HOME/bike-safety-computer"
cd "$APP"
if [[ ! -x "$HOME/pyenv/bin/python" ]]; then
    python3 -m venv "$HOME/pyenv"
fi
"$HOME/pyenv/bin/python" -m pip install -r requirements.txt
# Remove source modules replaced by ble_sensors.py and ant_sensors.py.
rm -f "$APP/bike_telemetry.py" "$APP/ant_telemetry.py" "$APP/lights.py" \
      "$APP/sram.py" "$APP/sram_bond.py" "$APP/sram_batteries.py" "$APP/sram_records.py"
if command -v udevadm >/dev/null && id -nG | grep -qw plugdev; then
    sudo -n install -m 0644 "$APP/42-ant-usb-sticks.rules" /etc/udev/rules.d/42-ant-usb-sticks.rules
    sudo -n install -m 0644 "$APP/blacklist-ant-serial.conf" /etc/modprobe.d/blacklist-ant-serial.conf
    sudo -n udevadm control --reload-rules
    sudo -n udevadm trigger --subsystem-match=usb --attr-match=idVendor=0fcf --action=add
    sudo -n modprobe -r usb_serial_simple
fi
# Retire the old single-sensor collector; preserve historical recordings.
if [[ -f "$HOME/.config/systemd/user/bike-heart-rate.service" ]]; then
    systemctl --user disable --now bike-heart-rate.service
    rm -f "$HOME/.config/systemd/user/bike-heart-rate.service"
fi
rm -f "$APP/heart_rate.py"
rm -f "$APP/web.html"
mkdir -p data "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/bike-telemetry.service" <<'UNIT'
[Unit]
Description=Bike Flask web dashboard and BLE/ANT+ telemetry

[Service]
Type=simple
WorkingDirectory=%h/bike-safety-computer
ExecStart=%h/pyenv/bin/python -u %h/bike-safety-computer/web_server.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
UMask=0077

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
echo "Installed in $APP. Terminal: ~/pyenv/bin/python $APP/dashboard.py; background: systemctl --user start bike-telemetry"
