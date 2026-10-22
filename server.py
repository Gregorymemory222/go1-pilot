"""Go1 Pilot – lokalny serwer: okno w przeglądarce <-> pies (MQTT) + głos + kamera."""
import collections
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import program
import settings as settings_store
from camera import CAMERAS, GRID_FPS, CameraLink
from go1_client import MODES, Go1Client
from media import AviWriter, jpeg_size
from voice import STRICTNESS, VoiceListener, accept_command, list_microphones, mic_muted, parse_command, unmute_mic

PORT = 8765
WEB_DIR = Path(__file__).parent / "web"
STICK_DEADMAN = 1.0   # s bez sygnału z okna -> pies staje
PAGE_TIMEOUT = 120.0  # s bez okna -> serwer się zamyka
MAX_RECORDING = 15 * 60  # s – dłuższe nagranie samo się kończy (pliki MJPEG są duże)
APP_DIR = Path(__file__).resolve().parent
PROGRAMS_DIR = APP_DIR / "programy"
# tryb lekcji: wolniej, krócej, bez biegu
LESSON_MAX_SPEED = 0.3
LESSON_MAX_SECONDS = 3.0
LESSON_BLOCKED = ("run",)
MAX_STEP_SECONDS = 8.0  # najdłuższy pojedynczy ruch z polecenia poza trybem lekcji

GAITS = {"walk", "run", "climb"}     # tryby, w których gałki chodzą psem
LYING = {"standDown", "damping"}     # z tych trybów pies nie ruszy, trzeba najpierw wstać
MODE_NAMES = {
    "standUp": "Wstań", "standDown": "Połóż się", "recoverStand": "Podnieś po upadku", "stand": "Poza",
    "walk": "Chód", "run": "Bieg", "climb": "Wspinaczka", "dance1": "Taniec 1", "dance2": "Taniec 2",
    "straightHand1": "Podaj łapę", "jumpYaw": "Skok z obrotem", "damping": "Zwiotcz silniki",
}


