import ast
import unittest
from pathlib import Path

import server
import settings
from server import Pilot
from test_pilot import FakeClient


class SettingsTest(unittest.TestCase):
    def test_bad_values_fall_back_or_clamp(self):
        s = settings.clean({"max_speed": 5, "camera_quality": "ultra", "move_seconds": "abc", "junk": 1})
        self.assertEqual(s["max_speed"], 1.0)
        self.assertEqual(s["camera_quality"], "medium")
        self.assertEqual(s["move_seconds"], settings.DEFAULTS["move_seconds"])
        self.assertNotIn("junk", s)

    def test_start_speed_never_above_max(self):
        s = settings.clean({"max_speed": 0.3, "start_speed": 0.9})
        self.assertEqual(s["start_speed"], 0.3)

    def test_round_trip(self):
        path = Path(self.id() + ".json")
        try:
            settings.save(settings.clean({"host": "10.0.0.5"}), path)
            self.assertEqual(settings.load(path)["host"], "10.0.0.5")
        finally:
            path.unlink(missing_ok=True)


class PilotSettingsTest(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.pilot = Pilot(client_factory=FakeClient, settings=settings.clean({}), save=self.saved.append)

    def test_empty_password_keeps_old_one(self):
        self.pilot.update_settings({"pi_password": "", "jetson_password": "nowe"})
        self.assertEqual(self.pilot.settings["pi_password"], "123")
        self.assertEqual(self.pilot.settings["jetson_password"], "nowe")
        self.assertEqual(len(self.saved), 1)

    def test_passwords_never_sent_to_window(self):
        self.assertNotIn("pi_password", self.pilot.state()["settings"])

    def test_lower_max_speed_clamps_current_speed(self):
        self.pilot.set_speed(0.6)
        self.pilot.update_settings({"max_speed": 0.3})
        self.assertEqual(self.pilot.speed, 0.3)

    def test_camera_sees_saved_settings(self):
        self.pilot.update_settings({"camera_quality": "high"})
        self.assertEqual(self.pilot.camera.settings["camera_quality"], "high")

    def test_auto_walk_can_be_disabled(self):
        self.pilot.update_settings({"auto_walk": False})
        self.pilot.connect("x")
        self.pilot.send_mode("standUp")
        self.pilot.drive([0, 0, 0, 0.3])
        self.assertEqual(self.pilot.client.modes, ["standUp"])


class DogScriptTest(unittest.TestCase):
    def test_go1cam_is_python36_compatible(self):
        # komputery kamer w Go1 mają Pythona 3.6
        source = (Path(server.__file__).parent / "go1cam.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 6))


if __name__ == "__main__":
    unittest.main()
