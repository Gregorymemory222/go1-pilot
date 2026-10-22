"""Podgląd kamer Go1: SSH do Raspberry Pi psa -> SSH do komputera kamer (Jetson) -> go1cam.py.

Kamery są przypięte do komputerów Jetson w sieci wewnętrznej psa (192.168.123.x), do której laptop
w Wi-Fi psa (192.168.12.x) nie sięga bezpośrednio – dlatego idziemy tunelem przez Raspberry Pi.
Domyślne loginy (pi/123, unitree/123) za MAVProxyUser/YushuTechUnitreeGo1.

Fabryczne programy psa (omijanie przeszkód, śledzenie ludzi) trzymają kamery, więc przed podglądem
je zatrzymujemy – wracają po restarcie psa.

Każda włączona kamera to osobny go1cam.py w psie (port 8091 + numer kamery) i osobny wątek tutaj,
który czyta klatki i trzyma ostatnią – z niej korzysta podgląd, siatka, zdjęcia i nagrywanie.
"""
import queue
import shlex
import threading
import time
from pathlib import Path

from media import MjpegParser

REMOTE_SCRIPT = "/tmp/go1cam.py"
BASE_PORT = 8091
# procesy, które zajmują kamery (za roboticsknowledgebase.com, Unitree Go1)
CAMERA_HOGS = ("point_cloud_node", "mqttControlNode", "live_human_pose", "putImagetrans")

# Która kamera jest gdzie – do potwierdzenia na prawdziwym psie (stąd neutralne nazwy).
CAMERAS = [
    {"label": "Głowa – kamera 1", "host": "192.168.123.13", "device": 0},
    {"label": "Głowa – kamera 2", "host": "192.168.123.13", "device": 1},
    {"label": "Tułów A – kamera 1", "host": "192.168.123.14", "device": 0},
    {"label": "Tułów A – kamera 2", "host": "192.168.123.14", "device": 1},
    {"label": "Tułów B – kamera 1", "host": "192.168.123.15", "device": 0},
]
QUALITY = {"low": (480, 60), "medium": (640, 70), "high": (928, 80)}
GRID_FPS = 8  # w siatce wszystkie kamery idą jednym Wi-Fi, więc mniej klatek


class Stream:
    """Jedna włączona kamera: stan, ostatnia klatka i wątek czytający ją z psa."""

    def __init__(self, index, fps=30):
        self.index = index
        self.fps = fps
        self.state = "starting"  # starting / on / error
        self.text = "uruchamiam…"
        self.jpeg = None
        self.frame_id = 0
        self.channel = None
        self.cond = threading.Condition()

    def put(self, jpeg):
        with self.cond:
            self.jpeg = jpeg
            self.frame_id += 1
            self.cond.notify_all()

    def wait(self, last_id, timeout=2.0):
        with self.cond:
            self.cond.wait_for(lambda: self.frame_id != last_id or self.state != "on", timeout)
            if self.frame_id == last_id or self.jpeg is None:
                return None
            return self.frame_id, self.jpeg