class Pilot:
    def __init__(self, client_factory=Go1Client, settings=None, save=settings_store.save, media_dir=Path.home()):
        self.settings = settings or settings_store.load()
        self._save = save
        self.client_factory = client_factory
        self.client = None
        self.host = self.settings["host"]
        self.status = "Niepołączono"
        self.mode = None
        self.speed = self.settings["start_speed"]
        self.axes = [0.0, 0.0, 0.0, 0.0]
        self.notice = ""
        self.log = collections.deque(maxlen=40)
        self.voice = VoiceListener(self._on_partial, self._on_voice, self._on_voice_status)
        self.voice_status = "Mikrofon wyłączony"
        self.mic_muted = None
        self.heard = ""
        self.last_command = ""
        self.voice_seq = 0          # rośnie przy każdej komendzie głosowej – okno wtedy piszczy
        self.voice_result = ""      # ok / rejected / offline
        self.voice.push_to_talk = self.settings["mic_mode"] == "ptt"
        self.camera = CameraLink(self.settings, on_event=self.event)
        self.grid = False
        self.recording = None  # {"path", "start", "stop"} gdy trwa nagrywanie
        self.saved = ""
        self.photo_dir = media_dir / "Pictures" / "Go1 Pilot"
        self.video_dir = media_dir / "Videos" / "Go1 Pilot"
        self.program = None   # ostatni program: kroki, kod w Pythonie, który krok trwa
        self.saved_program = ""
        self.last_seen = time.monotonic()
        self._move_token = 0
        self._lock = threading.RLock()

    def event(self, text):
        if not self.log or self.log[-1][1] != text:
            self.log.append((time.strftime("%H:%M:%S"), text))

    # --- stan dla okna ---
    def state(self):
        self.last_seen = time.monotonic()
        return {
            "host": self.host, "status": self.status, "connected": self.connected,
            "battery": self.client.battery if self.connected else None,
            "mode": self.mode, "speed": self.speed, "axes": self.axes, "notice": self.notice,
            "voice": {"on": self.voice.running, "status": self.voice_status, "level": self.voice.level,
                      "device": self.voice.device, "muted": self.mic_muted,
                      "heard": self.heard, "command": self.last_command,
                      "seq": self.voice_seq, "result": self.voice_result, "talking": self.voice.talking},
            "camera": {
                "status": self.camera.status, "busy": self.camera.busy, "main": self.main_camera,
                "on": self.main_camera in self.camera.streams, "grid": self.grid,
                "streams": self.camera.describe(), "cameras": [c["label"] for c in CAMERAS],
                "recording": None if not self.recording else {
                    "seconds": round(time.monotonic() - self.recording["start"]),
                    "file": self.recording["path"].name},
                "saved": self.saved,
            },
            "program": self.program_view(), "saved_program": self.saved_program,
            "max_speed": self.max_speed,
            "obstacle_off": self.camera.obstacle_avoidance_off,
            "settings": {k: v for k, v in self.settings.items() if not k.endswith("password")},
            "log": list(self.log)[-12:],
        }

    @property
    def connected(self):
        return bool(self.client and self.client.connected)

    # --- ustawienia ---
    def update_settings(self, changes):
        merged = dict(self.settings)
        merged.update({k: v for k, v in changes.items() if not (k.endswith("password") and v == "")})
        self.settings.update(settings_store.clean(merged))  # ten sam obiekt widzi też kamera
        self._save(self.settings)
        self.set_speed(self.speed)
        self.voice.push_to_talk = self.settings["mic_mode"] == "ptt"
        if self.voice.running:
            self.voice_status = self.voice._ready_text()
        self.event("Zapisano ustawienia")

    # --- połączenie ---
    def connect(self, host):
        with self._lock:
            self.disconnect()
            self.host = host.strip() or self.settings["host"]
            if self.host != self.settings["host"]:
                self.update_settings({"host": self.host})
            self.client = self.client_factory(self.host, on_status=self._set_status)
            self.client.connect()

    def disconnect(self):
        with self._lock:
            if self.client:
                self.client.disconnect()
                self.client = None
                self.event("Rozłączono")
            self.status, self.mode, self.notice = "Niepołączono", None, ""
            self.axes = [0.0, 0.0, 0.0, 0.0]

    def _set_status(self, text):
        self.status = text
        self.event(text)

    # --- komendy ---
    def send_mode(self, mode):
        if mode not in MODES:
            raise ValueError(mode)
        if not self.connected:
            return False
        if self.settings["lesson_mode"] and mode in LESSON_BLOCKED:
            self._notice(f"„{MODE_NAMES[mode]}” jest wyłączony w trybie lekcji.")
            return False
        self.set_axes([0, 0, 0, 0])
        self.client.send_mode(mode)
        self.mode = mode
        self.notice = ""
        self.event(f"Komenda: {MODE_NAMES[mode]}")
        return True

    def set_axes(self, axes):
        with self._lock:
            self._move_token += 1  # ręczne sterowanie anuluje ruch z głosu
            self.axes = [max(-1.0, min(1.0, float(a))) for a in axes]
            if self.client:
                self.client.set_stick(*self.axes)

    def drive(self, axes):
        """Ruch z klawiatury/głosu: jeśli pies stoi, sam przełącza go w chód."""
        limit = self.max_speed  # limit pilnuje serwer, nie tylko suwak w oknie
        axes = [max(-limit, min(limit, float(a))) if i != 2 else float(a) for i, a in enumerate(axes)]
        moving = any(axes[i] for i in (0, 1, 3))
        if moving and self.program and self.program["running"]:
            self.stop_program(zero=False)  # ręczne sterowanie przerywa program
        if moving and self.connected and self.mode not in GAITS and self.mode != "stand":
            if self.mode in LYING:
                self._notice("Pies leży. Najpierw kliknij „Wstań”.")
                self.set_axes([0, 0, 0, 0])
                return False
            if self.settings["auto_walk"]:
                self.send_mode("walk")
                self._notice("Przełączyłem psa w tryb „Chód”.")
        self.set_axes(axes)
        return True

    def _notice(self, text):
        self.notice = text
        self.event(text)

    def set_speed(self, speed):
        self.speed = round(max(0.1, min(self.max_speed, float(speed))), 2)

    def set_led(self, r, g, b):
        if self.connected:
            self.client.set_led(int(r), int(g), int(b))

    @property
    def max_speed(self):
        if self.settings["lesson_mode"]:
            return min(self.settings["max_speed"], LESSON_MAX_SPEED)
        return self.settings["max_speed"]

    # --- programy: polecenie tekstowe/głosowe -> kroki -> kod w Pythonie ---
    def run_program(self, text, source="tekst"):
        """Zamienia polecenie na kroki i kod w Pythonie, a potem wykonuje te same kroki."""
        lesson = self.settings["lesson_mode"]
        steps, errors = program.parse(
            text, speed=self.speed, max_speed=self.max_speed,
            move_seconds=self.settings["move_seconds"], spin_seconds=self.settings["spin_seconds"],
            max_seconds=LESSON_MAX_SECONDS if lesson else MAX_STEP_SECONDS,
            start_mode=self.mode, auto_walk=self.settings["auto_walk"],
            blocked_modes=LESSON_BLOCKED if lesson else ())
        code, ranges = program.to_python(steps, self.host, text, app_dir=str(APP_DIR))
        self.stop_program(zero=False)
        if not steps and not errors:
            errors = ["Wpisz polecenie, na przykład „wstań, potem do przodu 2 sekundy”"]
        if not errors and not self.connected:
            errors = ["Najpierw połącz się z psem – kod możesz już obejrzeć."]
        cancel = threading.Event()
        self.program = {"source": source, "text": text, "steps": [s["label"] for s in steps], "ranges": ranges,
                        "code": code, "errors": errors, "current": None, "running": not errors,
                        "seq": (self.program or {}).get("seq", 0) + 1, "cancel": cancel}
        self.event(f"Program ({source}): {text}" + (f" – {errors[0]}" if errors else ""))
        if errors:
            return False
        threading.Thread(target=self._run_steps, args=(self.program, steps), daemon=True).start()
        return True

    def stop_program(self, zero=True):
        prog = self.program
        if prog and prog["running"]:
            prog["cancel"].set()
            prog["running"] = False
            prog["current"] = None
            self.event("Program zatrzymany")
        if zero:
            self.set_axes([0, 0, 0, 0])

    def _run_steps(self, prog, steps):
        cancel = prog["cancel"]
        for i, step in enumerate(steps):
            if cancel.is_set() or not self.connected:
                break
            prog["current"] = i
            kind = step["kind"]
            if kind == "mode":
                self.send_mode(step["mode"])
                cancel.wait(step["wait"])
            elif kind == "move":
                self.set_axes(step["axes"])
                cancel.wait(step["seconds"])
                if not cancel.is_set():
                    self.set_axes([0, 0, 0, 0])
            elif kind == "wait":
                cancel.wait(step["seconds"])
            elif kind == "stop":
                self.set_axes([0, 0, 0, 0])
        if self.program is prog and not cancel.is_set():
            prog["running"] = False
            prog["current"] = None

    def program_view(self):
        if not self.program:
            return None
        return {k: v for k, v in self.program.items() if k != "cancel"}

    def save_program(self):
        if not self.program:
            raise ValueError("najpierw wpisz polecenie")
        PROGRAMS_DIR.mkdir(exist_ok=True)
        path = PROGRAMS_DIR / time.strftime("program_%Y-%m-%d_%H-%M-%S.py")
        path.write_text(self.program["code"], encoding="utf-8")
        self.saved_program = str(path)
        self.event(f"Zapisano program {path.name}")
        os.startfile(PROGRAMS_DIR)

    def check_deadman(self):
        if any(self.axes) and time.monotonic() - self.last_seen > STICK_DEADMAN:
            self.stop_program()  # okno zniknęło – pies staje, program się kończy

    # --- kamera ---
    @property
    def main_camera(self):
        return self.settings["camera_index"]

    def set_camera(self, on, index=None):
        """Główny podgląd: jedna kamera (poza siatką pozostałe są wyłączane, żeby nie zapychać Wi-Fi)."""
        if not on:
            self.set_recording(False)
            self.grid = False
            self.camera.stop()
            return
        index = self.main_camera if index is None else max(0, min(len(CAMERAS) - 1, int(index)))
        if index != self.main_camera:
            self.set_recording(False)
            self.update_settings({"camera_index": index})
        if not self.grid:
            self.camera.stop([i for i in self.camera.streams if i != index])
        self.camera.start(self.host, [index])

    def set_grid(self, on, main=None):
        self.grid = bool(on)
        if self.grid:
            self.camera.start(self.host, range(len(CAMERAS)), fps=GRID_FPS)
        else:
            self.set_camera(True, main)

    def snapshot(self):
        jpeg = self.camera.latest(self.main_camera)
        if jpeg is None:
            raise ValueError("kamera nie pokazuje obrazu")
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        path = self.photo_dir / time.strftime("go1_%Y-%m-%d_%H-%M-%S.jpg")
        path.write_bytes(jpeg)
        self.saved = f"Zapisano zdjęcie {path.name}"
        self.event(self.saved)

    def set_recording(self, on):
        if not on:
            if self.recording:
                self.recording["stop"].set()
            return
        if self.recording:
            return
        if self.camera.latest(self.main_camera) is None:
            raise ValueError("kamera nie pokazuje obrazu")
        self.video_dir.mkdir(parents=True, exist_ok=True)
        path = self.video_dir / time.strftime("go1_%Y-%m-%d_%H-%M-%S.avi")
        self.recording = {"path": path, "start": time.monotonic(), "stop": threading.Event()}
        threading.Thread(target=self._record, args=(self.recording, self.main_camera), daemon=True).start()
        self.event(f"Nagrywam do {path.name}")

    def _record(self, rec, index):
        writer, frames, last = None, 0, 0
        try:
            while not rec["stop"].is_set() and time.monotonic() - rec["start"] < MAX_RECORDING:
                got = self.camera.wait_frame(index, last, timeout=1.0)
                if got is None:
                    if not self.camera.running(index):
                        break
                    continue
                last, jpeg = got
                if writer is None:
                    size = jpeg_size(jpeg) or (640, 480)
                    writer = AviWriter(rec["path"], *size)
                writer.add(jpeg)
                frames += 1
        finally:
            seconds = time.monotonic() - rec["start"]
            if writer:
                writer.close(fps=frames / max(seconds, 0.1))
                self.saved = f"Zapisano nagranie {rec['path'].name} ({round(seconds)} s)"
            else:
                self.saved = "Nagranie puste – kamera nie dała obrazu"
            self.event(self.saved)
            if self.recording is rec:
                self.recording = None

    def open_folder(self, kind):
        folder = self.video_dir if kind == "videos" else self.photo_dir
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    # --- głos ---
    def set_voice(self, on, device=None):
        if on:
            self.voice.start(device)
            if device != self.settings["mic_device"]:
                self.update_settings({"mic_device": device})
        else:
            self.voice.stop()

    def set_talking(self, down):
        self.voice.talking = bool(down)

    def unmute(self):
        unmute_mic()
        self.mic_muted = mic_muted()
        self.event("Włączono mikrofon w Windows")

    def _on_voice_status(self, text):
        self.voice_status = text

    def _on_partial(self, command, said=""):
        if said or command:
            self.heard = said or command
        found = parse_command(command)
        if found and found[1][0] == "stop" and (any(self.axes) or (self.program and self.program["running"])):
            self.stop_program()  # stop nie czeka na koniec zdania

    def _on_voice(self, command, said=None):
        self.heard = said or command
        if said is None:
            found = parse_command(command)
        else:
            found = accept_command(command, said, STRICTNESS[self.settings["voice_strictness"]])
            if not found and parse_command(command):
                self.event(f"Głos: pominięto „{said}” (to nie wyglądało na komendę)")
                self._voice_done("rejected")
        if not found:
            return
        phrase, action = found
        kind = action[0]
        if kind == "stop":
            self.stop_program()
        elif kind == "speed":
            self.set_speed(self.speed + action[1])
            phrase = f"{phrase} ({round(self.speed * 100)}%)"
        elif not self.connected:
            self.last_command = f"„{phrase}”, ale najpierw połącz się z psem"
            self._voice_done("offline")
            return
        elif not self.run_program(command, source="głos"):  # ta sama droga co polecenia tekstowe
            self.last_command = f"„{phrase}” – {self.program['errors'][0]}"
            self._voice_done("rejected")
            return
        self.last_command = phrase
        self.event(f"Głos: {phrase}")
        self._voice_done("ok")

    def _voice_done(self, result):
        self.voice_result = result
        self.voice_seq += 1


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
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/api/state":
            return self._json(self.pilot.state())
        if url.path == "/api/mics":
            try:
                return self._json(list_microphones())
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        if url.path in ("/camera.mjpg", "/camera.jpg"):
            query = urllib.parse.parse_qs(url.query)
            try:
                index = int(query.get("cam", [self.pilot.main_camera])[0])
            except ValueError:
                return self.send_error(400)
            return self._camera_stream(index) if url.path == "/camera.mjpg" else self._camera_frame(index)
        super().do_GET()

    def _camera_frame(self, index):
        """Jedna klatka – siatka kamer pobiera je po kolei (strumienie zajęłyby limit połączeń przeglądarki)."""
        jpeg = self.pilot.camera.latest(index)
        if jpeg is None:
            return self.send_error(503, "Camera off")  # linia statusu HTTP musi być w latin-1
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _camera_stream(self, index):
        first = self.pilot.camera.wait_frame(index, 0, timeout=5)
        if first is None:
            return self.send_error(503, "Camera off")
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        frame = first
        try:
            while frame is not None:
                last, jpeg = frame
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                 str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                frame = self.pilot.camera.wait_frame(index, last, timeout=5)
        except OSError:
            pass  # okno zamknęło podgląd

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:  # też złe kodowanie znaków – odpowiadamy błędem zamiast zrywać połączenie
            return self._json({"error": "niepoprawne dane (wymagany JSON w UTF-8)"}, 400)
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
            "/api/ptt": lambda: p.set_talking(body.get("down")),
            "/api/program/run": lambda: p.run_program(str(body.get("text", ""))),
            "/api/program/stop": p.stop_program,
            "/api/program/save": p.save_program,
            "/api/camera": lambda: p.set_camera(bool(body.get("on")), body.get("index")),
            "/api/camera/grid": lambda: p.set_grid(bool(body.get("on")), body.get("main")),
            "/api/camera/photo": p.snapshot,
            "/api/camera/record": lambda: p.set_recording(bool(body.get("on"))),
            "/api/open-folder": lambda: p.open_folder(body.get("kind")),
            "/api/settings": lambda: p.update_settings(body),
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


class AppServer(ThreadingHTTPServer):
    """Port na wyłączność. Domyślny SO_REUSEADDR na Windows pozwala drugiemu uruchomieniu zająć ten sam
    port – wtedy kliknięcia trafiają losowo do dwóch serwerów, z których tylko jeden jest połączony z psem."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


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
            subprocess.Popen([exe, f"--app={url}", "--window-size=1280,860"])
            return
    webbrowser.open(url)


def main():
    url = f"http://127.0.0.1:{PORT}/"
    try:
        server = AppServer(("127.0.0.1", PORT), Handler)
    except OSError:  # już działa – tylko otwórz okno
        open_window(url)
        return
    pilot = Handler.pilot = Pilot()
    if pilot.settings["auto_connect"]:
        pilot.connect(pilot.settings["host"])

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
                pilot.set_camera(False)  # kończy też nagrywanie…
                for _ in range(30):      # …i czekamy, aż plik zostanie domknięty
                    if pilot.recording is None:
                        break
                    time.sleep(0.1)
                pilot.disconnect()
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    if "--no-window" not in sys.argv:
        open_window(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
