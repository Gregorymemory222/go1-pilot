"""Sterowanie Unitree Go1 przez wbudowany broker MQTT (ten sam, którego używa aplikacja na telefon).

Protokół (za dbaldwin/go1-js):
  controller/action  -> nazwa trybu jako tekst, np. "standUp", QoS 1
  controller/stick   -> 4 x float32 little-endian: [lewo/prawo, obrót, góra/dół, przód/tył], każdy w [-1, 1]
  programming/code   -> kolor LED
"""
import struct
import threading

import paho.mqtt.client as mqtt

DEFAULT_HOST = "192.168.12.1"  # Wi-Fi psa; po kablu Ethernet: 192.168.123.161
DEFAULT_PORT = 1883

MODES = (
    "standUp", "standDown", "recoverStand", "stand", "walk", "run", "climb",
    "dance1", "dance2", "straightHand1", "damping",
)


def _clamp(v):
    return max(-1.0, min(1.0, float(v)))


def pack_stick(strafe, turn, pitch, forward):
    return struct.pack("<4f", _clamp(strafe), _clamp(turn), _clamp(pitch), _clamp(forward))


class Go1Client:
    STICK_PERIOD = 0.1  # pies oczekuje gałek co ~100 ms, tak jak aplikacja

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, on_status=None, mqtt_client=None):
        self.host, self.port = host, port
        self.on_status = on_status or (lambda text: None)
        self.connected = False
        self._stick = (0.0, 0.0, 0.0, 0.0)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._mqtt = mqtt_client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="go1-pilot")
        self._mqtt.on_connect = self._handle_connect
        self._mqtt.on_disconnect = self._handle_disconnect

    def connect(self):
        self.on_status(f"Łączenie z {self.host}:{self.port}…")
        self._mqtt.connect_async(self.host, self.port, keepalive=10)
        self._mqtt.loop_start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._stick_loop, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._stop.set()
        self.set_stick(0, 0, 0, 0)
        if self.connected:
            # pies ma stanąć, zanim zamkniemy połączenie
            self._publish_stick().wait_for_publish(1.0)
        self._mqtt.disconnect()
        self._mqtt.loop_stop()
        self.connected = False

    def send_mode(self, mode):
        if mode not in MODES:
            raise ValueError(f"Nieznany tryb: {mode}")
        self._mqtt.publish("controller/action", mode, qos=1)

    def set_stick(self, strafe, turn, pitch, forward):
        with self._lock:
            self._stick = (strafe, turn, pitch, forward)

    def set_led(self, r, g, b):
        self._mqtt.publish("programming/code", f"child_conn.send('change_light({r},{g},{b})')", qos=0)

    def _publish_stick(self):
        with self._lock:
            payload = pack_stick(*self._stick)
        return self._mqtt.publish("controller/stick", payload, qos=0)

    def _stick_loop(self):
        while not self._stop.wait(self.STICK_PERIOD):
            if self.connected:
                self._publish_stick()

    def _handle_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        self.on_status("Połączono ✔" if self.connected else f"Błąd połączenia: {reason_code}")

    def _handle_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        if not self._stop.is_set():
            self.on_status("Rozłączono – ponawiam…")
