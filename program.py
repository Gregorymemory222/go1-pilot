"""Polecenia tekstowe po polsku -> kroki programu -> kod w Pythonie, który pokazujemy uczniom.

Aplikacja wykonuje dokładnie te kroki, z których powstaje kod – kod nie jest „ilustracją”,
tylko zapisem tego, co naprawdę dostaje pies (go1_client.Go1Client).
"""
import re

from voice import COMMANDS, FORWARD, STRAFE, TURN, parse_command

_BY_LENGTH = sorted(COMMANDS, key=len, reverse=True)
# słowa, które nic nie zmieniają w poleceniu („proszę wstań”, „teraz trochę do przodu”)
FILLER = {"proszę", "teraz", "piesku", "pies", "psie", "no", "to", "jeszcze", "trochę", "przez", "a", "się",
          "mi", "ty", "go", "ok", "dobrze", "dalej"}

GAITS = {"walk", "run", "climb"}
LYING = {"standDown", "damping"}
MAX_STEPS = 30
# tryb -> (opis, ile sekund odczekać, zanim następny krok – szacunkowo, pies nie mówi, kiedy skończył)
MODE_INFO = {
    "standUp": ("wstań", 2.0), "standDown": ("połóż się", 2.0), "recoverStand": ("podnieś się po upadku", 3.0),
    "stand": ("poza – stój w miejscu", 0.5), "walk": ("tryb chodu", 0.5), "run": ("tryb biegu", 0.5),
    "climb": ("tryb wspinaczki", 0.5), "dance1": ("taniec 1", 8.0), "dance2": ("taniec 2", 8.0),
    "straightHand1": ("podaj łapę", 4.0), "jumpYaw": ("skok z obrotem", 2.0),
}
MOVE_NAMES = {(FORWARD, 1): "do przodu", (FORWARD, -1): "do tyłu", (STRAFE, 1): "bokiem w prawo",
              (STRAFE, -1): "bokiem w lewo", (TURN, 1): "obrót w prawo", (TURN, -1): "obrót w lewo"}
AXIS_ARGS = ("bok", "obrót", "głowa", "przód")  # kolejność argumentów set_stick

_SPLIT = re.compile(r"\s*(?:[,;.\n]|\ba potem\b|\bpotem\b|\bnastępnie\b|\bi\b|\boraz\b)\s*")
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s\b|sek\w*)")
_WAIT = re.compile(r"\b(?:czekaj|poczekaj|odczekaj|pauza|przerwa)\b")
_SPEEDS = (("bardzo szybko", 0.8), ("szybko", 0.6), ("bardzo wolno", 0.15), ("wolno", 0.25), ("powoli", 0.25))


def parse(text, speed=0.4, max_speed=1.0, move_seconds=2.0, spin_seconds=3.5, max_seconds=8.0,
          start_mode=None, auto_walk=True, blocked_modes=()):
    """Zwraca (kroki, błędy). Każdy krok to słownik z polem kind: mode / move / wait / stop / note."""
    steps, errors = [], []
    mode = start_mode
    # „1,5 s” i „1.5 s” to liczby, a nie koniec polecenia
    protected = re.sub(r"(\d)[.,](\d)", r"\1#\2", text.lower())
    for clause in _SPLIT.split(protected):
        clause = clause.replace("#", ".").strip()
        if not clause:
            continue
        duration = _DURATION.search(clause)
        seconds = min(float(duration.group(1)), max_seconds) if duration else None
        clause_speed = next((v for word, v in _SPEEDS if word in clause), None)

        if _WAIT.search(clause):
            steps.append({"kind": "wait", "seconds": seconds or 1.0, "label": f"czekaj {_num(seconds or 1.0)} s"})
            continue
        found = parse_command(clause)
        if not found:
            if clause_speed is not None:  # samo „szybko” zmienia prędkość dalszych ruchów
                speed = min(clause_speed, max_speed)
                steps.append({"kind": "note", "label": f"od teraz prędkość {_pct(speed)}"})
                continue
            errors.append(f"Nie rozumiem: „{clause}”")
            continue
        phrase, action = found
        others, unknown = _leftovers(clause, action)
        if others:
            errors.append(f"„{clause}”: dwa polecenia naraz ({phrase}, {others[0]}) – oddziel je przecinkiem")
            continue
        if unknown:
            hint = " – czas pisz z jednostką, np. „2 sekundy”" if any(w.isdigit() for w in unknown) else ""
            errors.append(f"„{clause}”: nie znam słów „{' '.join(unknown)}”{hint}")
            continue
        kind = action[0]
        if kind == "stop":
            steps.append({"kind": "stop", "label": "stop"})
        elif kind == "speed":
            speed = round(max(0.1, min(max_speed, speed + action[1])), 2)
            steps.append({"kind": "note", "label": f"{phrase}: od teraz prędkość {_pct(speed)}"})
        elif kind == "mode":
            if action[1] in blocked_modes:
                errors.append(f"„{phrase}” jest wyłączone w trybie lekcji")
                continue
            steps.append(_mode_step(action[1]))
            mode = action[1]
        else:  # move / spin
            if kind == "spin":
                axis, sign = TURN, (-1 if "lew" in clause else 1)
                seconds = seconds or spin_seconds
            else:
                axis, sign = action[1], action[2]
                seconds = seconds or move_seconds
            if mode not in GAITS and mode != "stand":
                if mode in LYING:
                    errors.append(f"„{clause}”: pies leży – najpierw dodaj „wstań”")
                    continue
                if auto_walk:
                    steps.append(_mode_step("walk", why="bez trybu chodu pies stoi w miejscu"))
                    mode = "walk"
            value = min(clause_speed, max_speed) if clause_speed is not None else speed
            axes = [0.0, 0.0, 0.0, 0.0]
            axes[axis] = round(sign * value, 2)
            name = MOVE_NAMES[(axis, sign)]
            steps.append({"kind": "move", "axes": axes, "seconds": seconds, "name": name,
                          "label": f"{name} {_num(seconds)} s ({_pct(value)})"})
    if len(steps) > MAX_STEPS:
        errors.append(f"Za długi program: najwyżej {MAX_STEPS} kroków")
    return steps, errors


