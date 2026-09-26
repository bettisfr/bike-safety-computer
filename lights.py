"""Inspect and control Trek lights through their BLE mode characteristic.

Protocol reference (Ion 200 RT; verify each light's advertised mode table):
https://gist.github.com/mywalkb/e0de3828cc0a84860a07bde5a6ec6c5c
"""
import argparse
import asyncio
import json

from bleak import BleakClient, BleakScanner

MODE = "71261001-3692-ae93-e711-472ba41689c9"
BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"
LIGHTS = {"front": "Ion Pro RT", "rear": "Flare RT"}


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


async def main(args):
    failed = False
    for key in LIGHTS if args.light == "both" else [args.light]:
        try:
            await control(LIGHTS[key], args.action)
        except Exception as exc:
            print(json.dumps({"name": LIGHTS[key], "error": str(exc)}), flush=True)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "on", "off", "flash"])
    parser.add_argument("--light", choices=["front", "rear", "both"], default="both")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
