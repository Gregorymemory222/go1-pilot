import time
import unittest

import server
from server import Pilot
from voice import FORWARD, TURN, parse_command


class FakeClient:
    def __init__(self, host, on_status=None):
        self.host, self.connected = host, False
        self.modes, self.sticks = [], []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send_mode(self, mode):
        self.modes.append(mode)

    def set_stick(self, *axes):
        self.sticks.append(axes)

    def set_led(self, r, g, b):
        pass


class ParseCommandTest(unittest.TestCase):
    def test_longest_phrase_wins(self):
        self.assertEqual(parse_command("taniec dwa")[1], ("mode", "dance2"))
        self.assertEqual(parse_command("bokiem w lewo")[0], "bokiem w lewo")

    def test_moves_and_stop(self):
        self.assertEqual(parse_command("do przodu")[1], ("move", FORWARD, 1))
        self.assertEqual(parse_command("skręć w prawo")[1], ("move", TURN, 1))
        self.assertEqual(parse_command("stój")[1], ("stop",))

    def test_whole_words_only(self):
        self.assertIsNone(parse_command("pozanic"))
        self.assertIsNone(parse_command(""))


class PilotTest(unittest.TestCase):
    def setUp(self):
        self.pilot = Pilot(client_factory=FakeClient)
        self.pilot.connect("1.2.3.4")
        self.dog = self.pilot.client

    def test_voice_mode_command(self):
        self.pilot._on_voice("wstań")
        self.assertEqual(self.dog.modes, ["standUp"])
        self.assertEqual(self.pilot.last_command, "wstań")

    def test_voice_move_stops_by_itself(self):
        self.pilot.set_speed(0.5)
        self.pilot.timed_move(FORWARD, +1, seconds=0.2)
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0.5])
        time.sleep(0.35)
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])

    def test_manual_input_cancels_voice_timer(self):
        self.pilot.timed_move(FORWARD, +1, seconds=0.2)
        self.pilot.set_axes([0, 0.3, 0, 0])
        time.sleep(0.35)
        self.assertEqual(self.pilot.axes, [0, 0.3, 0, 0])

    def test_voice_stop(self):
        self.pilot.set_axes([0, 0, 0, 1])
        self.pilot._on_voice("stop")
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])

    def test_voice_ignored_when_disconnected(self):
        self.pilot.disconnect()
        self.pilot._on_voice("do przodu")
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])
        self.assertIn("najpierw połącz", self.pilot.last_command)

    def test_deadman_stops_when_window_silent(self):
        self.pilot.set_axes([0, 0, 0, 1])
        self.pilot.last_seen = time.monotonic() - server.STICK_DEADMAN - 0.1
        self.pilot.check_deadman()
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])

    def test_axes_clamped(self):
        self.pilot.set_axes([5, -5, 0, 0])
        self.assertEqual(self.pilot.axes, [1, -1, 0, 0])


if __name__ == "__main__":
    unittest.main()
