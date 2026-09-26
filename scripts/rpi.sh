#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
HOST=${RPI_HOST:-rpi5-00.local}
ACTION=${1:-help}
if (($#)); then shift; fi
SERVICE=bike-telemetry.service
case "$ACTION" in
  deploy)
    ssh "$HOST" 'mkdir -p "$HOME/bike-safety-computer"'
    scp "$ROOT/web_server.py" "$ROOT/web.html" "$ROOT/dashboard.py" "$ROOT/bike_telemetry.py" "$ROOT/sram_records.py" "$ROOT/drivetrain.json" "$ROOT/lights.py" "$ROOT/sram.py" "$ROOT/sram_bond.py" "$ROOT/sram_batteries.py" "$ROOT/requirements.txt" "$ROOT/scripts/install-rpi.sh" "$HOST:bike-safety-computer/"
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
  lights|sram|sram_bond|sram_batteries)
    REMOTE=""
    if (($#)); then printf -v REMOTE '%q ' "$@"; elif [[ "$ACTION" == lights ]]; then REMOTE=status; elif [[ "$ACTION" == sram ]]; then REMOTE=scan; else REMOTE=--help; fi
    ssh "$HOST" "exec \"\$HOME/pyenv/bin/python\" \"\$HOME/bike-safety-computer/$ACTION.py\" $REMOTE"
    ;;
  fetch)
    mkdir -p "$ROOT/data/rpi"
    scp -r "$HOST:bike-safety-computer/data/." "$ROOT/data/rpi/"
    ;;
  *)
    echo 'Usage: scripts/rpi.sh {deploy|web|dashboard [--raw]|run|start|stop|restart|status|logs|enable|disable|fetch|lights [status|on|off|flash] [--light front|rear|both]}'
    echo 'Dashboard: scripts/rpi.sh dashboard [--raw] [--wheel-circumference 2.136]'
    echo 'Host override: RPI_HOST=user@hostname scripts/rpi.sh deploy'
    echo 'SRAM read-only: scripts/rpi.sh sram {scan|probe} [--address MAC] [--seconds 20]'
    [[ "$ACTION" == help ]]
    ;;
esac
