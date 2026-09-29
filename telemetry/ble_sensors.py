# SPDX-License-Identifier: MPL-2.0
"""BLE sensor collection and light maintenance commands for this bike."""
import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

from bleak import BleakClient, BleakScanner
from .config import DEVICES, WHEEL_CIRCUMFERENCE_M

LOG = logging.getLogger("bike.telemetry")

MODE = "71261001-3692-ae93-e711-472ba41689c9"
LIGHTS = {"front": DEVICES["frontlight"]["name"],
          "rear": DEVICES["rearlight"]["name"]}

BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"
CSC = "00002a5b-0000-1000-8000-00805f9b34fb"
BASE = "-90aa-4c7c-b036-1e01fb8eb7ee"
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

@dataclass
class TelemetryConfig:
    wheel_circumference: float = WHEEL_CIRCUMFERENCE_M
    poll_interval: float = 10
    sram_interval: float = 0.5
    raw: bool = False
    log: Path | None = None

def decode_hr(data):
    """Decode flags, 8/16-bit bpm, optional energy and RR intervals."""
    if not data:
        raise ValueError("Empty measurement")
    flags = data[0]
    offset = 1

    def take(size):
        nonlocal offset
        if offset + size > len(data):
            raise ValueError("Truncated measurement")
        value = int.from_bytes(data[offset:offset + size], "little")
        offset += size
        return value

    result = {"bpm": take(2 if flags & 1 else 1),
              "contact": bool(flags & 2) if flags & 4 else None}
    if flags & 8:
        result["energy_kj"] = take(2)
    result["rr_ms"] = []
    if flags & 16:
        while offset < len(data):
            result["rr_ms"].append(take(2) * 1000 / 1024)
    return result



class Section:
    def __init__(self, name, address):
        self.name, self.address = name, address
        self.status = "waiting"
        self.error = ""
        self.rssi = None
        self.seen = None
        self.fields = {}
        self.changed = {}

    def put(self, key, value):
        value = str(value)
        if key not in self.fields or self.fields[key][0] != value:
            self.changed[key] = time.monotonic()
        self.fields[key] = (value, time.monotonic())

    def visible_fields(self):
        """Omit absent measurements from UIs; keep complete acquisition logs."""
        missing = ("not transmitted", "unavailable", "unsupported",
                   "description unavailable")
        return {key: item for key, item in self.fields.items()
                if not item[0].strip().lower().startswith(missing)}


class Rotation:
    def __init__(self, bits):
        self.modulus = 1 << bits
        self.previous = None
        self.rate = None
        self.last_change = None
        self.started = time.monotonic()
        self.count = None
        self.event = None
        self.reset = False

    def update(self, count, event):
        now = time.monotonic()
        self.count, self.event = count, event
        if self.previous is None:
            self.previous = (count, event, now)
            return
        old_count, old_event, old_time = self.previous
        if count == old_count:
            return
        turns = (count - old_count) % self.modulus
        ticks = (event - old_event) % 65536
        # The event clock wraps every 64 s; do not infer a rate across a gap.
        elapsed = now - old_time
        rate = turns * 1024 / ticks if ticks else None
        self.reset = elapsed >= 64 or rate is None or rate > 30
        self.rate = None if self.reset else rate
        self.last_change = now
        self.previous = (count, event, now)

    def display_rate(self):
        if self.previous is None:
            return None
        # No wheel/crank pulse is an inactivity indication, not an exact stop sensor.
        if time.monotonic() - (self.last_change or self.started) > 5:
            return 0.0
        return self.rate


def decode_csc(data):
    if not data:
        raise ValueError("Empty CSC packet")
    offset, result = 1, {}
    for name, flag, size in (("wheel", 1, 4), ("crank", 2, 2)):
        if data[0] & flag:
            if len(data) < offset + size + 2:
                raise ValueError("Incomplete CSC packet")
            result[name] = (int.from_bytes(data[offset:offset + size], "little"),
                            int.from_bytes(data[offset + size:offset + size + 2], "little"))
            offset += size + 2
    return result