class CameraLink:
    def __init__(self, settings, on_event=lambda text: None):
        self.settings = settings
        self.on_event = on_event
        self.status = "Kamera wyłączona"
        self.streams = {}  # numer kamery -> Stream
        # po zatrzymaniu fabrycznych programów pies nie omija przeszkód aż do restartu – pokazujemy to w oknie
        self.obstacle_avoidance_off = False
        self._pi = None
        self._jetsons = {}  # adres Jetsona -> SSHClient
        self._prepared = set()  # Jetsony z zatrzymanymi programami i wgranym go1cam.py
        self._lock = threading.RLock()
        self._jobs = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    # --- publiczne ---
    @property
    def busy(self):
        return any(s.state == "starting" for s in list(self.streams.values()))

    def running(self, index):
        stream = self.streams.get(index)
        return stream is not None and stream.state == "on"

    def start(self, host, indices, fps=30):
        for index in indices:
            current = self.streams.get(index)
            if current and current.state != "error" and current.fps >= fps:
                continue  # już działa co najmniej tak płynnie
            if current:  # np. po siatce: z oszczędnych 8 kl./s z powrotem do pełnej jakości
                self._close_channel(current)
            self.streams[index] = Stream(index, fps)
            self._jobs.put((self._start_one, (host, index, fps)))

    def stop(self, indices=None):
        for index in list(self.streams) if indices is None else indices:
            stream = self.streams.pop(index, None)
            if stream:
                self._close_channel(stream)
                self._jobs.put((self._stop_one, (index,)))
        self._jobs.put((self._close_if_idle, ()))

    def wait_frame(self, index, last_id=0, timeout=2.0):
        stream = self.streams.get(index)
        return stream.wait(last_id, timeout) if stream else None

    def latest(self, index):
        stream = self.streams.get(index)
        return stream.jpeg if stream and stream.state == "on" else None

    def describe(self):
        return {i: {"state": s.state, "text": s.text} for i, s in list(self.streams.items())}

    # --- praca w tle (SSH po kolei, jedno zadanie naraz) ---
    def _worker(self):
        while True:
            job, args = self._jobs.get()
            try:
                job(*args)
            except Exception as e:  # zadanie samo raportuje błąd; to tylko siatka bezpieczeństwa
                self._set(f"błąd – {_explain(e)}")

    def _set(self, text):
        self.status = text
        self.on_event(f"Kamera: {text}")

    def _start_one(self, host, index, fps):
        stream = self.streams.get(index)
        if stream is None:  # wyłączona, zanim przyszła jej kolej
            return
        cam = CAMERAS[index]
        port = BASE_PORT + index
        try:
            jetson = self._jetson(host, cam["host"])
            if cam["host"] not in self._prepared:
                self._set(f"zwalniam kamery na {cam['host']} (wyłączam omijanie przeszkód)…")
                password = shlex.quote(self.settings["jetson_password"])
                # wzorzec „[p]oint…” nie pasuje do samej tej komendy, więc pkill nie zabije własnej powłoki
                patterns = " ".join(_pattern(p) for p in CAMERA_HOGS)
                self.obstacle_avoidance_off = True
                _run(jetson, f"for p in {patterns}; do echo {password} | sudo -S pkill -f \"$p\"; done; sleep 1")
                sftp = jetson.open_sftp()
                sftp.put(str(Path(__file__).parent / "go1cam.py"), REMOTE_SCRIPT)
                sftp.close()
                self._prepared.add(cam["host"])

            width, quality = QUALITY.get(self.settings["camera_quality"], QUALITY["medium"])
            if fps < 30:
                width, quality = QUALITY["low"]
            log = f"/tmp/go1cam_{port}.log"
            self._set(f"uruchamiam {cam['label']}…")
            # osobno: gdyby pkill był w jednej komendzie z „python3 …go1cam.py --port”, zabiłby własną powłokę
            _run(jetson, f"pkill -f {_pattern('go1cam.py')}'.*--port {port}'")
            # zwalniamy samo urządzenie – działa też na fabryczne programy, których nie znamy z nazwy
            password = shlex.quote(self.settings["jetson_password"])
            _run(jetson, f"echo {password} | sudo -S fuser -k /dev/video{cam['device']}; sleep 0.5")
            _run(jetson, f"nohup python3 {REMOTE_SCRIPT} --device {cam['device']} --port {port} "
                         f"--width {width} --quality {quality} --fps {fps} > {log} 2>&1 &")
            _wait_ready(jetson, log)
            channel = jetson.get_transport().open_channel(
                "direct-tcpip", ("127.0.0.1", port), ("127.0.0.1", 0), timeout=5)
            if self.streams.get(index) is not stream:  # wyłączona w międzyczasie
                channel.close()
                return
            stream.channel = channel
            stream.state, stream.text = "on", "działa"
            threading.Thread(target=self._read, args=(stream,), daemon=True).start()
            self._set(f"działa ({cam['label']})")
        except Exception as e:
            stream.state, stream.text = "error", _explain(e)
            self._set(f"błąd ({cam['label']}) – {stream.text}")

    def _read(self, stream):
        parser = MjpegParser()
        try:
            while True:
                data = stream.channel.recv(65536)
                if not data:
                    break
                for jpeg in parser.feed(data):
                    stream.put(jpeg)
        except Exception:
            pass
        if self.streams.get(stream.index) is stream:  # nie wyłączyliśmy jej sami – połączenie padło
            stream.state, stream.text = "error", "połączenie zerwane – włącz ponownie"
            with stream.cond:
                stream.cond.notify_all()
            self._set(f"{CAMERAS[stream.index]['label']}: połączenie zerwane")

    def _stop_one(self, index):
        cam = CAMERAS[index]
        jetson = self._jetsons.get(cam["host"])
        if jetson:
            try:
                _run(jetson, f"pkill -f {_pattern('go1cam.py')}'.*--port {BASE_PORT + index}'")
            except Exception:
                pass

    def _close_if_idle(self):
        if self.streams:
            return
        with self._lock:
            for client in (*self._jetsons.values(), self._pi):
                if client:
                    client.close()
            self._jetsons.clear()
            self._pi = None
            self._prepared.clear()
        self._set("Kamera wyłączona")

    @staticmethod
    def _close_channel(stream):
        if stream.channel:
            try:
                stream.channel.close()
            except Exception:
                pass

    def _jetson(self, host, jetson_host):
        with self._lock:
            client = self._jetsons.get(jetson_host)
            if client and _alive(client):
                return client
            if not (self._pi and _alive(self._pi)):
                self._set("łączę się z Raspberry Pi psa…")
                self._pi = self._ssh(host, self.settings["pi_user"], self.settings["pi_password"])
                self._jetsons.clear()
                self._prepared.clear()
            self._set(f"łączę się z komputerem kamer {jetson_host}…")
            hop = self._pi.get_transport().open_channel(
                "direct-tcpip", (jetson_host, 22), ("127.0.0.1", 0), timeout=5)
            client = self._ssh(jetson_host, self.settings["jetson_user"], self.settings["jetson_password"], sock=hop)
            self._jetsons[jetson_host] = client
            return client

    def _ssh(self, host, user, password, sock=None):
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, sock=sock, timeout=6,
                       banner_timeout=10, auth_timeout=10, allow_agent=False, look_for_keys=False)
        client.get_transport().set_keepalive(10)  # podtrzymuje tunel, gdy obraz akurat nie płynie
        return client


