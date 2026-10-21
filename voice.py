"""Polskie komendy głosowe offline (Vosk) – działa bez internetu, także w sieci Wi-Fi psa."""
import array
import json
import math
import queue
import re
import threading
import time
import urllib.request
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

MODEL_NAME = "vosk-model-small-pl-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_DIR = Path(__file__).parent / "models" / MODEL_NAME

FORWARD, STRAFE, TURN = 3, 0, 1
MOVE_SECONDS = 2.0
SPIN_SECONDS = 3.5
SIMILAR_ENOUGH = 0.5  # zmierzone na nagraniach: prawdziwe komendy ≥ 0.55, zwykłe zdania ≤ 0.43
STRICTNESS = {"strict": 0.65, "normal": SIMILAR_ENOUGH, "loose": 0.35}

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
    "skocz": ("mode", "jumpYaw"), "skok": ("mode", "jumpYaw"), "hop": ("mode", "jumpYaw"),
    "naprzód": ("move", FORWARD, +1), "do przodu": ("move", FORWARD, +1), "idź": ("move", FORWARD, +1),
    "do tyłu": ("move", FORWARD, -1), "cofnij": ("move", FORWARD, -1),
    "w lewo": ("move", TURN, -1), "skręć w lewo": ("move", TURN, -1),
    "w prawo": ("move", TURN, +1), "skręć w prawo": ("move", TURN, +1),
    "bokiem w lewo": ("move", STRAFE, -1), "bokiem w prawo": ("move", STRAFE, +1),
    "obróć się": ("spin",), "kręć się": ("spin",), "zawróć": ("spin",),
    "szybciej": ("speed", +0.1), "wolniej": ("speed", -0.1),
}
_BY_LENGTH = sorted(COMMANDS, key=len, reverse=True)


def parse_command(text):
    """Zwraca (fraza, akcja) dla pierwszej rozpoznanej komendy albo None."""
    text = f" {text.lower().strip()} "
    for phrase in _BY_LENGTH:
        if re.search(rf"\s{re.escape(phrase)}\s", text):
            return phrase, COMMANDS[phrase]
    return None


def accept_command(command_text, free_text, threshold=SIMILAR_ENOUGH):
    """Komenda z rozpoznawania zawężonego do komend, potwierdzona swobodnym zapisem zdania.

    Zawężone rozpoznawanie dopasuje do komendy każde zdanie („dzisiaj skoczymy do kina” -> „skocz”),
    więc wykonujemy je tylko, gdy swobodny zapis też zawiera komendę albo brzmi podobnie
    („co w niej” ≈ „cofnij”: 0.77, a „sklepu po chleb” ≈ „skręć w lewo”: tylko 0.43).
    """
    found = parse_command(command_text)
    if not found:
        return None
    phrase, action = found
    if action[0] == "stop":  # fałszywy stop nic nie psuje, przegapiony – tak
        return found
    if not free_text or parse_command(free_text) == found:
        return found
    letters = lambda s: s.replace(" ", "")
    if SequenceMatcher(None, letters(free_text), letters(phrase)).ratio() >= threshold:
        return found
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


def list_microphones():
    """Mikrofony z interfejsu MME – te same, które widać w ustawieniach dźwięku Windows."""
    import sounddevice as sd

    mme = next(i for i, api in enumerate(sd.query_hostapis()) if api["name"] == "MME")
    return [{"id": i, "name": d["name"]} for i, d in enumerate(sd.query_devices())
            if d["hostapi"] == mme and d["max_input_channels"] > 0 and "Mapowanie" not in d["name"]]


def _default_mic_volume():
    import comtypes
    from comtypes import CLSCTX_ALL
    from ctypes import POINTER, cast
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    comtypes.CoInitialize()
    device = AudioUtilities.GetMicrophone()
    if not device:
        return None
    return cast(device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))


def mic_muted():
    """True gdy domyślny mikrofon jest wyciszony w Windows; None gdy nie da się sprawdzić."""
    try:
        volume = _default_mic_volume()
        return None if volume is None else bool(volume.GetMute())
    except Exception:
        return None


def unmute_mic():
    volume = _default_mic_volume()
    if volume is not None:
        volume.SetMute(0, None)


def level_of(chunk):
    """Głośność fragmentu nagrania w skali 0..1 (od -60 dB do -10 dB)."""
    samples = array.array("h", chunk)
    if not samples:
        return 0.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    db = 20 * math.log10(max(rms, 1) / 32768)
    return max(0.0, min(1.0, (db + 60) / 50))


def _text(result_json, key):
    return json.loads(result_json).get(key, "").replace("[unk]", "").strip()


class VoiceListener:
    RATE = 16000
    SILENT_LEVEL = 0.08   # poniżej tego mikrofon praktycznie nic nie łapie
    SILENT_SECONDS = 4.0

    def __init__(self, on_partial, on_final, on_status):
        self.on_partial, self.on_final, self.on_status = on_partial, on_final, on_status
        self.device = None  # None = domyślny mikrofon Windows
        self.level = 0.0
        self._stop = threading.Event()
        self._thread = None
        self._model = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, device=None):
        if self.running and device == self.device:
            return
        if self.running:
            self.stop()
            self._thread.join(timeout=2)
        self.device = device
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.level = 0.0

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
            free = vosk.KaldiRecognizer(self._model, self.RATE)  # zapis całego zdania do potwierdzenia
            free_parts = []
            audio = queue.Queue()
            with sd.RawInputStream(samplerate=self.RATE, blocksize=4000, dtype="int16", channels=1,
                                   device=self.device, callback=lambda data, *_: audio.put(bytes(data))):
                self.on_status("Słucham")
                loud_at = time.monotonic()
                warned = False
                while not self._stop.is_set():
                    try:
                        chunk = audio.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    self.level = level_of(chunk)
                    now = time.monotonic()
                    if self.level > self.SILENT_LEVEL:
                        loud_at = now
                        if warned:
                            self.on_status("Słucham")
                            warned = False
                    elif not warned and now - loud_at > self.SILENT_SECONDS:
                        self.on_status("Mikrofon nic nie łapie. Sprawdź, czy nie jest wyciszony albo wybierz inny.")
                        warned = True
                    if free.AcceptWaveform(chunk):
                        free_parts.append(_text(free.Result(), "text"))
                    if rec.AcceptWaveform(chunk):
                        free_parts.append(_text(free.FinalResult(), "text"))
                        said = " ".join(p for p in free_parts if p)
                        free_parts = []
                        command = _text(rec.Result(), "text")
                        if command or said:
                            self.on_final(command, said)
                    else:
                        self.on_partial(_text(rec.PartialResult(), "partial"),
                                        _text(free.PartialResult(), "partial"))
            self.on_status("Mikrofon wyłączony")
        except Exception as e:  # brak mikrofonu, brak internetu przy pobieraniu modelu itp.
            self.on_status(f"Błąd mikrofonu: {e}")
        finally:
            self.level = 0.0
