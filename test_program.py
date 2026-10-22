import ast
import time
import unittest

import program
import settings
from server import Pilot
from test_pilot import FakeClient


class ParseTest(unittest.TestCase):
    def labels(self, text, **kw):
        steps, errors = program.parse(text, **kw)
        return [s["label"] for s in steps], errors

    def test_sequence_with_auto_walk(self):
        labels, errors = self.labels("wstań, potem idź do przodu 2 sekundy, obróć się w lewo i połóż się")
        self.assertEqual(errors, [])
        self.assertEqual(labels, ["wstań", "tryb chodu", "do przodu 2 s (40%)", "obrót w lewo 3.5 s (40%)",
                                  "połóż się"])

    def test_decimal_seconds_and_speed_words(self):
        steps, _ = program.parse("tryb chodu; szybko do tyłu 1,5 s")
        move = steps[-1]
        self.assertEqual((move["seconds"], move["axes"]), (1.5, [0, 0, 0, -0.6]))

    def test_limits_are_applied(self):
        steps, _ = program.parse("chodź, bardzo szybko do przodu 60 sekund", max_speed=0.3, max_seconds=3)
        self.assertEqual((steps[-1]["seconds"], steps[-1]["axes"][3]), (3, 0.3))

    def test_moving_while_lying_needs_stand_up(self):
        _, errors = self.labels("połóż się, do przodu")
        self.assertIn("najpierw dodaj „wstań”", errors[0])

    def test_unknown_and_blocked(self):
        self.assertIn("Nie rozumiem", self.labels("zrób salto")[1][0])
        self.assertIn("trybie lekcji", self.labels("biegaj", blocked_modes=("run",))[1][0])

    def test_parser_does_not_guess(self):
        """„biegnij na kolegę” to nie samo „biegnij” – nieznane słowa i dwie komendy naraz to błąd."""
        self.assertIn("nie znam słów „na kolegę”", self.labels("biegnij na kolegę")[1][0])
        self.assertIn("dwa polecenia naraz", self.labels("wstań skocz")[1][0])
        self.assertIn("z jednostką", self.labels("chodź, do przodu 2")[1][0])
        self.assertEqual(self.labels("proszę wstań, teraz trochę wolno do tyłu")[1], [])
        self.assertEqual(self.labels("obróć się w lewo")[0][-1], "obrót w lewo 3.5 s (40%)")

    def test_wait_and_stop(self):
        labels, _ = self.labels("czekaj 2 s, stop")
        self.assertEqual(labels, ["czekaj 2 s", "stop"])


class PythonCodeTest(unittest.TestCase):
    def test_code_is_valid_python_and_matches_steps(self):
        text = "wstań, do przodu 2 s, skocz"
        steps, _ = program.parse(text)
        code, ranges = program.to_python(steps, "192.168.12.1", text, app_dir="C:/x")
        ast.parse(code)  # uczniowie mogą to uruchomić
        lines = code.splitlines()
        self.assertEqual(len(ranges), len(steps))
        move = ranges[2]  # wstań, tryb chodu, do przodu…
        self.assertIn("pies.set_stick(0, 0, 0, 0.4)", lines[move[0] - 1])
        self.assertIn("time.sleep(2)", lines[move[0]])
        self.assertIn('pies.send_mode("jumpYaw")', lines[ranges[3][0] - 1])

    def test_generated_code_runs_against_fake_dog(self):
        """Wykonujemy wygenerowany kod z podstawionym Go1Client i sprawdzamy, co dostał pies."""
        steps, _ = program.parse("chodź, w prawo 0.1 s")
        code, _ = program.to_python(steps, "pies", "test")
        calls = []

        class Recorder:
            def __init__(self, host):
                pass

            def __getattr__(self, name):
                return lambda *a: calls.append((name, a))

        code = code.replace("from go1_client import Go1Client", "").replace("time.sleep", "(lambda s: None)")
        exec(code, {"Go1Client": Recorder, "time": time})
        sent = [c for c in calls if c[0] in ("send_mode", "set_stick")]
        self.assertEqual(sent, [("send_mode", ("walk",)), ("set_stick", (0, 0.4, 0, 0)), ("set_stick", (0, 0, 0, 0))])


