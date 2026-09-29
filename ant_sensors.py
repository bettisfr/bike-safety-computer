"""ANT+ heart rate, bike speed/cadence, and bicycle light collection."""
import json
import logging
import threading
import time
from pathlib import Path

LOG = logging.getLogger("bike.ant")
LIGHT_BATTERY = {1: "Full", 2: "Good", 3: "OK", 4: "Low", 5: "Critical", 6: "Charging"}
LIGHT_MODES = {
    0: "Off", 1: "Steady 81–100%", 2: "Steady 61–80%",
    3: "Steady 41–60%", 4: "Steady 21–40%", 5: "Steady 0–20%",
    6: "Slow flash", 7: "Fast flash", 8: "Random flash", 9: "Auto",
}
SHIFT_BATTERY = {1: "New/Full", 2: "Good", 3: "OK", 4: "Low", 5: "Critical", 6: "Charging"}


class ANTRotation:
    """Rate from 16-bit revolution counts and 1/1024 s event timestamps."""

    def __init__(self):
        self.previous = None
        self.rate = None
        self.last_change = None
        self.started = time.monotonic()

    def update(self, count, event, now):
        if self.previous is None:
            self.previous = (count, event, now)
            return
        old_count, old_event, old_at = self.previous
        if count == old_count:
            return
        turns = (count - old_count) & 0xFFFF
        ticks = (event - old_event) & 0xFFFF
        rate = turns * 1024 / ticks if ticks else None
        self.rate = rate if now - old_at < 64 and rate is not None and rate <= 30 else None
        self.last_change = now
        self.previous = (count, event, now)

    def display_rate(self, now):
        if self.previous is None:
            return None
        if now - (self.last_change or self.started) > 5:
            return 0.0
        return self.rate


