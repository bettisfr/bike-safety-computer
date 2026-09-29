# Bike Safety Computer

A Raspberry Pi 5 bike computer prototype with BLE and ANT+ sensor collection,
JSONL recording, a terminal dashboard, and a Flask page on the local network.
The intended handlebar device will have a rugged monochrome display, physical
buttons, and configurable pages. GPS, environmental sensors, cameras, radar,
and power meters are possible future additions.

## Current sensor coverage

| Device | BLE | ANT+ |
| --- | --- | --- |
| COOSPO H808S | Heart rate, contact, RR intervals and battery when transmitted | Heart rate, beat count, event time and battery when transmitted |
| Trek DuoTrap S | Wheel speed, crank cadence, counters and battery | Profile not yet integrated |
| Trek Ion Pro RT / Flare RT | Mode and battery; explicit on/off/flash commands | Profile not yet integrated |
| SRAM Force AXS 2×12 | Experimental battery-related fields and counters; gear position undecoded | Profile not yet integrated |

The device addresses in [ble_sensors.py](ble_sensors.py) belong to the bike used
for development. Wheel speed currently uses a **2.136 m** circumference, an
estimate for 700×28C tires; calibrate it on the actual wheel. The known
drivetrain has 35/48 chainrings and a 10-11-12-13-14-15-17-19-21-24-28-33
cassette, recorded in [drivetrain.json](drivetrain.json). Gear position is not
estimated from speed and cadence.

## Code layout

- [ble_sensors.py](ble_sensors.py) is the BLE library. `BikeTelemetry` collects
  all BLE devices and logs measurements. The same file offers explicit `lights`,
  `sram`, `sram_bond`, `sram_batteries`, and `sram_records` maintenance commands.
- [ant_sensors.py](ant_sensors.py) is the ANT+ library. `ANTHeartRate` receives
  heart-rate broadcasts through the USB stick; other ANT+ profiles can be added
  here.
- [web_server.py](web_server.py) joins the two collectors for one Flask API.
  [web.html](web.html) renders compact, separate BLE and ANT+ columns.
- [dashboard.py](dashboard.py) is the BLE terminal display. The web page is the
  current view for both protocols.

