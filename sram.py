"""Read-only SRAM AXS BLE discovery and inspection; no pairing or writes.

Vendor UUID reference (verified upstream on GX, not assumed identical on Force):
https://github.com/GaborWnuk/sram-axs/blob/main/PROTOCOL.md
"""
import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner

BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"
BASE = "-90aa-4c7c-b036-1e01fb8eb7ee"
READABLE = {BATTERY, *(f"d905{s}{BASE}" for s in
                        ("fe54", "fe56", "fe58", "fff1", "fff2", "000a", "0002", "0003", "000b", "0024", "0025"))}


def is_sram(device, adv):
    name = adv.local_name or device.name or ""
    return "sram" in name.lower() or 0x0933 in adv.manufacturer_data or any(
        u.startswith("d905") or u.startswith("0000fe51") for u in adv.service_uuids)


async def main(args):
    if args.action == "scan":
        devices = await BleakScanner.discover(timeout=args.seconds, return_adv=True)
        results = [{"address": d.address, "name": a.local_name or d.name,
                    "rssi": a.rssi, "services": a.service_uuids}
                   for d, a in devices.values() if is_sram(d, a)]
        print(json.dumps(results, indent=2))
        return 0 if results else 1
    if args.address:
        device = await BleakScanner.find_device_by_address(args.address, timeout=args.seconds)
    else:
        device = await BleakScanner.find_device_by_filter(is_sram, timeout=args.seconds)
    if device is None:
        raise RuntimeError("SRAM not found: wake the derailleur and close the phone app")
    report = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "address": device.address, "name": device.name, "services": [], "reads": {}}
    print(json.dumps({"found": device.name, "address": device.address}), flush=True)
    async with BleakClient(device, timeout=30) as client:
        if args.action == "capture":
            output = Path(__file__).resolve().parent / "data"
            output.mkdir(exist_ok=True)
            path = output / ("sram-capture-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".jsonl")
            targets = [f"d905{s}{BASE}" for s in ("0002", "0003", "000b", "0024", "0025")
                       if client.services.get_characteristic(f"d905{s}{BASE}")]
            print("BASELINE: keep gears unchanged for 10 seconds", flush=True)
            started = time.monotonic()
            announced = False
            count = 0
            with path.open("w", buffering=1) as stream:
                while time.monotonic() - started < args.seconds:
                    if not announced and time.monotonic() - started >= 10:
                        print("SHIFT NOW: rear shifts only", flush=True)
                        announced = True
                    for uuid in targets:
                        row = {"timestamp": datetime.now(timezone.utc).isoformat(),
                               "elapsed_s": time.monotonic() - started, "uuid": uuid,
                               "address": device.address}
                        try:
                            raw = await asyncio.wait_for(client.read_gatt_char(uuid), 3)
                            row["hex"] = raw.hex()
                        except Exception as exc:
                            row["error"] = str(exc)
                        stream.write(json.dumps(row) + "\n")
                        count += 1
                    await asyncio.sleep(0.3)
            print(f"DONE: {count} reads saved to {path}", flush=True)
            return 0
        for service in client.services:
            report["services"].append({"uuid": service.uuid, "characteristics": [
                {"uuid": ch.uuid, "properties": ch.properties} for ch in service.characteristics]})
            for ch in service.characteristics:
                standard_info = ch.uuid in {f"00002a{x}-0000-1000-8000-00805f9b34fb"
                                            for x in ("24", "26", "27", "28", "29")}
                if "read" not in ch.properties or not (ch.uuid in READABLE or standard_info):
                    continue
                try:
                    raw = bytes(await asyncio.wait_for(client.read_gatt_char(ch), 5))
                    value = {"hex": raw.hex(), "length": len(raw)}
                    if ch.uuid == BATTERY and len(raw) == 1 and raw[0] <= 100:
                        value["battery_percent"] = raw[0]
                    if standard_info:
                        value["text"] = raw.decode("utf-8", errors="replace")
                    report["reads"][ch.uuid] = value
                except Exception as exc:
                    report["reads"][ch.uuid] = {"error": str(exc)}
    output = Path(__file__).resolve().parent / "data"
    output.mkdir(exist_ok=True)
    path = output / ("sram-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ") + ".json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"Saved: {path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["scan", "probe", "capture"])
    parser.add_argument("--address")
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    raise SystemExit(asyncio.run(main(args)))
