"""Shared configuration for the connected bike devices."""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
DEVICES = json.loads(CONFIG_PATH.read_text())["devices"]
WHEEL_CIRCUMFERENCE_M = DEVICES["speedcadence"]["wheel_circumference_m"]
