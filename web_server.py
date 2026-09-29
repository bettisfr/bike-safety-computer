"""Flask UI with shared BLE/ANT+ collectors and automatic JSONL recording."""
import argparse
import asyncio
import fcntl
import logging
import math
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template
from werkzeug.serving import make_server

from telemetry.ble_sensors import BikeTelemetry, TelemetryConfig
from telemetry.ant_sensors import ANTSensorCollector
from telemetry.config import WHEEL_CIRCUMFERENCE_M

ROOT = Path(__file__).resolve().parent


class Collector:
    def __init__(self, config):
        self.config = config
        self.mutex = threading.Lock()
        self.state = {"state": "starting", "sections": {}, "error": None}
        self.loop = None
        self.telemetry = None
        self.ant = ANTSensorCollector(config.wheel_circumference)
        self.closing = threading.Event()
        self.thread = threading.Thread(target=self.worker, name="bike-ble", daemon=True)

    def snapshot(self):
        with self.mutex:
            state = dict(self.state)
        state["sections_ant"] = self.ant.snapshot()
        return state

    def publish(self, state):
        # Replace complete snapshots: request threads never access mutable BLE state.
        with self.mutex:
            self.state = state

    async def snapshots(self):
        app = self.telemetry
        while not app.stop.is_set():
            now = time.monotonic()
            sections = {}
            for key, section in app.sections.items():
                sections[key] = {
                    "name": section.name, "status": section.status,
                    "error": section.error, "rssi": section.rssi,
                    "advertisement_age_s": now - section.seen if section.seen is not None else None,
                    "fields": [{"label": label, "value": value, "age_s": now - updated,
                                "changed": now - section.changed.get(label, 0) < 2}
                               for label, (value, updated) in section.visible_fields().items()],
                }
            fresh = (app.duo_packet_at is not None and now - app.duo_packet_at < 10
                     and app.sections["speedcadence"].status == "connected")
            wheel = app.wheel.display_rate() if fresh else None
            crank = app.crank.display_rate() if fresh else None
            sections["speedcadence"]["speed_kmh"] = wheel * self.config.wheel_circumference * 3.6 if wheel is not None else None
            sections["speedcadence"]["cadence_rpm"] = crank * 60 if crank is not None else None
            self.publish({"state": "running", "error": None, "timestamp": time.time(),
                          "log": getattr(app, "log_path", Path("opening")).name,
                          "wheel_circumference_m": self.config.wheel_circumference,
                          "sections": sections, "sections_ble": sections})
            await app.pause(0.25)

    async def collect(self):
        self.loop = asyncio.get_running_loop()
        self.telemetry = BikeTelemetry(self.config)
        if self.closing.is_set():
            return
        tasks = [asyncio.create_task(self.telemetry.run()), asyncio.create_task(self.snapshots())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            self.telemetry.stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def worker(self):
        try:
            asyncio.run(self.collect())
            self.publish({**self.snapshot(), "state": "stopped"})
        except Exception as exc:
            logging.exception("BLE collector stopped")
            self.publish({**self.snapshot(), "state": "error", "error": f"{type(exc).__name__}: {exc}"})

    def close(self):
        self.closing.set()
        self.ant.close()
        if self.loop and self.telemetry and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.telemetry.stop.set)
            except RuntimeError:
                pass
        self.thread.join(timeout=15)


def create_app(collector):
    app = Flask(__name__, template_folder="www/templates", static_folder="www/static")

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def state():
        return jsonify(collector.snapshot())

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--wheel-circumference", type=float, default=WHEEL_CIRCUMFERENCE_M)
    parser.add_argument("--poll-interval", type=float, default=10)
    parser.add_argument("--sram-interval", type=float, default=0.5)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if not 0.1 < args.wheel_circumference < 5:
        parser.error("Wheel circumference must be between 0.1 and 5 m")
    if not math.isfinite(args.poll_interval) or args.poll_interval < 1:
        parser.error("Light poll interval must be finite and at least 1 s")
    if not math.isfinite(args.sram_interval) or args.sram_interval < 0.1:
        parser.error("SRAM interval must be finite and at least 0.1 s")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    (ROOT / "data").mkdir(exist_ok=True)
    diagnostic = ROOT / "data" / datetime.now(timezone.utc).strftime("web-%Y%m%dT%H%M%S-%fZ.log")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(diagnostic), logging.StreamHandler()])
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    with (ROOT / ".telemetry.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "Telemetry already running: close the dashboard or stop bike-telemetry.service.\n")
        collector = Collector(TelemetryConfig(wheel_circumference=args.wheel_circumference,
                              poll_interval=args.poll_interval, sram_interval=args.sram_interval,
                              log=args.log))
        server = make_server(args.host, args.port, create_app(collector), threaded=True)

        def stop(*_):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        collector.ant.start()
        collector.thread.start()
        logging.info("Bike web: http://%s:%s", args.host, args.port)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            collector.close()


if __name__ == "__main__":
    main()
