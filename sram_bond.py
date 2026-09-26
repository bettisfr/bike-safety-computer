# SPDX-License-Identifier: MPL-2.0
# SRAMBond handshake adapted from Gabor Wnuk's sram-axs (copyright 2026).
# https://github.com/GaborWnuk/sram-axs/blob/main/packages/axs-core/src/axs/srambond-bond.ts
# This file is subject to the Mozilla Public License 2.0:
# https://mozilla.org/MPL/2.0/
"""Experimental SRAMBond v1 pairing and authenticated payload inspection."""
import argparse
import asyncio
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner
from Crypto.Cipher import AES

BASE = "-90aa-4c7c-b036-1e01fb8eb7ee"
BOND = "d905ee52" + BASE
MODULUS = (1 << 128) - 713


def public_key(private):
    if len(private) != 16:
        raise ValueError("Private key must be 16 bytes")
    return pow(5, int.from_bytes(private, "little"), MODULUS).to_bytes(16, "big")


def shared_key(private, peer):
    value = int.from_bytes(peer, "big")
    if len(private) != 16 or len(peer) != 16 or not 1 < value < MODULUS - 1:
        raise ValueError("Invalid DH key")
    return pow(value, int.from_bytes(private, "little"), MODULUS).to_bytes(16, "big")


def decrypt(key, frame):
    if len(frame) < 32:
        raise ValueError("Frame shorter than nonce and authentication tag")
    cipher = AES.new(key, AES.MODE_EAX, nonce=frame[:16], mac_len=16)
    return cipher.decrypt_and_verify(frame[16:-16], frame[-16:])


def store_key(path, key):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(key.hex() + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


async def bond(client, path, diagnose=False):
    inbox = asyncio.Queue()
    await client.start_notify(BOND, lambda _, value: inbox.put_nowait(bytes(value)))
    try:
        print("Pairing: init", flush=True)
        await asyncio.wait_for(client.write_gatt_char(BOND, bytes(range(16)), response=True), 8)
        if diagnose:
            trace = []
            async def collect(stage):
                packets = []
                for _ in range(12):
                    try:
                        packet = await asyncio.wait_for(inbox.get(), 2)
                    except asyncio.TimeoutError:
                        break
                    packets.append(packet)
                trace.append({"stage": stage, "lengths": [len(p) for p in packets],
                              "response_hex": b"".join(packets).hex()})
                print(f"{stage}: notification lengths {[len(p) for p in packets]}", flush=True)
            await collect("init")
            await asyncio.wait_for(client.write_gatt_char(BOND, public_key(secrets.token_bytes(16)), response=True), 8)
            await collect("public_key")
            output = path.parent.parent / "data"
            output.mkdir(exist_ok=True)
            (output / "sram-handshake-diagnostic.json").write_text(json.dumps(trace, indent=2) + "\n")
            raise RuntimeError("Diagnostic saved; no finalize sent and no key saved")
        private = secrets.token_bytes(16)
        print("Pairing: client public key", flush=True)
        await asyncio.wait_for(client.write_gatt_char(BOND, public_key(private), response=True), 8)
        peer = await asyncio.wait_for(inbox.get(), 8)
        print(f"Pairing: first response {len(peer)} bytes", flush=True)
        # Test whether older firmware packs the public key + transport blob
        # across ATT-sized notifications instead of preserving message boundaries.
        combined = peer
        for _ in range(8):
            if len(combined) >= 64:
                break
            part = await asyncio.wait_for(inbox.get(), 8)
            print(f"Pairing: additional notification {len(part)} bytes", flush=True)
            combined += part
        if len(combined) != 64:
            raise ValueError(f"Handshake response length {len(combined)}, expected 64")
        shared = shared_key(private, combined[:16])
        blob = combined[16:]
        if len(blob) != 48:
            raise ValueError(f"Key transport length {len(blob)}, expected 48")
        key = decrypt(shared, blob)
        if len(key) != 16:
            raise ValueError("Invalid transported key length")
        # Keep a recoverable local key even if the final BLE response is lost.
        store_key(path, key)
        print("Pairing: authenticated key saved; finalize", flush=True)
        await asyncio.wait_for(client.write_gatt_char(BOND, b"\x73", response=True), 8)
        print("Pairing completed (key not printed)", flush=True)
        return key
    finally:
        if client.is_connected:
            await client.stop_notify(BOND)


async def main(args):
    root = Path(__file__).resolve().parent
    path = root / ".secrets" / (args.address.replace(":", "").lower() + ".key")
    if args.action == "bond" and not args.ready:
        raise RuntimeError("Put the derailleur in AXS pairing mode, then pass --ready")
    if args.action == "bond" and path.exists():
        raise RuntimeError("A key already exists; use read to avoid replacing the bond")
    device = await BleakScanner.find_device_by_address(args.address, timeout=30)
    if device is None:
        raise RuntimeError("SRAM device not found")
    print(f"Connecting to {device.name}", flush=True)
    async with BleakClient(device, timeout=30) as client:
        key = await bond(client, path, args.diagnose) if args.action == "bond" else bytes.fromhex(path.read_text().strip())
        report = {"timestamp": datetime.now(timezone.utc).isoformat(), "address": args.address,
                  "characteristics": [ch.uuid for s in client.services for ch in s.characteristics],
                  "reads": {}}
        targets = ["d905" + short + BASE for short in
                   ("000b", "0024", "0025", "0003", "0002", "0008", "0006", "0011", "0021", "0022")]
        if args.all_readable:
            targets = [ch.uuid for service in client.services for ch in service.characteristics
                       if "read" in ch.properties and ch.uuid not in (BOND, "d905ee53" + BASE)]
        report["user_reported_gear"] = args.gear_label
        report["all_readable_except_bond_tokens"] = args.all_readable
        for uuid in targets:
            ch = client.services.get_characteristic(uuid)
            if ch is None or "read" not in ch.properties:
                continue
            samples = []
            for _ in range(2):
                try:
                    raw = bytes(await asyncio.wait_for(client.read_gatt_char(ch), 5))
                    row = {"raw_hex": raw.hex(), "length": len(raw)}
                    try:
                        row["authenticated_plaintext_hex"] = decrypt(key, raw).hex()
                    except ValueError:
                        row["authenticated"] = False
                    samples.append(row)
                except Exception as exc:
                    samples.append({"error": str(exc)})
            report["reads"][uuid] = samples
        output = root / "data"
        output.mkdir(exist_ok=True)
        target = output / ("sram-bond-probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
        target.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
        print(f"Saved: {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["bond", "read"])
    parser.add_argument("--address", required=True)
    parser.add_argument("--ready", action="store_true")
    parser.add_argument("--diagnose", action="store_true", help="Record handshake framing without finalizing")
    parser.add_argument("--all-readable", action="store_true", help="Read all readable characteristics except bond/token endpoints")
    parser.add_argument("--gear-label", help="User-reported reference only; not a decoded gear")
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1)
