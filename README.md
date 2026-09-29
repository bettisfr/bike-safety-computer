# Bike Safety Computer

A Raspberry Pi bike computer in development. It collects cycling telemetry
over BLE and ANT+, records it locally, and presents live readings through a
web page and a terminal dashboard. The planned handlebar unit will use a
rugged monochrome display, physical buttons, and configurable pages.

The current setup includes a heart rate monitor, a speed/cadence sensor,
bicycle lights, and a SRAM AXS drivetrain. GPS, environmental sensors, radar,
and power meters are possible future additions.

## Project layout

- [ble_sensors.py](ble_sensors.py) collects BLE readings and provides explicit
  light commands.
- [ant_sensors.py](ant_sensors.py) collects ANT+ readings from the USB stick.
- [web_server.py](web_server.py) serves a shared telemetry API and web page.
- [templates/index.html](templates/index.html) is the page; [static/style.css](static/style.css)
  and [static/app.js](static/app.js) provide its styling and live updates.
- [dashboard.py](dashboard.py) is the terminal dashboard.
- [drivetrain.json](drivetrain.json) holds the bike-specific drivetrain setup.
- [scripts/rpi.sh](scripts/rpi.sh) deploys and manages the Raspberry Pi service.

The web page displays ANT+ readings. The collector also keeps BLE readings
available through the API and terminal dashboard. Only fields received from a
device are shown. ANT+ battery categories or voltage are not converted into
percentages.

## Raspberry Pi

The deployment script copies the application with rsync to `rpi5-02.local`,
uses `~/pyenv` for Python dependencies, and installs a systemd user service.
Set `RPI_HOST` to use another host. The default web port is `5050`.

```bash
./scripts/rpi.sh deploy
./scripts/rpi.sh start
./scripts/rpi.sh status
./scripts/rpi.sh restart
./scripts/rpi.sh stop
./scripts/rpi.sh logs
```

Open `http://rpi5-02.local:5050` from a device on the same network. The web
service shares one set of sensor connections between all browsers and records
measurements under `data/`. The page is read-only and has no authentication;
keep the service on a trusted local network.

The terminal dashboard uses the same sensors. Stop the web service before
starting it:

```bash
./scripts/rpi.sh stop
./scripts/rpi.sh dashboard
```

Run `./scripts/rpi.sh help` for maintenance commands, including light control
and copying recordings back to the PC.
