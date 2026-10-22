"""AI poprawia polecenia: zamienia swobodny tekst ucznia na polecenie w języku, który rozumie program.py.

AI nigdy nie steruje psem bezpośrednio – zwraca tylko tekst polecenia. Ten tekst przechodzi potem
przez zwykły parser (te same limity bezpieczeństwa i ten sam kod w Pythonie dla uczniów).
Używa Claude Code w trybie bez okna (`claude -p`) – działa na subskrypcji Claude, bez klucza API,
ale potrzebuje internetu.
"""
import json
import os
import shutil
import subprocess
import tempfile

from voice import COMMANDS

TIMEOUT = 90  # s


class AIError(Exception):
    pass


def build_prompt(text, lesson):
    phrases = ", ".join(sorted(COMMANDS))
    return "\n".join([
        "Jesteś tłumaczem poleceń dla robota-psa Unitree Go1 na lekcji programowania w szkole.",
        "Zamień polecenie ucznia na polecenie, które rozumie prosty parser. Parser zna WYŁĄCZNIE te frazy:",
        phrases + ".",
        "Do fraz ruchu (do przodu, do tyłu, w lewo, w prawo, bokiem w lewo/prawo, obróć się) można dodać czas,"
        " np. „2 sekundy”, oraz tempo: „wolno”, „szybko”, „bardzo wolno”. „obróć się w lewo” obraca w lewo.",
        "Pauza: „czekaj 2 s”. Kroki oddzielaj przecinkami. Przykład: „wstań, do przodu 2 sekundy, obróć się"
        " w lewo, czekaj 1 s, połóż się”.",
        "Nie wymyślaj innych słów. Kształty rozbijaj na kroki (np. kwadrat: 4 × do przodu 1 s i w prawo 1 s).",
        "Ruch najwyżej 8 sekund na krok" + (", w trybie lekcji najwyżej 3 sekundy i bez biegania" if lesson else "") + ".",
        "Jeśli polecenie jest niebezpieczne (np. biegnij na ludzi, skacz ze stołu, uderz w coś) albo niemożliwe,"
        " zwróć pusty „polecenie” i wyjaśnij dlaczego.",
        "Odpowiedz WYŁĄCZNIE jednym obiektem JSON, bez tekstu przed ani po:",
        '{"polecenie": "polecenie dla parsera albo pusty string", "wyjasnienie": "jedno krótkie zdanie po polsku dla ucznia"}',
        "",
        f"Polecenie ucznia: {text}",
    ])


def rewrite(text, model="haiku", lesson=False, claude=None):
    """Zwraca (polecenie, wyjaśnienie). Rzuca AIError z opisem dla ucznia, gdy się nie uda."""
    exe = claude or shutil.which("claude") or os.path.expanduser(r"~\.local\bin\claude.exe")
    args = [exe, "-p", "--output-format", "json", "--model", model,
            "--setting-sources", "project", "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence"]
    try:
        with tempfile.TemporaryDirectory() as empty_dir:  # bez dostępu do plików projektu
            proc = subprocess.run(args, input=build_prompt(text, lesson), capture_output=True, text=True,
                                  encoding="utf-8", timeout=TIMEOUT, cwd=empty_dir,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise AIError("nie znalazłem programu „claude” (Claude Code). Zainstaluj go albo wyłącz AI w Ustawieniach.")
    except subprocess.TimeoutExpired:
        raise AIError("AI odpowiadało za długo. Sprawdź internet.")
    try:
        outer = json.loads(proc.stdout)
    except ValueError:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        hint = " Laptop w Wi-Fi psa nie ma internetu – patrz README." if _looks_offline(proc) else ""
        raise AIError(f"AI nie odpowiedziało ({detail[-1][:160] if detail else f'kod {proc.returncode}'}).{hint}")
    if outer.get("is_error"):
        message = str(outer.get("result") or outer.get("subtype") or "")
        hint = " Laptop w Wi-Fi psa nie ma internetu – patrz README." if _looks_offline(proc, message) else ""
        raise AIError(f"AI zgłosiło błąd: {message[:160]}.{hint}")
    data = extract_json(str(outer.get("result", "")))
    if not isinstance(data, dict) or "polecenie" not in data:
        raise AIError("AI odpowiedziało w złym formacie. Spróbuj jeszcze raz.")
    return str(data["polecenie"]).strip(), str(data.get("wyjasnienie", "")).strip()


def extract_json(text):
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1]):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _looks_offline(proc, extra=""):
    text = f"{proc.stdout} {proc.stderr} {extra}".lower()
    return any(word in text for word in ("enotfound", "network", "connect", "getaddrinfo", "offline", "econn"))
