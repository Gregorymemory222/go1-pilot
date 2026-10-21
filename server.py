"""Go1 Pilot – lokalny serwer: okno w przeglądarce <-> pies (MQTT) + komendy głosowe."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from go1_client import DEFAULT_HOST, MODES, Go1Client
from voice import (MOVE_SECONDS, SPIN_SECONDS, TURN, VoiceListener, accept_command, list_microphones,
                   mic_muted, parse_command, unmute_mic)

PORT = 8765
WEB_DIR = Path(__file__).parent / "web"
STICK_DEADMAN = 1.0   # s bez sygnału z okna -> pies staje
PAGE_TIMEOUT = 120.0  # s bez okna -> serwer się zamyka

GAITS = {"walk", "run", "climb"}     # tryby, w których gałki chodzą psem
LYING = {"standDown", "damping"}     # z tych trybów pies nie ruszy, trzeba najpierw wstać
SPEED_STEP_LIMITS = (0.1, 1.0)


class Pilot:
    def __init__(self, client_factory=Go1Client):
        self.client_factory = client_factory
        self.client = None
        self.host = DEFAULT_HOST
        self.status = "Niepołączono"
        self.mode = None
        self.speed = 0.4
        self.axes = [0.0, 0.0, 0.0, 0.0]
        self.notice = ""
        self.voice = VoiceListener(self._on_partial, self._on_voice, self._on_voice_status)
        self.voice_status = "Mikrofon wyłączony"
        self.mic_muted = None
        self.heard = ""
        self.last_command = ""
        self.last_seen = time.monotonic()
        self._move_token = 0
        self._lock = threading.RLock()

    # --- stan dla okna ---
    def state(self):
        self.last_seen = time.monotonic()
        return {
            "host": self.host, "status": self.status, "connected": self.connected,
            "battery": self.client.battery if self.connected else None,
            "mode": self.mode, "speed": self.speed, "axes": self.axes, "notice": self.notice,
            "voice": {"on": self.voice.running, "status": self.voice_status, "level": self.voice.level,
                      "device": self.voice.device, "muted": self.mic_muted,
                      "heard": self.heard, "command": self.last_command},
        }

    @property
    def connected(self):
        return bool(self.client and self.client.connected)

    # --- połączenie ---
    def connect(self, host):
        with self._lock:
            self.disconnect()
            self.host = host.strip() or DEFAULT_HOST
            self.client = self.client_factory(self.host, on_status=self._set_status)
            self.client.connect()

    def disconnect(self):
        with self._lock:
            if self.client:
                self.client.disconnect()
                self.client = None
            self.status, self.mode, self.notice = "Niepołączono", None, ""
            self.axes = [0.0, 0.0, 0.0, 0.0]

    def _set_status(self, text):
        self.status = text

    # --- komendy ---
    def send_mode(self, mode):
        if mode not in MODES:
            raise ValueError(mode)
        if not self.connected:
            return False
        self.set_axes([0, 0, 0, 0])
        self.client.send_mode(mode)
        self.mode = mode
        self.notice = ""
        return True

    def set_axes(self, axes):
        with self._lock:
            self._move_token += 1  # ręczne sterowanie anuluje ruch z głosu
            self.axes = [max(-1.0, min(1.0, float(a))) for a in axes]
            if self.client:
                self.client.set_stick(*self.axes)

    def drive(self, axes):
        """Ruch z klawiatury/głosu: jeśli pies stoi, sam przełącza go w chód."""
        moving = any(axes[i] for i in (0, 1, 3))
        if moving and self.connected and self.mode not in GAITS and self.mode != "stand":
            if self.mode in LYING:
                self.notice = "Pies leży. Najpierw kliknij „Wstań”."
                self.set_axes([0, 0, 0, 0])
                return False
            self.send_mode("walk")
            self.notice = "Przełączyłem psa w tryb „Chód”."
        self.set_axes(axes)
        return True

    def set_speed(self, speed):
        self.speed = round(max(SPEED_STEP_LIMITS[0], min(SPEED_STEP_LIMITS[1], float(speed))), 2)

    def set_led(self, r, g, b):
        if self.connected:
            self.client.set_led(int(r), int(g), int(b))

    def timed_move(self, axis, sign, seconds=MOVE_SECONDS):
        if not self.drive([sign * self.speed if i == axis else 0 for i in range(4)]):
            return
        token = self._move_token
        threading.Timer(seconds, self._end_move, args=(token,)).start()

    def _end_move(self, token):
        with self._lock:
            if token == self._move_token:
                self.set_axes([0, 0, 0, 0])

    def check_deadman(self):
        if any(self.axes) and time.monotonic() - self.last_seen > STICK_DEADMAN:
            self.set_axes([0, 0, 0, 0])

    # --- głos ---
    def set_voice(self, on, device=None):
        if on:
            self.voice.start(device)
        else:
            self.voice.stop()

    def unmute(self):
        unmute_mic()
        self.mic_muted = mic_muted()

    def _on_voice_status(self, text):
        self.voice_status = text

    def _on_partial(self, command, said=""):
        if said or command:
            self.heard = said or command
        found = parse_command(command)
        if found and found[1][0] == "stop" and any(self.axes):
            self.set_axes([0, 0, 0, 0])  # stop nie czeka na koniec zdania

    def _on_voice(self, command, said=None):
        self.heard = said or command
        found = parse_command(command) if said is None else accept_command(command, said)
        if not found:
            return
        phrase, action = found
        kind = action[0]
        if kind == "stop":
            self.set_axes([0, 0, 0, 0])
        elif kind == "speed":
            self.set_speed(self.speed + action[1])
            phrase = f"{phrase} ({round(self.speed * 100)}%)"
        elif not self.connected:
            self.last_command = f"„{phrase}”, ale najpierw połącz się z psem"
            return
        elif kind == "mode":
            self.send_mode(action[1])
        elif kind == "move":
            self.timed_move(action[1], action[2])
        elif kind == "spin":
            self.timed_move(TURN, +1, SPIN_SECONDS)
        self.last_command = phrase


class Handler(SimpleHTTPRequestHandler):
    pilot: Pilot = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/state":
            return self._json(self.pilot.state())
        if self.path == "/api/mics":
            try:
                return self._json(list_microphones())
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        p = self.pilot
        routes = {
            "/api/connect": lambda: p.connect(body.get("host", "")),
            "/api/disconnect": p.disconnect,
            "/api/mode": lambda: p.send_mode(body["mode"]),
            "/api/axes": lambda: p.drive(body["axes"]),
            "/api/speed": lambda: p.set_speed(body["speed"]),
            "/api/led": lambda: p.set_led(body["r"], body["g"], body["b"]),
            "/api/voice": lambda: p.set_voice(bool(body.get("on")), body.get("device")),
            "/api/unmute": p.unmute,
        }
        if self.path not in routes:
            return self.send_error(404)
        try:
            result = routes[self.path]()
        except (KeyError, ValueError, TypeError, OSError) as e:
            return self._json({"error": str(e)}, 400)
        self._json({"ok": result is not False, "state": p.state()})

    def _json(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def open_window(url):
    candidates = [
        shutil.which("chrome"),
        *(os.path.join(os.environ.get(v, ""), r"Google\Chrome\Application\chrome.exe")
          for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")),
        *(os.path.join(os.environ.get(v, ""), r"Microsoft\Edge\Application\msedge.exe")
          for v in ("PROGRAMFILES(X86)", "PROGRAMFILES")),
    ]
    for exe in candidates:
        if exe and os.path.isfile(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1180,800"])
            return
    webbrowser.open(url)


def main():
    url = f"http://127.0.0.1:{PORT}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:  # już działa – tylko otwórz okno
        open_window(url)
        return
    pilot = Handler.pilot = Pilot()

    def watchdog():
        ticks = 0
        while True:
            time.sleep(0.25)
            pilot.check_deadman()
            if ticks % 4 == 0:
                pilot.mic_muted = mic_muted()
            ticks += 1
            if time.monotonic() - pilot.last_seen > PAGE_TIMEOUT:
                pilot.voice.stop()
                pilot.disconnect()
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    if "--no-window" not in sys.argv:
        open_window(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
