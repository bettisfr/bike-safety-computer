#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
HOST=${RPI_HOST:-rpi5-02.local}
ACTION=${1:-help}
if (($#)); then shift; fi
SERVICE=bike-telemetry.service
case "$ACTION" in
  deploy)
    ssh "$HOST" 'mkdir -p "$HOME/bike-safety-computer/templates" "$HOME/bike-safety-computer/static"'
    rsync -a --itemize-changes -- \
      "$ROOT/web_server.py" "$ROOT/dashboard.py" \
      "$ROOT/ble_sensors.py" "$ROOT/ant_sensors.py" "$ROOT/README.md" \
      "$ROOT/drivetrain.json" "$ROOT/requirements.txt" \
      "$ROOT/scripts/install-rpi.sh" "$ROOT/scripts/42-ant-usb-sticks.rules" \
      "$ROOT/scripts/blacklist-ant-serial.conf" "$HOST:bike-safety-computer/"
    rsync -a --itemize-changes -- "$ROOT/templates/" "$HOST:bike-safety-computer/templates/"
    rsync -a --itemize-changes -- "$ROOT/static/" "$HOST:bike-safety-computer/static/"
    ssh "$HOST" 'bash "$HOME/bike-safety-computer/install-rpi.sh"'
    ;;
  start|stop|restart|status)
    ssh "$HOST" "systemctl --user $ACTION $SERVICE"
    ;;
  enable)
    ssh "$HOST" 'sudo -n loginctl enable-linger "$(id -un)" && systemctl --user enable --now bike-telemetry.service'
    ;;
  disable)
    ssh "$HOST" "systemctl --user disable --now $SERVICE"
    ;;
  logs)
    ssh "$HOST" "journalctl _SYSTEMD_USER_UNIT=$SERVICE -n 30 -f"
    ;;
  web)
    REMOTE=""
    if (($#)); then printf -v REMOTE '%q ' "$@"; fi
    ssh -t "$HOST" "exec \"\$HOME/pyenv/bin/python\" \"\$HOME/bike-safety-computer/web_server.py\" $REMOTE"
    ;;
  dashboard|run)
    REMOTE=""
    if (($#)); then printf -v REMOTE '%q ' "$@"; fi
    ssh -t "$HOST" "exec \"\$HOME/pyenv/bin/python\" \"\$HOME/bike-safety-computer/dashboard.py\" $REMOTE"
    ;;
  lights)
    REMOTE=""
    if (($#)); then printf -v REMOTE '%q ' "$@"; else REMOTE=status; fi
    ssh "$HOST" "exec \"\$HOME/pyenv/bin/python\" \"\$HOME/bike-safety-computer/ble_sensors.py\" $ACTION $REMOTE"
    ;;
  fetch)
    mkdir -p "$ROOT/data/rpi"
    scp -r "$HOST:bike-safety-computer/data/." "$ROOT/data/rpi/"
    ;;
  *)
    echo 'Usage: scripts/rpi.sh {deploy|web|dashboard [--raw]|run|start|stop|restart|status|logs|enable|disable|fetch|lights [status|on|off|flash] [--light front|rear|both]}'
    echo 'Dashboard: scripts/rpi.sh dashboard [--raw] [--wheel-circumference 2.136]'
    echo 'Host override: RPI_HOST=user@hostname scripts/rpi.sh deploy'
    [[ "$ACTION" == help ]]
    ;;
esac
