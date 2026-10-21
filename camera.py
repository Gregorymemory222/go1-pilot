"""Podgląd kamer Go1: SSH do Raspberry Pi psa -> SSH do komputera kamer (Jetson) -> go1cam.py.

Kamery są przypięte do komputerów Jetson w sieci wewnętrznej psa (192.168.123.x), do której laptop
w Wi-Fi psa (192.168.12.x) nie sięga bezpośrednio – dlatego idziemy tunelem przez Raspberry Pi.
Domyślne loginy (pi/123, unitree/123) za MAVProxyUser/YushuTechUnitreeGo1.

Fabryczne programy psa (omijanie przeszkód, śledzenie ludzi) trzymają kamery, więc przed podglądem
je zatrzymujemy – wracają po restarcie psa.
"""
import shlex
import threading
import time
from pathlib import Path

REMOTE_SCRIPT = "/tmp/go1cam.py"
REMOTE_LOG = "/tmp/go1cam.log"
REMOTE_PORT = 8091
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


class CameraLink:
    def __init__(self, settings, on_event=lambda text: None):
        self.settings = settings
        self.on_event = on_event
        self.status = "Kamera wyłączona"
        self.active = None  # indeks z CAMERAS, gdy podgląd działa
        self.busy = False
        self._pi = self._jetson = None
        self._lock = threading.Lock()

    # --- publiczne ---
    def start(self, host, index):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._start, args=(host, index), daemon=True).start()

    def stop(self):
        threading.Thread(target=self._stop, daemon=True).start()

    def open_stream(self):
        """Kanał TCP do serwera obrazu w psie (strumień MJPEG razem z nagłówkami HTTP)."""
        with self._lock:
            if self._jetson is None or self.active is None:
                return None
            transport = self._jetson.get_transport()
            if transport is None or not transport.is_active():
                lost = True
            else:
                try:
                    return transport.open_channel(
                        "direct-tcpip", ("127.0.0.1", REMOTE_PORT), ("127.0.0.1", 0), timeout=5)
                except Exception:
                    lost = True
        if lost:
            self._close()
            self._set("połączenie z kamerą zerwane – włącz ją ponownie")
        return None

    # --- wewnętrzne ---
    def _set(self, text):
        self.status = text
        self.on_event(f"Kamera: {text}")

    def _start(self, host, index):
        try:
            cam = CAMERAS[index]
            self._close()
            self._set("łączę się z Raspberry Pi psa…")
            pi = self._ssh(host, self.settings["pi_user"], self.settings["pi_password"])
            self._set(f"łączę się z komputerem kamer {cam['host']}…")
            hop = pi.get_transport().open_channel("direct-tcpip", (cam["host"], 22), ("127.0.0.1", 0), timeout=5)
            jetson = self._ssh(cam["host"], self.settings["jetson_user"], self.settings["jetson_password"], sock=hop)
            with self._lock:
                self._pi, self._jetson = pi, jetson

            self._set("zwalniam kamery (wyłączam omijanie przeszkód)…")
            password = shlex.quote(self.settings["jetson_password"])
            # wzorzec „[p]oint…” nie pasuje do samej tej komendy, więc pkill nie zabije własnej powłoki
            patterns = " ".join(_pattern(p) for p in (*CAMERA_HOGS, "go1cam.py"))
            self._run(f"for p in {patterns}; do echo {password} | sudo -S pkill -f \"$p\"; done; sleep 1")

            sftp = jetson.open_sftp()
            sftp.put(str(Path(__file__).parent / "go1cam.py"), REMOTE_SCRIPT)
            sftp.close()
            width, quality = QUALITY.get(self.settings["camera_quality"], QUALITY["medium"])
            self._set("uruchamiam podgląd…")
            self._run(f"nohup python3 {REMOTE_SCRIPT} --device {cam['device']} --port {REMOTE_PORT} "
                      f"--width {width} --quality {quality} > {REMOTE_LOG} 2>&1 &")
            self._wait_ready()
            self.active = index
            self._set(f"działa ({cam['label']})")
        except Exception as e:
            self._close()
            self._set(f"błąd – {_explain(e)}")
        finally:
            self.busy = False

    def _wait_ready(self, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            log = self._run(f"cat {REMOTE_LOG} 2>/dev/null").strip()
            if "ready" in log:
                return
            if "error" in log or "Traceback" in log:
                raise RuntimeError(log.splitlines()[-1].removeprefix("error "))
            time.sleep(0.5)
        raise RuntimeError("serwer obrazu w psie nie wystartował (sprawdź /tmp/go1cam.log)")

    def _run(self, command):
        _, out, err = self._jetson.exec_command(command, timeout=15)
        return out.read().decode(errors="replace") + err.read().decode(errors="replace")

    def _ssh(self, host, user, password, sock=None):
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, sock=sock, timeout=6,
                       banner_timeout=10, auth_timeout=10, allow_agent=False, look_for_keys=False)
        client.get_transport().set_keepalive(10)  # podtrzymuje tunel, gdy obraz akurat nie płynie
        return client

    def _stop(self):
        try:
            if self._jetson:
                self._run(f"pkill -f {_pattern('go1cam.py')}")
        except Exception:
            pass
        self._close()
        self._set("Kamera wyłączona")

    def _close(self):
        with self._lock:
            for client in (self._jetson, self._pi):
                if client:
                    client.close()
            self._pi = self._jetson = None
            self.active = None


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