def _leftovers(clause, action):
    """Co w zdaniu zostaje poza rozpoznaną komendą: (inne komendy, nieznane słowa).

    Parser nie zgaduje: „biegnij na kolegę” to nie samo „biegnij”. Nieznane słowa = błąd
    (a z włączonym AI – polecenie idzie do AI, które może odmówić)."""
    text = f" {_DURATION.sub(' ', clause)} "
    for word, _ in _SPEEDS:
        text = text.replace(f" {word} ", " ")
    others = []
    for phrase in _BY_LENGTH:
        pattern = rf"\s{re.escape(phrase)}(?=\s)"
        if not re.search(pattern, text):
            continue
        other = COMMANDS[phrase]
        turn_direction = action == ("spin",) and other[:2] == ("move", TURN)  # „obróć się w lewo”
        if other != action and not turn_direction and phrase not in others:
            others.append(phrase)
        text = re.sub(pattern, " ", text)
    return others, [w for w in text.split() if w not in FILLER]


def _mode_step(mode, why=None):
    label, wait = MODE_INFO[mode]
    return {"kind": "mode", "mode": mode, "wait": wait, "label": label, "why": why}


def to_python(steps, host, source_text, app_dir=None, note=None):
    """Kod w Pythonie + dla każdego kroku zakres linii (do podświetlania wykonywanego kroku)."""
    lines = [f"# Program z polecenia: „{source_text.strip()}”"]
    if note:
        lines.append(f"# {note}")
    lines += ["# Wygenerowany przez Go1 Pilot", "import time"]
    if app_dir:
        lines.append(f'import sys; sys.path.append(r"{app_dir}")  # tu leży go1_client.py')
    lines += [
        "from go1_client import Go1Client", "",
        f'pies = Go1Client("{host}")   # adres psa w jego Wi-Fi',
        "pies.connect()",
        "pies.wait_connected()          # czekamy, aż pies odpowie", "",
        "# set_stick(bok, obrót, głowa, przód) – każda wartość od -1 do 1, 0 = stoi",
    ]
    ranges = []
    for step in steps:
        start = len(lines) + 1
        kind = step["kind"]
        if kind == "mode":
            comment = step["label"] + (f" ({step['why']})" if step.get("why") else "")
            lines.append(_comment(f'pies.send_mode("{step["mode"]}")', comment))
            lines.append(_comment(f"time.sleep({_num(step['wait'])})", "czekamy, aż skończy (szacunkowo)"))
        elif kind == "move":
            args = ", ".join(_num(v) for v in step["axes"])
            moving = next(name for name, v in zip(AXIS_ARGS, step["axes"]) if v)
            value = _num(max(step["axes"], key=abs))
            lines.append(_comment(f"pies.set_stick({args})", f"{step['name']}: „{moving}” = {value}"))
            lines.append(_comment(f"time.sleep({_num(step['seconds'])})", f"ruch trwa {_num(step['seconds'])} s"))
            lines.append(_comment("pies.set_stick(0, 0, 0, 0)", "stop – wszystkie gałki na zero"))
        elif kind == "wait":
            lines.append(_comment(f"time.sleep({_num(step['seconds'])})", step["label"]))
        elif kind == "stop":
            lines.append(_comment("pies.set_stick(0, 0, 0, 0)", "stop"))
        else:
            lines.append(f"# {step['label']}")
        ranges.append([start, len(lines)])
    lines += ["", "pies.disconnect()              # na koniec pies staje i się rozłączamy"]
    return "\n".join(lines) + "\n", ranges


def _comment(code, text):
    return f"{code:<30} # {text}"


def _num(value):
    return f"{value:g}"


def _pct(value):
    return f"{round(abs(value) * 100)}%"