The consolidated BLE module includes SRAMBond code adapted from
[Gabor Wnuk's sram-axs](https://github.com/GaborWnuk/sram-axs) under MPL-2.0;
its attribution and license notice are retained in the source.

## Web dashboard

Open **http://rpi5-02.local:5050** from a computer on the same network. Each
sensor has a compact card in each protocol column. Heart rate appears in its
own card; speed and cadence appear in the BLE DuoTrap card. Each field shows
the age of its last reading. Yellow marks a recently changed value. A dash
means that no recent measurement is available. Profiles that have not been
integrated are labelled as such.

The page polls `/api/state` every 0.5 s. One collector serves all browsers and
continues recording with the page closed. HTTP requests never open additional
sensor connections. The page is read-only and has no external assets. There
is no authentication: anyone who can reach port 5050 on the local network can
read telemetry.

```bash
./scripts/rpi.sh deploy
./scripts/rpi.sh start
./scripts/rpi.sh status
./scripts/rpi.sh stop
```

Or, with the service stopped, run it on the Pi:

```bash
~/pyenv/bin/python ~/bike-safety-computer/web_server.py
```

Options include `--port 5050`, `--host 0.0.0.0`,
`--wheel-circumference 2.136`, `--sram-interval 0.5`,
`--poll-interval 10`, and `--log PATH`. Measurements are saved to
`data/telemetry-*.jsonl`; server diagnostics go to `data/web-*.log`.
The API exposes separate `sections_ble` and `sections_ant` objects.

## Deployment and ANT+ USB access

`scripts/rpi.sh deploy` uses SSH and rsync to `rpi5-02.local`, copies only the
application files that changed to
`~/bike-safety-computer`, installs Python requirements in `~/pyenv`, and installs
the user service. Override the host with `RPI_HOST=fra@HOST`.
The file list is explicit: deployment leaves remote recordings and `.secrets/`
untouched.

The Pi's ANTUSB2 stick has USB ID `0fcf:1008`. Linux also recognizes it as a
Suunto serial converter. OpenANT needs direct USB access, so the installer
grants the `plugdev` group access to that USB ID and blacklists
`usb_serial_simple` on this dedicated bike Pi. These are system-wide USB driver
settings on that Pi. The installer reloads udev rules and unloads the serial
driver. The user must belong to `plugdev`; `sudo -n` must work for setup.

```bash
./scripts/rpi.sh restart   # Load changed code after deployment
./scripts/rpi.sh enable    # Start on boot; enables user linger
./scripts/rpi.sh disable
./scripts/rpi.sh logs
./scripts/rpi.sh fetch     # Copy recordings to data/rpi on the PC
```

The service is enabled on `rpi5-02`. The older installation on `rpi5-00` was
removed during migration. The deploy script installs or updates the service;
use `start` or `restart` to run the new code.

## Terminal dashboard and library use

The terminal dashboard displays BLE measurements and writes the same JSONL
format as the web service. They share `.telemetry.lock`, so stop the service
before launching the terminal dashboard.

```bash
./scripts/rpi.sh stop
./scripts/rpi.sh dashboard
# Or on the Pi:
~/pyenv/bin/python ~/bike-safety-computer/dashboard.py
```

Wear the chest strap, spin the wheel or crank, and wake other sensors to see
their readings. Use arrow keys or PgUp/PgDn to scroll and `q` to exit. `--plain`
prints snapshots without colors; `--raw` also shows packet hex. The default
JSONL path is under `~/bike-safety-computer/data/`. The log includes UTC and
monotonic timestamps, device address, displayed and decoded values, and raw
measurement bytes. It grows until the collector stops; no automatic rotation
is implemented.

```python
import asyncio
from ble_sensors import BikeTelemetry, TelemetryConfig

async def main():
    telemetry = BikeTelemetry(TelemetryConfig(), on_event=print)
    await telemetry.run()  # telemetry.stop.set() ends collection

asyncio.run(main())
```

The callback is synchronous and should return quickly. Current readings are
available through `telemetry.sections`. BLE discovery and connections are
serialized to avoid stale BlueZ device objects. Heart rate, DuoTrap and SRAM
can remain connected while one light is polled. The first GATT service
enumeration can take tens of seconds. The light poll pauses 10 s between
cycles by default; SRAM pauses 0.5 s after each read. A pause does not imply
that the device updates its characteristic at the same rate.

The DuoTrap display uses zero after 5 s without wheel or crank pulses as an
inactivity convention. It shows a dash when recent data is missing.

## Trek lights

The BLE `lights` command discovers Ion Pro RT and Flare RT by advertised name,
reads their batteries and mode tables, and can select off, low steady, or Day
Flash. Stop the web service before standalone BLE commands, then restart it.
The script checks each light's own mode labels before writing and reads the
mode back. When several lights share a name, discovery selects the first.

```bash
./scripts/rpi.sh lights status
./scripts/rpi.sh lights on                 # Both, low/night steady
./scripts/rpi.sh lights off
./scripts/rpi.sh lights flash              # Both, Day Flash
./scripts/rpi.sh lights on --light front   # Or rear
```

The characteristic was identified using
[independent Ion 200 RT protocol research](https://gist.github.com/mywalkb/e0de3828cc0a84860a07bde5a6ec6c5c).
Visual confirmation of the LEDs remains useful after a write.

## SRAM AXS diagnostics

Wake the rear derailleur and disconnect the SRAM phone app before discovery.
The inspection commands record the GATT service tree and selected readable
characteristics without changing drivetrain settings:

```bash
./scripts/rpi.sh sram scan
./scripts/rpi.sh sram probe --seconds 30
./scripts/rpi.sh sram probe --address AA:BB:CC:DD:EE:FF
./scripts/rpi.sh sram capture --address AA:BB:CC:DD:EE:FF --seconds 40
./scripts/rpi.sh fetch
```

`probe` saves `data/sram-*.json`; `capture` repeatedly reads selected
characteristics into JSONL. It announces a 10 s baseline before the shift
phase. Record the actual starting gear and each manual shift separately:
changing bytes alone do not establish a gear decoder. Vendor payload meanings
remain unverified on this Force AXS 2×12; upstream protocol work was validated
on GX Eagle Transmission. See [SRAM_APK_FINDINGS.md](SRAM_APK_FINDINGS.md).

### Experimental SRAMBond

The `sram_bond` command pairs in AXS mode and saves the diagnostics key under
`.secrets/` with restricted permissions. A saved key prevents accidental
rebonding. The official app may rebond later; normal shifting uses a separate
link. Only the SRAMBond characteristic is written by this command.

```bash
./scripts/rpi.sh sram_bond bond --address AA:BB:CC:DD:EE:FF --ready
./scripts/rpi.sh sram_bond read --address AA:BB:CC:DD:EE:FF
./scripts/rpi.sh sram_bond read --address AA:BB:CC:DD:EE:FF --all-readable --gear-label 48x11
```

Put the rear derailleur in pairing mode until its LED blinks before `bond`.
`--all-readable` skips bond and token endpoints. `--gear-label` records a
user-supplied reference, not a decoded position. Pairing succeeded on this
Force 2×12 on 2026-09-26. Authenticated decryption succeeded for several
characteristics, but their field meanings and live gear position remain
unverified. A prior short button press had not entered pairing mode.

### Battery advertisements and saved records

```bash
./scripts/rpi.sh sram_batteries --seconds 45
./scripts/rpi.sh fetch
python3 ble_sensors.py sram_records data/rpi/sram-bond-probe-20260926T195620Z.json --output data/rpi/sram-battery-records.json
```

Press each component's AXS button briefly during the advertisement scan. The
documented battery advertisement format has been observed on other AXS models,
but this Force's observed FE51 record has not yielded a verified percentage.
Missing advertisements do not imply an empty battery.

The observed `d9050003` payload contains a six-byte header and five 24-byte
records. Four product records have nonzero unsigned values at offset 8.
Swapping the two rechargeable derailleur packs reversed the ordering of some
values, supporting a battery-related interpretation without validating a
voltage scale or charge percentage. Controller battery records, status codes,
and gear position remain unverified; the decoder retains raw bytes.
