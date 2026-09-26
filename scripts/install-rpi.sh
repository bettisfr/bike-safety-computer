#!/usr/bin/env bash
set -euo pipefail
APP="$HOME/bike-safety-computer"
cd "$APP"
if [[ ! -x "$HOME/pyenv/bin/python" ]]; then
    python3 -m venv "$HOME/pyenv"
fi
"$HOME/pyenv/bin/python" -m pip install -r requirements.txt
# Retire the old single-sensor collector; preserve historical recordings.
if [[ -f "$HOME/.config/systemd/user/bike-heart-rate.service" ]]; then
    systemctl --user disable --now bike-heart-rate.service
    rm -f "$HOME/.config/systemd/user/bike-heart-rate.service"
fi
rm -f "$APP/heart_rate.py"
mkdir -p data "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/bike-telemetry.service" <<'UNIT'
[Unit]
Description=Bike Flask web dashboard and BLE telemetry

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
