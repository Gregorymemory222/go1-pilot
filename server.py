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
from voice import MOVE_SECONDS, VoiceListener, parse_command

PORT = 8765
WEB_DIR = Path(__file__).parent / "web"
STICK_DEADMAN = 1.0   # s bez sygnału z okna -> pies staje
PAGE_TIMEOUT = 120.0  # s bez okna -> serwer się zamyka


class Pilot:
    def __init__(self, client_factory=Go1Client):
        self.client_factory = client_factory
        self.client = None
        self.host = DEFAULT_HOST
        self.status = "Niepołączono"
        self.mode = None
        self.speed = 0.4
        self.axes = [0.0, 0.0, 0.0, 0.0]
        self.voice = VoiceListener(self._on_partial, self._on_voice, self._on_voice_status)
        self.voice_status = "Mikrofon wyłączony"
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
            "mode": self.mode, "speed": self.speed, "axes": self.axes,
            "voice": {"on": self.voice.running, "status": self.voice_status,
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
            self.status, self.mode = "Niepołączono", None
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
        return True

    def set_axes(self, axes):
        with self._lock:
            self._move_token += 1  # ręczne sterowanie anuluje ruch z głosu
            self.axes = [max(-1.0, min(1.0, float(a))) for a in axes]
            if self.client:
                self.client.set_stick(*self.axes)

    def set_speed(self, speed):
        self.speed = max(0.1, min(1.0, float(speed)))

    def set_led(self, r, g, b):
        if self.connected:
            self.client.set_led(int(r), int(g), int(b))

    def timed_move(self, axis, sign, seconds=MOVE_SECONDS):
        self.set_axes([sign * self.speed if i == axis else 0 for i in range(4)])
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
    def set_voice(self, on):
        if on:
            self.voice.start()
        else:
            self.voice.stop()

    def _on_voice_status(self, text):
        self.voice_status = text

    def _on_partial(self, text):
        if text:
            self.heard = text

    def _on_voice(self, text):
        self.heard = text
        found = parse_command(text)
        if not found:
            return
        phrase, action = found
        if action[0] == "stop":
            self.set_axes([0, 0, 0, 0])
        elif not self.connected:
            self.last_command = f"„{phrase}” – najpierw połącz się z psem"
            return
        elif action[0] == "mode":
            self.send_mode(action[1])
        elif action[0] == "move":
            self.timed_move(action[1], action[2])
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
        super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        p = self.pilot
        routes = {
            "/api/connect": lambda: p.connect(body.get("host", "")),
            "/api/disconnect": p.disconnect,
            "/api/mode": lambda: p.send_mode(body["mode"]),
            "/api/axes": lambda: p.set_axes(body["axes"]),
            "/api/speed": lambda: p.set_speed(body["speed"]),
            "/api/led": lambda: p.set_led(body["r"], body["g"], body["b"]),
            "/api/voice": lambda: p.set_voice(bool(body.get("on"))),
        }
        if self.path not in routes:
            return self.send_error(404)
        try:
            result = routes[self.path]()
        except (KeyError, ValueError, TypeError) as e:
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
            subprocess.Popen([exe, f"--app={url}", "--window-size=1180,760"])
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
        while True:
            time.sleep(0.25)
            pilot.check_deadman()
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
