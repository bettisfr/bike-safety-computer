"""Read ANT+ heart-rate and battery broadcasts for the web dashboard."""
import logging
import threading
import time

LOG = logging.getLogger("bike.ant")


class ANTHeartRate:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.node = None
        self.state = {
            "cardio": {"name": "COOSPO H808S", "status": "initializing ANT+",
                       "error": "", "fields": []}
        }
        self.thread = threading.Thread(target=self._run, name="bike-ant", daemon=True)

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            return {key: {**value, "fields": [
                {"label": field["label"], "value": field["value"],
                 "age_s": now - field["updated"],
                 "changed": now - field["changed_at"] < 2}
                for field in value["fields"]]}
                    for key, value in self.state.items()}

    def _set_status(self, status, error=""):
        with self.lock:
            item = self.state["cardio"]
            item["status"], item["error"] = status, error

    def _put(self, label, value):
        now = time.monotonic()
        with self.lock:
            item = self.state["cardio"]
            fields = {field["label"]: field for field in item["fields"]}
            old = fields.get(label)
            fields[label] = {"label": label, "value": str(value),
                             "changed_at": now if old is None or old["value"] != str(value)
                             else old["changed_at"],
                             "updated": now}
            item["fields"] = list(fields.values())
            item["status"], item["error"] = "connected", ""

    def _run(self):
        try:
            from openant.devices import ANTPLUS_NETWORK_KEY
            from openant.devices.common import DeviceType
            from openant.devices.scanner import Scanner
            from openant.easy.node import Node
        except Exception as exc:
            LOG.exception("ANT+ package unavailable")
            self._set_status("ANT+ error", f"{type(exc).__name__}: {exc}")
            return

        while not self.stop_event.is_set():
            node = None
            try:
                self._set_status("searching for ANT+ chest strap…")
                node = Node()
                self.node = node
                node.set_network_key(0, ANTPLUS_NETWORK_KEY)
                scanner = Scanner(node, device_type=DeviceType.HeartRate.value)
                selected = [None]

                def on_packet(data):
                    scanner._on_data(data)
                    if len(data) < 8 or not scanner.found:
                        return
                    device_id = data[9] | data[10] << 8 if len(data) >= 13 else None
                    if selected[0] is None and device_id is not None:
                        selected[0] = device_id
                        self._put("ANT+ ID", device_id)
                    if device_id != selected[0]:
                        return
                    page = data[0] & 0x0F
                    if page > 7:
                        return
                    self._put("Heart rate", f"{data[7]} bpm")
                    self._put("Beat count", data[6])
                    self._put("Event time", f"{int.from_bytes(data[4:6], 'little') / 1024:.3f} s")
                    if page == 7 and data[1] <= 100:
                        self._put("Battery", f"{data[1]} %")

                scanner.channel.on_broadcast_data = on_packet
                self._set_status("listening on ANT+ · wear the chest strap")
                node.start()
                if not self.stop_event.is_set():
                    scanner.close_channel()
            except Exception as exc:
                if not self.stop_event.is_set():
                    LOG.exception("ANT+ heart-rate collector stopped")
                    self._set_status("ANT+ error · retrying", f"{type(exc).__name__}: {exc}")
            finally:
                self.node = None
                try:
                    if node is not None:
                        node.stop()
                except Exception:
                    LOG.exception("Error stopping ANT+ node")
            self.stop_event.wait(5)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.node is not None:
            try:
                self.node.stop()
            except Exception:
                LOG.exception("Error closing ANT+ USB stick")
        self.thread.join(timeout=10)
