import time
import unittest

import server
import settings
from server import Pilot
from voice import FORWARD, TURN, accept_command, parse_command


class FakeClient:
    def __init__(self, host, on_status=None):
        self.host, self.connected, self.battery = host, False, None
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

    def test_command_inside_sentence_rejected(self):
        # zawężone rozpoznawanie słyszy „skocz”, swobodne – całe zdanie
        self.assertIsNone(accept_command("skocz", "dzisiaj skończymy do kina"))

    def test_similar_sounding_free_text_accepted(self):
        self.assertEqual(accept_command("cofnij", "co w niej")[0], "cofnij")
        self.assertEqual(accept_command("podnieś się", "podnieście")[0], "podnieś się")
        self.assertEqual(accept_command("bokiem w prawo", "bogiem w prawo")[0], "bokiem w prawo")

    def test_pieces_of_ordinary_sentence_rejected(self):
        self.assertIsNone(accept_command("idź", "idziemy dzisiaj"))
        self.assertIsNone(accept_command("skręć w lewo", "sklepu po chleb"))

    def test_command_confirmed_by_free_text_in_longer_sentence(self):
        self.assertEqual(accept_command("wstań", "no dalej piesku wstań")[0], "wstań")

    def test_stop_always_accepted(self):
        self.assertEqual(accept_command("stop", "a teraz już proszę stop natychmiast")[0], "stop")

    def test_whole_words_only(self):
        self.assertIsNone(parse_command("pozanic"))
        self.assertIsNone(parse_command(""))


class PilotTest(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.pilot = Pilot(client_factory=FakeClient, settings=settings.clean({"max_speed": 1.0}),
                           save=self.saved.append)
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

    def test_driving_from_standing_switches_to_walk(self):
        self.pilot.send_mode("standUp")
        self.pilot.drive([0, 0, 0, 0.4])
        self.assertEqual(self.dog.modes, ["standUp", "walk"])
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0.4])

    def test_driving_while_lying_is_refused(self):
        self.pilot.send_mode("standDown")
        self.assertFalse(self.pilot.drive([0, 0, 0, 0.4]))
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])
        self.assertIn("Wstań", self.pilot.notice)

    def test_head_tilt_in_pose_mode_keeps_mode(self):
        self.pilot.send_mode("stand")
        self.pilot.drive([0, 0, 0.4, 0])
        self.assertEqual(self.dog.modes, ["stand"])

    def test_voice_jump(self):
        self.pilot._on_voice("skocz")
        self.assertEqual(self.dog.modes, ["jumpYaw"])

    def test_voice_speed_changes_clamped(self):
        self.pilot.set_speed(0.95)
        self.pilot._on_voice("szybciej")
        self.assertEqual(self.pilot.speed, 1.0)
        self.pilot._on_voice("wolniej")
        self.assertEqual(self.pilot.speed, 0.9)

    def test_partial_stop_halts_immediately(self):
        self.pilot.set_axes([0, 0, 0, 1])
        self.pilot._on_partial("stop")
        self.assertEqual(self.pilot.axes, [0, 0, 0, 0])

    def test_new_synonyms(self):
        self.assertEqual(parse_command("waruj")[1], ("mode", "standDown"))
        self.assertEqual(parse_command("dawaj")[1], ("move", FORWARD, 1))
        self.assertEqual(parse_command("hamuj")[1], ("stop",))
        self.assertEqual(parse_command("podaj łapę")[1], ("mode", "straightHand1"))

    def test_voice_seq_marks_each_outcome(self):
        seq = self.pilot.voice_seq
        self.pilot._on_voice("wstań", "wstań")
        self.assertEqual((self.pilot.voice_seq, self.pilot.voice_result), (seq + 1, "ok"))
        self.pilot._on_voice("skocz", "dzisiaj skończymy do kina")
        self.assertEqual((self.pilot.voice_seq, self.pilot.voice_result), (seq + 2, "rejected"))
        self.pilot.disconnect()
        self.pilot._on_voice("wstań", "wstań")
        self.assertEqual((self.pilot.voice_seq, self.pilot.voice_result), (seq + 3, "offline"))

    def test_push_to_talk_follows_settings(self):
        self.pilot.update_settings({"mic_mode": "ptt"})
        self.assertTrue(self.pilot.voice.push_to_talk)
        self.pilot.set_talking(True)
        self.assertTrue(self.pilot.state()["voice"]["talking"])
        self.pilot.update_settings({"mic_mode": "continuous"})
        self.assertFalse(self.pilot.voice.push_to_talk)

    def test_axes_clamped(self):
        self.pilot.set_axes([5, -5, 0, 0])
        self.assertEqual(self.pilot.axes, [1, -1, 0, 0])


if __name__ == "__main__":
    unittest.main()
