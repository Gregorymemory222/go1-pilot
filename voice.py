"""Polskie komendy głosowe offline (Vosk) – działa bez internetu, także w sieci Wi-Fi psa."""
import json
import queue
import re
import threading
import urllib.request
import zipfile
from pathlib import Path

MODEL_NAME = "vosk-model-small-pl-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_DIR = Path(__file__).parent / "models" / MODEL_NAME

FORWARD, STRAFE, TURN = 3, 0, 1
MOVE_SECONDS = 2.0

# fraza -> akcja; dłuższe frazy wygrywają z krótszymi ("taniec dwa" przed "taniec")
COMMANDS = {
    "stop": ("stop",), "stój": ("stop",), "zatrzymaj się": ("stop",),
    "wstań": ("mode", "standUp"),
    "połóż się": ("mode", "standDown"), "leżeć": ("mode", "standDown"), "leż": ("mode", "standDown"),
    "podnieś się": ("mode", "recoverStand"),
    "chodź": ("mode", "walk"), "tryb chodu": ("mode", "walk"),
    "biegaj": ("mode", "run"), "bieg": ("mode", "run"),
    "wspinaj się": ("mode", "climb"),
    "poza": ("mode", "stand"),
    "tańcz": ("mode", "dance1"), "taniec": ("mode", "dance1"),
    "taniec dwa": ("mode", "dance2"), "drugi taniec": ("mode", "dance2"),
    "daj łapę": ("mode", "straightHand1"), "łapa": ("mode", "straightHand1"),
    "naprzód": ("move", FORWARD, +1), "do przodu": ("move", FORWARD, +1), "idź": ("move", FORWARD, +1),
    "do tyłu": ("move", FORWARD, -1), "cofnij": ("move", FORWARD, -1),
    "w lewo": ("move", TURN, -1), "skręć w lewo": ("move", TURN, -1),
    "w prawo": ("move", TURN, +1), "skręć w prawo": ("move", TURN, +1),
    "bokiem w lewo": ("move", STRAFE, -1), "bokiem w prawo": ("move", STRAFE, +1),
}
_BY_LENGTH = sorted(COMMANDS, key=len, reverse=True)


def parse_command(text):
    """Zwraca (fraza, akcja) dla pierwszej rozpoznanej komendy albo None."""
    text = f" {text.lower().strip()} "
    for phrase in _BY_LENGTH:
        if re.search(rf"\s{re.escape(phrase)}\s", text):
            return phrase, COMMANDS[phrase]
    return None


def ensure_model(on_status):
    if MODEL_DIR.exists():
        return
    on_status("Pobieram model mowy (ok. 50 MB)…")
    MODEL_DIR.parent.mkdir(exist_ok=True)
    archive = MODEL_DIR.parent / f"{MODEL_NAME}.zip"
    urllib.request.urlretrieve(MODEL_URL, archive)
    with zipfile.ZipFile(archive) as z:
        z.extractall(MODEL_DIR.parent)
    archive.unlink()


class VoiceListener:
    RATE = 16000

    def __init__(self, on_partial, on_final, on_status):
        self.on_partial, self.on_final, self.on_status = on_partial, on_final, on_status
        self._stop = threading.Event()
        self._thread = None
        self._model = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            import sounddevice as sd
            import vosk

            if self._model is None:
                ensure_model(self.on_status)
                self.on_status("Ładuję model mowy…")
                vosk.SetLogLevel(-1)
                self._model = vosk.Model(str(MODEL_DIR))
            # gramatyka zawężona do komend = dużo lepsza trafność; reszta mowy trafia do [unk]
            grammar = json.dumps(sorted(COMMANDS) + ["[unk]"], ensure_ascii=False)
            rec = vosk.KaldiRecognizer(self._model, self.RATE, grammar)
            audio = queue.Queue()
            with sd.RawInputStream(samplerate=self.RATE, blocksize=4000, dtype="int16", channels=1,
                                   callback=lambda data, *_: audio.put(bytes(data))):
                self.on_status("Słucham")
                while not self._stop.is_set():
                    try:
                        chunk = audio.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if rec.AcceptWaveform(chunk):
                        text = json.loads(rec.Result()).get("text", "").replace("[unk]", "").strip()
                        if text:
                            self.on_final(text)
                    else:
                        partial = json.loads(rec.PartialResult()).get("partial", "").replace("[unk]", "").strip()
                        self.on_partial(partial)
            self.on_status("Mikrofon wyłączony")
        except Exception as e:  # brak mikrofonu, brak internetu przy pobieraniu modelu itp.
            self.on_status(f"Błąd mikrofonu: {e}")
