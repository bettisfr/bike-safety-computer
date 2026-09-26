"""Capture SRAM battery advertisements without connecting.

Format reference: https://github.com/tarekrached/esphome-sram-axs/blob/main/docs/protocol.md
Field meanings were verified upstream on other AXS models, not this Force.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakScanner


def decode(payload):
    # Decode only the documented battery record, not identity/build records.
    if len(payload) < 12 or payload[:2] != b"\x00\x00" or payload[4:7] != b"\x00\x04\x05":
        return {"format": "unrecognized"}
    voltage = int.from_bytes(payload[7:9], "little")
    percent = payload[11]
    return {"format": "documented_12_byte_prefix", "voltage_mv_candidate": voltage,
            "battery_percent_candidate": percent if percent <= 100 else None,
            "percent_supported": percent != 255,
            "validation": "upstream decoder; not independently calibrated on this device"}


async def main(seconds):
    output = Path(__file__).resolve().parent / "data"
    output.mkdir(exist_ok=True)
    path = output / ("sram-batteries-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".jsonl")
    latest = {}
    with path.open("w", buffering=1) as stream:
        def received(device, adv):
            name = adv.local_name or device.name or ""
            payload = adv.manufacturer_data.get(2355)
            if "sram" not in name.lower() and payload is None:
                return
            row = {"timestamp": datetime.now(timezone.utc).isoformat(), "address": device.address,
                   "name": name, "rssi": adv.rssi,
                   "manufacturer_data": {str(k): v.hex() for k, v in adv.manufacturer_data.items()},
                   "service_data": {k: v.hex() for k, v in adv.service_data.items()}}
            if payload is not None:
                row.update(decode(payload))
            stream.write(json.dumps(row) + "\n")
            if latest.get(device.address, {}).get("manufacturer_data") != row["manufacturer_data"] or device.address not in latest:
                print(json.dumps(row), flush=True)
            latest[device.address] = row
        print(f"Listening for SRAM advertisements for {seconds}s", flush=True)
        async with BleakScanner(received):
            await asyncio.sleep(seconds)
    print(f"Finished: {len(latest)} devices; saved {path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=45)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    asyncio.run(main(args.seconds))