class ANTSensorCollector:
    def __init__(self, wheel_circumference=2.136):
        self.wheel_circumference = wheel_circumference
        drivetrain = json.loads(Path(__file__).with_name("drivetrain.json").read_text())
        mapping = drivetrain.get("ant_position_mapping") or {}
        self.front_teeth = {int(index): teeth for index, teeth in
                            mapping.get("front_index_to_teeth", {}).items()}
        self.rear_teeth = (list(reversed(drivetrain["cassette_teeth_smallest_to_largest"]))
                           if mapping.get("rear_index_zero_is_largest") else [])
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.node = None
        self.state = {
            "cardio": {"name": "COOSPO H808S", "status": "initializing ANT+",
                       "error": "", "rssi": None, "fields": []},
            "duo": {"name": "DuoTrap S", "status": "initializing ANT+",
                    "error": "", "rssi": None, "fields": []},
            "front": {"name": "Ion Pro RT", "status": "initializing ANT+",
                      "error": "", "rssi": None, "fields": []},
            "rear": {"name": "Flare RT", "status": "initializing ANT+",
                     "error": "", "rssi": None, "fields": []},
            "sram": {"name": "SRAM Force AXS", "status": "initializing ANT+",
                     "error": "", "rssi": None, "fields": []},
        }
        self.received_at = {key: None for key in self.state}
        self.wheel = ANTRotation()
        self.crank = ANTRotation()
        self.thread = threading.Thread(target=self._run, name="bike-ant", daemon=True)

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            result = {key: {**section,
                            "packet_age_s": now - self.received_at[key]
                            if self.received_at[key] is not None else None,
                            "fields": [
                                {"label": field["label"], "value": field["value"],
                                 "age_s": now - field["updated"],
                                 "changed": now - field["changed_at"] < 2}
                                for field in section["fields"]]}
                      for key, section in self.state.items()}
            fresh = self.received_at["duo"] is not None and now - self.received_at["duo"] < 10
            wheel = self.wheel.display_rate(now) if fresh else None
            crank = self.crank.display_rate(now) if fresh else None
            result["duo"]["speed_kmh"] = wheel * self.wheel_circumference * 3.6 if wheel is not None else None
            result["duo"]["cadence_rpm"] = crank * 60 if crank is not None else None
            return result

    def _set_status(self, key, status, error=""):
        with self.lock:
            self.state[key]["status"] = status
            self.state[key]["error"] = error

    def _record_locked(self, key, values, now):
        section = self.state[key]
        fields = {field["label"]: field for field in section["fields"]}
        for label, value in values.items():
            value = str(value)
            old = fields.get(label)
            fields[label] = {"label": label, "value": value,
                             "changed_at": now if old is None or old["value"] != value
                             else old["changed_at"], "updated": now}
        section["fields"] = list(fields.values())
        section["status"], section["error"] = "connected", ""
        self.received_at[key] = now

    def _record(self, key, values):
        now = time.monotonic()
        with self.lock:
            self._record_locked(key, values, now)

    def _run(self):
        try:
            from openant.devices import ANTPLUS_NETWORK_KEY
            from openant.devices.common import DeviceType
            from openant.devices.scanner import Scanner
            from openant.easy.node import Node
        except Exception as exc:
            LOG.exception("ANT+ package unavailable")
            for key in self.state:
                self._set_status(key, "ANT+ error", f"{type(exc).__name__}: {exc}")
            return

        while not self.stop_event.is_set():
            node = None
            try:
                for key in self.state:
                    self._set_status(key, "searching ANT+…")
                node = Node()
                self.node = node
                node.set_network_key(0, ANTPLUS_NETWORK_KEY)
                cardio = Scanner(node, device_type=DeviceType.HeartRate.value, period=8070)
                duo = Scanner(node, device_type=DeviceType.BikeSpeedCadence.value, period=8086)
                lights = Scanner(node, device_type=35, period=4084)
                shifting = Scanner(node, device_type=34, period=8192)
                selected = {"cardio": None, "duo": None}
                shifting_ids = set()

                def cardio_packet(data):
                    cardio._on_data(data)
                    if len(data) < 13 or not cardio.found:
                        return
                    device_id = data[9] | data[10] << 8
                    if selected["cardio"] is None:
                        selected["cardio"] = device_id
                    if device_id != selected["cardio"] or (data[0] & 0x0F) > 7:
                        return
                    values = {"ANT+ ID": device_id, "Heart rate": f"{data[7]} bpm",
                              "Beat count": data[6],
                              "Event time": f"{int.from_bytes(data[4:6], 'little') / 1024:.3f} s"}
                    if data[0] & 0x0F == 7 and data[1] <= 100:
                        values["Battery"] = f"{data[1]} %"
                    self._record("cardio", values)

                def duo_packet(data):
                    if len(data) < 13 or data[11] != DeviceType.BikeSpeedCadence.value:
                        return
                    device_id = data[9] | data[10] << 8
                    if selected["duo"] is None:
                        selected["duo"] = device_id
                    if device_id != selected["duo"]:
                        return
                    crank_time = int.from_bytes(data[0:2], "little")
                    crank_count = int.from_bytes(data[2:4], "little")
                    wheel_time = int.from_bytes(data[4:6], "little")
                    wheel_count = int.from_bytes(data[6:8], "little")
                    now = time.monotonic()
                    with self.lock:
                        self.crank.update(crank_count, crank_time, now)
                        self.wheel.update(wheel_count, wheel_time, now)
                        self._record_locked("duo", {
                            "ANT+ ID": device_id,
                            "Wheel · cumulative revolutions": wheel_count,
                            "Wheel · event time": f"{wheel_time} /1024 s (modulo 64 s)",
                            "Crank · cumulative revolutions": crank_count,
                            "Crank · event time": f"{crank_time} /1024 s (modulo 64 s)",
                        }, now)

                def light_packet(data):
                    # Bike Lights profile, data page 1 (Light States 1).
                    if len(data) < 13 or data[11] != 35 or data[0] != 1:
                        return
                    light_type = (data[2] >> 2) & 7
                    key = {0: "front", 2: "rear"}.get(light_type)
                    if key is None:
                        return
                    device_id = data[9] | data[10] << 8
                    if selected.get(key) is None:
                        selected[key] = device_id
                    if device_id != selected[key]:
                        return
                    battery_code = (data[2] >> 5) & 7
                    mode_code = (data[6] >> 2) & 63
                    values = {
                        "ANT+ ID": device_id,
                        "Battery status": LIGHT_BATTERY.get(battery_code, "Unavailable"),
                        "Mode": LIGHT_MODES.get(
                            mode_code,
                            f"Custom mode {mode_code}" if mode_code >= 48
                            else f"Reserved mode {mode_code}"),
                        "Mode code": mode_code,
                    }
                    if data[7] <= 100:
                        values["Intensity"] = f"{data[7]} %"
                    self._record(key, values)

                def shifting_packet(data):
                    if len(data) < 13 or data[11] != 34:
                        return
                    device_id = data[9] | data[10] << 8
                    shifting_ids.add(device_id)
                    values = {"ANT+ IDs": ", ".join(map(str, sorted(shifting_ids)))}
                    if data[0] == 1:
                        rear = data[3] & 0x1F
                        front = data[3] >> 5
                        rear_teeth = (self.rear_teeth[rear]
                                      if rear < len(self.rear_teeth) else None)
                        front_teeth = self.front_teeth.get(front)
                        values.update({
                            "Gear": (f"{front_teeth}×{rear_teeth}"
                                     if front_teeth is not None and rear_teeth is not None
                                     else "unavailable"),
                            "Rear gear index": rear if rear != 31 else "unavailable",
                            "Front gear index": front if front != 7 else "unavailable",
                            "Rear gear count": data[4] & 0x1F,
                            "Front gear count": data[4] >> 5,
                            "Shift event counter": data[1],
                        })
                    elif data[0] == 82:
                        battery_id = data[2] >> 4 if data[2] != 0xFF else None
                        component = {
                            0: "System", 1: "Front derailleur", 2: "Rear derailleur",
                            3: "Left shifter", 4: "Right shifter",
                        }.get(battery_id, f"component {battery_id}")
                        voltage = (data[7] & 0x0F) + data[6] / 256
                        status = (data[7] >> 4) & 7
                        values[f"Battery · {component}"] = (
                            f"{voltage:.2f} V · {SHIFT_BATTERY.get(status, 'Unknown')}")
                    else:
                        return
                    self._record("sram", values)

                cardio.channel.on_broadcast_data = cardio_packet
                duo.channel.on_broadcast_data = duo_packet
                lights.channel.on_broadcast_data = light_packet
                shifting.channel.on_broadcast_data = shifting_packet
                self._set_status("cardio", "listening on ANT+ · wear the chest strap")
                self._set_status("duo", "listening on ANT+ · spin the wheel and crank")
                self._set_status("front", "listening on ANT+ · turn on the light")
                self._set_status("rear", "listening on ANT+ · turn on the light")
                self._set_status("sram", "listening on ANT+ · press a shift button")
                node.start()
            except Exception as exc:
                if not self.stop_event.is_set():
                    LOG.exception("ANT+ collector stopped")
                    for key in self.state:
                        self._set_status(key, "ANT+ error · retrying", f"{type(exc).__name__}: {exc}")
            finally:
                self.node = None
                try:
                    if node is not None:
                        node.stop()
                except Exception:
                    LOG.exception("Error stopping ANT+ node")
            self.stop_event.wait(5)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.node is not None:
            try:
                self.node.stop()
            except Exception:
                LOG.exception("Error closing ANT+ USB stick")
        self.thread.join(timeout=10)
