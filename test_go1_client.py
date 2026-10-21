import struct
import time
import unittest
from types import SimpleNamespace

from go1_client import Go1Client, pack_stick


class FakeMqtt:
    def __init__(self):
        self.published = []

    def connect_async(self, host, port, keepalive):
        self.on_connect(self, None, None, SimpleNamespace(is_failure=False), None)

    def subscribe(self, topic):
        self.subscribed = topic

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def publish(self, topic, payload, qos):
        self.published.append((topic, payload, qos))
        return SimpleNamespace(wait_for_publish=lambda timeout: None)


class Go1ClientTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMqtt()
        self.client = Go1Client(mqtt_client=self.fake)
        self.client.connect()

    def tearDown(self):
        self.client.disconnect()

    def test_stick_is_four_little_endian_floats_clamped(self):
        payload = pack_stick(-2, 0.5, 0, 1)
        self.assertEqual(struct.unpack("<4f", payload), (-1.0, 0.5, 0.0, 1.0))

    def test_mode_goes_to_controller_action_with_qos1(self):
        self.client.send_mode("standUp")
        self.assertIn(("controller/action", "standUp", 1), self.fake.published)

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            self.client.send_mode("backflip")

    def test_stick_streamed_periodically(self):
        self.client.set_stick(0, 0, 0, 0.4)
        time.sleep(0.35)
        sticks = [p for t, p, _ in self.fake.published if t == "controller/stick"]
        self.assertGreaterEqual(len(sticks), 2)
        self.assertAlmostEqual(struct.unpack("<4f", sticks[-1])[3], 0.4, places=5)

    def test_battery_read_from_bms_state(self):
        self.assertEqual(self.fake.subscribed, "bms/state")
        payload = bytes([1, 2, 0, 87]) + bytes(30)
        self.fake.on_message(self.fake, None, SimpleNamespace(topic="bms/state", payload=payload))
        self.assertEqual(self.client.battery, 87)

    def test_jump_is_a_known_mode(self):
        self.client.send_mode("jumpYaw")
        self.assertIn(("controller/action", "jumpYaw", 1), self.fake.published)

    def test_disconnect_sends_zero_stick(self):
        self.client.set_stick(0, 0, 0, 1)
        self.client.disconnect()
        topic, payload, _ = self.fake.published[-1]
        self.assertEqual((topic, struct.unpack("<4f", payload)), ("controller/stick", (0, 0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
