"""Extract experimental Force AXS records from saved probes; no BLE writes.

Record layout inferred from this bike's captures. Field meanings, including
voltage units and status codes, have NOT been independently validated.
"""
import argparse
import json
from pathlib import Path

UUID = "d9050003-90aa-4c7c-b036-1e01fb8eb7ee"


def extract(raw):
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    probe = json.loads(args.probe.read_text())
    samples = probe["reads"][UUID]
    if isinstance(samples, dict):
        samples = [samples]
    report = {
        "source": str(args.probe), "timestamp": probe.get("timestamp"),
        "validation": "Experimental layout; voltage and status semantics unverified; not live data",
        "samples": [extract(bytes.fromhex(sample.get("raw_hex", sample.get("hex", ""))))
                    for sample in samples],
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
