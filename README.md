# Bike Safety Computer

A Raspberry Pi bike computer in development. It collects cycling telemetry
over BLE and ANT+, records it locally, and presents live readings through a
web page and a terminal dashboard. The planned handlebar unit will use a
rugged monochrome display, physical buttons, and configurable pages.

The current setup includes a heart rate monitor, a speed/cadence sensor,
bicycle lights, and a SRAM AXS drivetrain. GPS, environmental sensors, radar,
and power meters are possible future additions.

## Project layout

- [telemetry/ble_sensors.py](telemetry/ble_sensors.py) collects BLE readings and provides explicit
  light commands.
- [telemetry/ant_sensors.py](telemetry/ant_sensors.py) collects ANT+ readings from the USB stick.
- [web_server.py](web_server.py) serves a shared telemetry API and web page.
- [www/templates/index.html](www/templates/index.html) is the page;
  [www/static/style.css](www/static/style.css) and
  [www/static/app.js](www/static/app.js) provide its styling and live updates.
- [telemetry/dashboard.py](telemetry/dashboard.py) is the terminal dashboard.
- [config.json](config.json) holds the devices, their BLE/ANT+ identifiers,
  wheel circumference, and SRAM drivetrain setup.
- [scripts/rpi.sh](scripts/rpi.sh) deploys and manages the Raspberry Pi service.

An ANT+ `device_id` set to `null` accepts devices of that profile until their
identifier is known; this is useful for components that transmit separately.

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
