"""Terminal display for bike_telemetry: live sections, colors and JSONL logging."""
import argparse
import asyncio
import curses
import fcntl
import math
import logging
from datetime import datetime, timezone
import signal
import sys
import time
from pathlib import Path
from bike_telemetry import BikeTelemetry


class Dashboard(BikeTelemetry):
    def lines(self):
        now = time.monotonic()
        lines = ["BIKE · TELEMETRIA LIVE    " + time.strftime("%H:%M:%S"),
                 "q / Ctrl+C: esci · ↑↓ / PgUp PgDn: scorri · età a destra = ultima lettura",
                 self.banner, ""]
        for key, section in self.sections.items():
            lines.append(f"── {section.name} ── {section.status}")
            if section.rssi is not None:
                lines.append(f"  Segnale ultimo annuncio: {section.rssi} dBm · {now - section.seen:.0f} s fa")
            if key == "duo":
                fresh = self.duo_packet_at is not None and now - self.duo_packet_at < 10 and section.status == "connesso"
                wheel = self.wheel.display_rate() if fresh else None
                crank = self.crank.display_rate() if fresh else None
                speed = f"{wheel * self.args.wheel_circumference * 3.6:.1f} km/h" if wheel is not None else "--"
                cadence = f"{crank * 60:.1f} rpm" if crank is not None else "--"
                lines.extend([f"  Velocità: {speed}    Cadenza: {cadence}",
                              f"  Circonferenza impostata: {self.args.wheel_circumference:.3f} m; 0 dopo 5 s senza impulsi"])
            visible = section.visible_fields()
            for label, (value, updated) in visible.items():
                lines.append(f"  {label}: {value}  [{now - updated:.0f} s fa]")
            if not visible:
                lines.append("  Nessuna lettura ricevuta")
            if section.error:
                lines.append("  Avviso: " + section.error.replace("\n", " "))
            lines.append("")
        return lines

    async def render(self, screen):
        if screen:
            screen.nodelay(True)
            screen.keypad(True)
            if curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                for index, color in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED), 1):
                    curses.init_pair(index, color, -1)
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        while not self.stop.is_set():
            lines = self.lines()
            if screen is None:
                print("\n".join(lines), flush=True)
            else:
                height, width = screen.getmaxyx()
                key = screen.getch()
                if key in (ord('q'), ord('Q'), 3):
                    self.stop.set()
                if key in (curses.KEY_DOWN, ord('j')):
                    self.offset += 1
                if key in (curses.KEY_UP, ord('k')):
                    self.offset -= 1
                if key == curses.KEY_NPAGE:
                    self.offset += max(1, height - 2)
                if key == curses.KEY_PPAGE:
                    self.offset -= max(1, height - 2)
                self.offset = max(0, min(self.offset, max(0, len(lines) - height + 1)))
                screen.erase()
                for row, line in enumerate(lines[self.offset:self.offset + max(1, height - 1)]):
                    try:
                        style = 0
                        if curses.has_colors():
                            if line.startswith("──"):
                                style = curses.color_pair(1) | curses.A_BOLD
                            elif "Avviso:" in line or "NON DISPONIBILE" in line:
                                style = curses.color_pair(4)
                            elif "Velocità:" in line:
                                style = curses.color_pair(2) | curses.A_BOLD
                            else:
                                for section in self.sections.values():
                                    for label, changed in section.changed.items():
                                        if line.startswith(f"  {label}:") and time.monotonic() - changed < 2:
                                            style = curses.color_pair(3) | curses.A_BOLD
                        screen.addnstr(row, 0, line, max(1, width - 1), style)
                    except curses.error:
                        pass
                try:
                    screen.addnstr(height - 1, 0, f"q: esci | scorri ↑↓ | righe {self.offset + 1}-{min(self.offset + height - 1, len(lines))}/{len(lines)}", max(1, width - 1))
                except curses.error:
                    pass
                screen.refresh()
            await self.pause(2 if screen is None else 0.25)


async def run(app, screen, headless=False):
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, app.stop.set)
    tasks = [asyncio.create_task(app.run())]
    if not headless:
        tasks.append(asyncio.create_task(app.render(screen)))
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        app.stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-circumference", type=float, default=2.136,
                        help="Metri per giro ruota; default 2.136, ipotesi 700x28C")
    parser.add_argument("--poll-interval", type=float, default=10, help="Pausa tra cicli luci/SRAM in secondi")
    parser.add_argument("--sram-interval", type=float, default=0.5, help="Pausa tra letture SRAM, secondi (default 0.5)")
    parser.add_argument("--raw", action="store_true", help="Mostra anche i pacchetti esadecimali")
    parser.add_argument("--plain", action="store_true", help="Stampa istantanee senza curses")
    parser.add_argument("--headless", action="store_true", help="Solo raccolta e log, senza schermo")
    parser.add_argument("--log", type=Path, help="Percorso JSONL; default data/telemetry-DATA.jsonl")
    args = parser.parse_args()
    if not 0.1 < args.wheel_circumference < 5 or not math.isfinite(args.poll_interval) or args.poll_interval < 1:
        parser.error("Circonferenza tra 0.1 e 5 m; intervallo polling finito e almeno 1 s")
    if not math.isfinite(args.sram_interval) or args.sram_interval < 0.1:
        parser.error("Intervallo SRAM finito e almeno 0.1 s")
    with (Path(__file__).resolve().parent / ".telemetry.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "Telemetria già attiva. Ferma prima l'altra istanza o bike-telemetry.service.\n")
        diagnostic_dir = Path(__file__).resolve().parent / "data"
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        diagnostic_path = diagnostic_dir / datetime.now(timezone.utc).strftime("diagnostics-%Y%m%dT%H%M%S-%fZ.log")
        logging.basicConfig(filename=diagnostic_path, level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")
        logging.getLogger("bike.telemetry").info("Dashboard started; fresh discovery before each connection")
        app = Dashboard(args)
        try:
            if args.headless or args.plain or not sys.stdout.isatty():
                asyncio.run(run(app, None, args.headless))
            else:
                curses.wrapper(lambda screen: asyncio.run(run(app, screen)))
        except KeyboardInterrupt:
            pass
        if hasattr(app, "log_path"):
            print(f"Log salvato: {app.log_path}")


if __name__ == "__main__":
    main()