class BikeTelemetry:
    def __init__(self, args=None, on_event=None):
        args = args or TelemetryConfig()
        self.on_event = on_event
        self.args = args
        self.sections = {key: Section(device["name"], device["ble"]["address"].upper())
                         for key, device in DEVICES.items()}
        self.devices = {}
        self.light_modes = {}
        self.light_descriptors = set()
        self.stop = asyncio.Event()
        self.connect_lock = asyncio.Lock()
        self.banner = ""
        self.wheel = Rotation(32)
        self.crank = Rotation(16)
        self.duo_packet_at = None
        self.offset = 0
        self.log = None
        self.log_error = None

    def advertisement(self, device, adv):
        for key, section in self.sections.items():
            if device.address.upper() == section.address:
                self.devices[key] = device
                section.rssi, section.seen = adv.rssi, time.monotonic()

    def record(self, key, values, data=None, raw=None):
        section = self.sections[key]
        for label, value in values.items():
            section.put(label, value)
        event = {"timestamp": datetime.now(timezone.utc).isoformat(),
                 "monotonic_s": time.monotonic(), "device": key,
                 "address": section.address, "values": values, "data": data,
                 "raw_hex": raw.hex() if raw is not None else None}
        if self.log:
            try:
                self.log.write(json.dumps(event) + "\n")
            except OSError as exc:
                self.log_error = exc
                self.stop.set()
                raise
        if self.on_event:
            self.on_event(event)

    async def read(self, client, uuid):
        return bytes(await asyncio.wait_for(client.read_gatt_char(uuid), 5))

    async def battery(self, key, client):
        if client.services.get_characteristic(BATTERY):
            try:
                raw = await self.read(client, BATTERY)
                self.record(key, {"Battery": f"{raw[0]} %" if len(raw) == 1 and raw[0] <= 100 else "unavailable"}, data={"battery_pct": raw[0] if len(raw) == 1 and raw[0] <= 100 else None}, raw=raw)
            except Exception as exc:
                self.sections[key].error = f"Battery: {exc}"

    async def release_stale_connection(self, key):
        """Release a BlueZ connection left open when a sensor stops advertising."""
        address = self.sections[key].address

        async def command(action, timeout):
            process = await asyncio.create_subprocess_exec(
                "bluetoothctl", action, address,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                raise
            return process.returncode, output

        try:
            _, output = await command("info", 6)
            if b"Connected: yes" not in output:
                return False
            returncode, _ = await command("disconnect", 8)
            if returncode == 0:
                LOG.warning("Released stale BlueZ %s connection %s", key, address)
                return True
        except Exception as exc:
            LOG.warning("Could not release stale BlueZ %s connection: %s", key, exc)
        return False

    async def connect(self, key):
        section = self.sections[key]
        # Never reuse a BLEDevice retained by an earlier discovery: BlueZ can
        # remove/recreate its D-Bus object. Serialize discovery AND connection.
        section.status = "queued · waiting for BLE adapter"
        async with self.connect_lock:
            if self.stop.is_set():
                return None
            section.status = "scanning BLE…"

            def matches(device, adv):
                self.advertisement(device, adv)
                return device.address.upper() == section.address

            device = await BleakScanner.find_device_by_filter(matches, timeout=6)
            if device is None or self.stop.is_set():
                self.devices.pop(key, None)
                if key in ("cardio", "speedcadence", "frontlight", "rearlight") and not self.stop.is_set() and await self.release_stale_connection(key):
                    section.status = "releasing stale BlueZ connection"
                return None
            client = BleakClient(device, timeout=90)
            try:
                section.status = "connecting and reading services… (first time: up to 90 s)"
                await asyncio.wait_for(client.connect(), 95)
                section.status, section.error = "connected", ""
                LOG.info("Connected %s %s", key, section.address)
                return client
            except BaseException:
                self.devices.pop(key, None)
                await self.disconnect(client)
                raise

    async def disconnect(self, client):
        if client:
            try:
                await asyncio.wait_for(client.disconnect(), 5)
            except Exception:
                pass

    async def pause(self, seconds):
        try:
            await asyncio.wait_for(self.stop.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    async def stream(self, key):
        section = self.sections[key]
        while not self.stop.is_set():
            client = None
            try:
                client = await self.connect(key)
                if client is None:
                    if section.status != "releasing stale BlueZ connection":
                        section.status = "searching · wake the sensor"
                    await self.pause(2)
                    continue
                await self.battery(key, client)
                if key == "speedcadence":
                    self.wheel, self.crank = Rotation(32), Rotation(16)
                    self.duo_packet_at = None
                last_packet = time.monotonic()

                def received(_, payload):
                    nonlocal last_packet
                    try:
                        raw = bytes(payload)
                        if key == "cardio":
                            values = decode_hr(raw)
                            display = {"Heart rate": f"{values['bpm']} bpm",
                                       "Contact": {True: "yes", False: "no", None: "unsupported"}[values['contact']],
                                       "RR intervals": ", ".join(f"{v:.0f} ms" for v in values['rr_ms']) or "not transmitted",
                                       "Energy": f"{values['energy_kj']} kJ" if 'energy_kj' in values else "not transmitted"}
                        else:
                            values = decode_csc(raw)
                            display = {}
                            for name, rotation in (("wheel", self.wheel), ("crank", self.crank)):
                                if name in values:
                                    rotation.update(*values[name])
                                    label = "Wheel" if name == "wheel" else "Crank"
                                    display[label + " · cumulative revolutions"] = rotation.count
                                    display[label + " · event time"] = f"{rotation.event} /1024 s (modulo 64 s)"
                            self.duo_packet_at = time.monotonic()
                        if self.args.raw:
                            display["BLE packet"] = raw.hex()
                        if key == "speedcadence":
                            wheel, crank = self.wheel.display_rate(), self.crank.display_rate()
                            values.update(speed_kmh=wheel * self.args.wheel_circumference * 3.6 if wheel is not None else None,
                                          cadence_rpm=crank * 60 if crank is not None else None,
                                          wheel_circumference_m=self.args.wheel_circumference)
                        self.record(key, display, data=values, raw=raw)
                        last_packet = time.monotonic()
                        section.error = ""
                    except Exception as exc:
                        section.error = f"Decode: {exc}"

                await client.start_notify(HR_UUID if key == "cardio" else CSC, received)
                battery_at = time.monotonic()
                while client.is_connected and not self.stop.is_set():
                    if time.monotonic() - last_packet > 35:
                        section.error = "No packets for 35 s; reconnecting"
                        break
                    if time.monotonic() - battery_at > 60:
                        await self.battery(key, client)
                        battery_at = time.monotonic()
                    await self.pause(1)
            except Exception as exc:
                section.error = f"{type(exc).__name__}: {exc}"
                LOG.exception("Stream %s failed", key)
            finally:
                await self.disconnect(client)
                if client is not None:
                    section.status = "disconnected · retrying"
                elif section.error:
                    section.status = "connection failed · retrying"
            await self.pause(3)

    async def light(self, key, client):
        # Publish useful readings immediately; descriptors are a static label table.
        await self.battery(key, client)
        modes = self.light_modes.setdefault(key, {})

        async def mode_reading():
            raw = await self.read(client, MODE)
            mode = raw[0] if len(raw) == 1 else None
            self.record(key, {"Mode": modes.get(mode, "description unavailable"),
                              "Mode code": mode if mode is not None else raw.hex()},
                        data={"mode": mode, "label": modes.get(mode)}, raw=raw)

        await mode_reading()
        for service in client.services:
            for char in service.characteristics:
                if char.uuid.startswith("712611") and "read" in char.properties:
                    # Keep successfully decoded descriptors for subsequent polls.
                    if (key, char.uuid) in self.light_descriptors:
                        continue
                    try:
                        raw = await self.read(client, char.uuid)
                        if len(raw) >= 4:
                            modes[raw[0]] = raw[3:].decode("utf-8", errors="replace").rstrip("\x00")
                            self.light_descriptors.add((key, char.uuid))
                    except Exception:
                        LOG.exception("Mode descriptor %s %s failed", key, char.uuid)
        await mode_reading()

    async def sram(self, client):
        raw = await self.read(client, "d9050003" + BASE)
        records = extract_sram(raw)
        labels = {0: "Left shifter", 1: "Right shifter", 128: "Front derailleur", 129: "Rear derailleur"}
        drivetrain = DEVICES["drivetrain"]["gearing"]
        values = {"Gear": "unavailable via BLE",
                  "Drivetrain": ("/".join(map(str, drivetrain["chainring_teeth_smallest_to_largest"]))
                                 + " · " + "-".join(map(str, drivetrain["cassette_teeth_smallest_to_largest"])))}
        for label in labels.values():
            values[label + " · battery*"] = "unavailable"
            values[label + " · serial / status"] = "unavailable"
        for record in records:
            if not record['product_id_candidate']:
                continue
            label = labels.get(record['role_raw'], f"Component {record['role_raw']}")
            voltage = record['voltage_v_hypothesis']
            values[label + " · battery*"] = f"{voltage:.3f} V" if voltage is not None and record['status_raw'] == 3 else "unavailable"
            values[label + " · serial / status"] = f"{record['serial']} / {record['status_raw']}"
            if record['role_raw'] == 129:
                payload = bytes.fromhex(record['raw_hex'])
                values["Shift counter · low byte"] = payload[20]
                values["Time counter* · uint16"] = int.from_bytes(payload[16:18], "little")
        values["* Interpretation"] = "Voltage and time counter experimental; left/right order from SDK"
        if self.args.raw:
            values["Dynamic BLE record"] = raw.hex()
        self.record("drivetrain", values, data={"records": records, "gear": None}, raw=raw)

    async def poll_sram(self):
        """Keep SRAM connected; light discovery never gates an established read."""
        section = self.sections["drivetrain"]
        while not self.stop.is_set():
            client = None
            try:
                client = await self.connect("drivetrain")
                if client is None:
                    section.status = "searching · wake the derailleur"
                else:
                    previous = None
                    while client.is_connected and not self.stop.is_set():
                        started = time.monotonic()
                        await self.sram(client)
                        finished = time.monotonic()
                        section.error = ""
                        timing = {"BLE read duration": f"{finished - started:.2f} s"}
                        if previous is not None:
                            timing["Actual read interval"] = f"{finished - previous:.2f} s"
                        for label, value in timing.items():
                            section.put(label, value)
                        previous = finished
                        section.status = "connected · continuous reads"
                        await self.pause(getattr(self.args, "sram_interval", 0.5))
            except Exception as exc:
                section.error = f"{type(exc).__name__}: {exc}"
                section.status = "connection failed · retrying"
                LOG.exception("SRAM continuous read failed")
            finally:
                await self.disconnect(client)
                if client is not None and not section.error:
                    section.status = "disconnected · retrying"
            await self.pause(3)

    async def poll_others(self):
        # One light at a time, alongside persistent HR, CSC and SRAM connections.
        while not self.stop.is_set():
            for key in ("frontlight", "rearlight"):
                if self.stop.is_set():
                    break
                client = None
                section = self.sections[key]
                try:
                    client = await self.connect(key)
                    if client is None:
                        section.status = "searching · wake the device"
                        continue
                    await self.light(key, client)
                    section.status = "reading acquired · polling"
                except Exception as exc:
                    section.status, section.error = "unreachable", f"{type(exc).__name__}: {exc}"
                    LOG.exception("Read %s failed", key)
                finally:
                    await self.disconnect(client)
            await self.pause(self.args.poll_interval)

    async def run(self):
        """Collect until stop.set(); expose sections and synchronous on_event callbacks.

        Every run records JSONL, including numeric data and raw measurement bytes.
        Callbacks must be fast and must not block the asyncio event loop.
        """
        path = self.args.log or Path(__file__).resolve().parent.parent / "data" / (
            datetime.now(timezone.utc).strftime("telemetry-%Y%m%dT%H%M%S-%fZ.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = path
        self.banner = f"Log: {path}"
        tasks = []
        with path.open("a", buffering=1) as self.log:
            try:
                tasks = [asyncio.create_task(self.stream("cardio")),
                         asyncio.create_task(self.stream("speedcadence")),
                         asyncio.create_task(self.poll_sram()),
                         asyncio.create_task(self.poll_others()),
                         asyncio.create_task(self.stop.wait())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                if self.log_error:
                    raise RuntimeError(f"Recording stopped: {self.log_error}") from self.log_error
            finally:
                self.stop.set()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.log = None

def extract_sram(raw):
    if len(raw) < 6 or raw[0] != 1 or len(raw) != 6 + raw[1] * 24:
        raise ValueError("Unrecognized record layout; expected version 1, count and 24-byte records")
    records = []
    for index in range(raw[1]):
        offset = 6 + index * 24
        record = raw[offset:offset + 24]
        value = int.from_bytes(record[8:10], "little")
        product = int.from_bytes(record[1:3], "little")
        records.append({
            "offset": offset, "raw_hex": record.hex(),
            "role_raw": record[0], "product_id_candidate": product,
            "serial": int.from_bytes(record[3:7], "little"),
            "status_raw": record[7], "field_u16_raw": value,
            "voltage_v_hypothesis": value / 1000 if product and value else None,
            "battery_percent": None,
        })
    return records


async def control(name, action):
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: (adv.local_name or d.name) == name, timeout=15)
    if device is None:
        raise RuntimeError(f"{name}: not found")
    async with BleakClient(device, timeout=20) as client:
        modes = {}
        for service in client.services:
            for char in service.characteristics:
                if char.uuid.startswith("712611") and "read" in char.properties:
                    raw = await asyncio.wait_for(client.read_gatt_char(char), 5)
                    if len(raw) >= 4:
                        modes[raw[0]] = raw[3:].decode("utf-8", errors="replace").rstrip("\x00")
        before = bytes(await asyncio.wait_for(client.read_gatt_char(MODE), 5))
        result = {"name": name, "address": device.address, "modes": modes,
                  "before_hex": before.hex()}
        if action != "status":
            if action == "flash":
                matches = [mode for mode, label in modes.items() if label.lower() == "day flash"]
                if len(matches) != 1:
                    raise RuntimeError(f"{name}: cannot identify Day Flash mode: {modes}")
                target = matches[0]
            else:
                target = 0 if action == "off" else 5
            # Only write a known mode when the light itself describes its purpose.
            label = modes.get(target, "").lower()
            accepted = label == "day flash" if action == "flash" else ((label == "off") if target == 0 else ("low" in label or "night steady" in label))
            if not accepted:
                raise RuntimeError(f"{name}: unrecognized mode {target}: {modes}; refusing write")
            await asyncio.wait_for(client.write_gatt_char(MODE, bytes([target]), response=True), 5)
            await asyncio.sleep(1)
            after = bytes(await asyncio.wait_for(client.read_gatt_char(MODE), 5))
            result.update(requested_mode=target, requested_label=modes[target], after_hex=after.hex())
            if after != bytes([target]):
                raise RuntimeError(f"Mode readback mismatch: {result}")
        battery = await asyncio.wait_for(client.read_gatt_char(BATTERY), 5)
        result["battery_percent"] = battery[0] if battery else None
        print(json.dumps(result), flush=True)


async def lights_command(args):
    failed = False
    for key in LIGHTS if args.light == "both" else [args.light]:
        try:
            await control(LIGHTS[key], args.action)
        except Exception as exc:
            print(json.dumps({"name": LIGHTS[key], "error": str(exc)}), flush=True)
            failed = True
    return 1 if failed else 0


def main():
    """Run explicit light commands; live collection uses BikeTelemetry."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    lights = commands.add_parser("lights", help="Read or control Trek lights")
    lights.add_argument("action", choices=["status", "on", "off", "flash"])
    lights.add_argument("--light", choices=["front", "rear", "both"], default="both")

    args = parser.parse_args()
    if args.command == "lights":
        raise SystemExit(asyncio.run(lights_command(args)))


if __name__ == "__main__":
    main()