class PilotProgramTest(unittest.TestCase):
    def setUp(self):
        self.pilot = Pilot(client_factory=FakeClient, settings=settings.clean({"max_speed": 1.0}),
                           save=lambda s: None)
        self.pilot.connect("x")
        self.dog = self.pilot.client

    def wait_done(self, timeout=5):
        deadline = time.monotonic() + timeout
        while self.pilot.program["running"] and time.monotonic() < deadline:
            time.sleep(0.02)

    def test_program_executes_the_same_steps_as_the_code(self):
        self.pilot.run_program("chodź, do przodu 0.2 s, w lewo 0.2 s")
        self.wait_done()
        self.assertEqual(self.dog.modes, ["walk"])
        moves = [s for s in self.dog.sticks if any(s)]
        self.assertEqual(moves, [(0, 0, 0, 0.4), (0, -0.4, 0, 0)])
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])

    def test_stop_cancels_program_immediately(self):
        self.pilot.run_program("chodź, do przodu 5 s, skocz")
        time.sleep(0.8)
        self.pilot.stop_program()
        time.sleep(0.2)
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])
        self.assertNotIn("jumpYaw", self.dog.modes)

    def test_errors_do_not_run_anything_but_code_is_shown(self):
        self.pilot.run_program("wstań, zrób salto")
        self.assertFalse(self.pilot.program["running"])
        self.assertEqual(self.dog.modes, [])
        self.assertIn('send_mode("standUp")', self.pilot.program["code"])

    def test_disconnected_shows_code_without_running(self):
        self.pilot.disconnect()
        self.pilot.run_program("wstań")
        self.assertIn("połącz", self.pilot.program["errors"][0])

    def test_lesson_mode_caps_speed_time_and_blocks_run(self):
        self.pilot.update_settings({"lesson_mode": True})
        self.pilot.set_speed(1.0)
        self.assertEqual(self.pilot.speed, 0.3)
        self.pilot.drive([0, 0, 0, 1.0])
        self.assertEqual(self.pilot.axes[3], 0.3)
        self.assertFalse(self.pilot.send_mode("run"))
        self.pilot.run_program("chodź, do przodu 20 s")
        self.assertEqual(self.pilot.program["steps"][-1], "do przodu 3 s (30%)")
        self.pilot.stop_program()

    def test_deadman_stops_program(self):
        self.pilot.run_program("chodź, do przodu 5 s")
        time.sleep(0.8)
        self.pilot.last_seen = time.monotonic() - 5
        self.pilot.check_deadman()
        self.assertFalse(self.pilot.program["running"])
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])


class AiProgramTest(unittest.TestCase):
    def setUp(self):
        import ai
        self.ai = ai
        self.calls = []
        self.reply = ("chodź, do przodu 0.2 s", "Pies podejdzie.")
        self._orig = ai.rewrite
        ai.rewrite = self.fake_rewrite
        self.pilot = Pilot(client_factory=FakeClient, settings=settings.clean({"ai_mode": "fix"}),
                           save=lambda s: None)
        self.pilot.connect("x")

    def tearDown(self):
        self.ai.rewrite = self._orig

    def fake_rewrite(self, text, model="haiku", lesson=False):
        self.calls.append(text)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def wait(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(condition())

    def test_understood_command_skips_ai_in_fix_mode(self):
        self.pilot.run_program("wstań")
        self.assertEqual(self.calls, [])

    def test_unknown_command_is_rewritten_then_run_with_code(self):
        self.pilot.run_program("podejdź do mnie")
        self.wait(lambda: self.pilot.program["ai"]["status"] == "done")
        prog = self.pilot.program
        self.assertEqual(self.calls, ["podejdź do mnie"])
        self.assertEqual(prog["text"], "chodź, do przodu 0.2 s")
        self.assertIn("AI zamieniło „podejdź do mnie”", prog["code"])
        self.wait(lambda: not self.pilot.program["running"])
        self.assertIn((0, 0, 0, 0.4), self.pilot.client.sticks)

    def test_refusal_runs_nothing(self):
        self.reply = ("", "To niebezpieczne.")
        self.pilot.run_program("biegnij na kolegę")
        self.wait(lambda: self.pilot.program["ai"]["status"] == "done")
        self.assertIn("To niebezpieczne", self.pilot.program["errors"][0])
        self.assertEqual(self.pilot.client.modes, [])

    def test_ai_error_is_shown(self):
        self.reply = self.ai.AIError("brak internetu")
        self.pilot.run_program("zrób kwadrat")
        self.wait(lambda: self.pilot.program["ai"]["status"] == "error")
        self.assertIn("brak internetu", self.pilot.program["errors"][0])

    def test_always_mode_and_voice_never_uses_ai(self):
        self.pilot.update_settings({"ai_mode": "always"})
        self.pilot.run_program("wstań", source="głos")
        self.assertEqual(self.calls, [])
        self.pilot.run_program("wstań")
        self.wait(lambda: self.calls == ["wstań"])


if __name__ == "__main__":
    unittest.main()