def _alive(client):
    transport = client.get_transport()
    return transport is not None and transport.is_active()


def _run(client, command):
    _, out, err = client.exec_command(command, timeout=15)
    return out.read().decode(errors="replace") + err.read().decode(errors="replace")


def _wait_ready(client, log, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = log_state(_run(client, f"cat {log} 2>/dev/null"))
        if state == "ready":
            return
        if state:
            raise RuntimeError(state)
        time.sleep(0.5)
    raise RuntimeError(f"serwer obrazu w psie nie wystartował (sprawdź {log})")


def log_state(text):
    """'ready', opis błędu albo None (jeszcze startuje). Ostrzeżenia GStreamera w logu to nie błąd."""
    lines = text.splitlines()
    for line in lines:
        if line.startswith("GO1CAM-READY"):
            return "ready"
        if line.startswith("GO1CAM-ERROR "):
            return line[len("GO1CAM-ERROR "):]
    if any(line.startswith("Traceback") for line in lines):
        return next((ln for ln in reversed(lines) if ln.strip()), "błąd programu kamery")
    return None


def _pattern(name):
    return f"'[{name[0]}]{name[1:]}'"


def _explain(error):
    text = str(error) or type(error).__name__
    name = type(error).__name__
    if name == "AuthenticationException":
        return "zły login lub hasło (zmień w Ustawieniach)"
    if name in ("NoValidConnectionsError", "TimeoutError", "timeout") or "timed out" in text:
        return "brak połączenia – czy laptop jest w Wi-Fi psa?"
    if name == "ChannelException":
        return "Raspberry Pi nie przepuszcza połączenia do komputera kamer"
    return text
