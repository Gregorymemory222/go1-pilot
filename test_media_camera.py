import socket
import struct
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import settings
from camera import Stream
from media import AviWriter, MjpegParser, jpeg_size
from server import Handler, Pilot
from test_pilot import FakeClient


def fake_jpeg(width=64, height=48, filler=b"x" * 10):
    """Minimalny „JPEG” z nagłówkiem SOF0 – wystarczy do sprawdzenia rozmiaru i zapisu."""
    sof = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + bytes(12)
    return b"\xff\xd8" + sof + filler + b"\xff\xd9"


def part(jpeg):
    return b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"


class MediaTest(unittest.TestCase):
    def test_parser_reassembles_frames_split_anywhere(self):
        frames = [fake_jpeg(filler=bytes([i]) * 50) for i in range(3)]
        stream = b"HTTP/1.0 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n"
        stream += b"".join(part(f) for f in frames)
        for size in (1, 7, 64, len(stream)):
            parser, got = MjpegParser(), []
            for i in range(0, len(stream), size):
                got += parser.feed(stream[i:i + size])
            self.assertEqual(got, frames, f"kawałki po {size} B")

    def test_jpeg_size(self):
        self.assertEqual(jpeg_size(fake_jpeg(928, 800)), (928, 800))
        self.assertIsNone(jpeg_size(b"nie jpeg"))

    def test_avi_structure(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.avi"
            writer = AviWriter(path, 64, 48)
            for i in range(5):
                writer.add(fake_jpeg(filler=bytes([i]) * (i + 1)))  # różne, też nieparzyste rozmiary
            writer.close(fps=12.4)
            data = path.read_bytes()
        self.assertEqual(data[:4], b"RIFF")
        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)
        self.assertEqual(data[8:12], b"AVI ")
        avih = data.index(b"avih") + 8
        usec, _, _, flags, frames = struct.unpack("<5I", data[avih:avih + 20])
        self.assertEqual((usec, flags, frames), (1_000_000 // 12, 0x10, 5))
        idx = data.index(b"idx1")
        self.assertEqual(struct.unpack("<I", data[idx + 4:idx + 8])[0], 5 * 16)
        movi = data.index(b"movi")
        first_offset = struct.unpack("<I", data[idx + 16:idx + 20])[0]
        self.assertEqual(data[movi + first_offset:movi + first_offset + 4], b"00dc")


class CameraFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pilot = Pilot(client_factory=FakeClient, settings=settings.clean({}), save=lambda s: None,
                           media_dir=Path(self.tmp.name))
        self.stream = Stream(0)
        self.stream.state = "on"
        self.pilot.camera.streams[0] = self.stream

    def tearDown(self):
        self.tmp.cleanup()

    def test_photo_saves_latest_frame(self):
        self.stream.put(fake_jpeg(filler=b"A"))
        self.stream.put(fake_jpeg(filler=b"B"))
        self.pilot.snapshot()
        photos = list(self.pilot.photo_dir.glob("*.jpg"))
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0].read_bytes(), fake_jpeg(filler=b"B"))

    def test_photo_without_image_is_an_error(self):
        self.pilot.camera.streams.clear()
        with self.assertRaises(ValueError):
            self.pilot.snapshot()

    def test_recording_writes_every_new_frame(self):
        self.stream.put(fake_jpeg())
        self.pilot.set_recording(True)
        self.assertIsNotNone(self.pilot.state()["camera"]["recording"])
        for i in range(6):
            time.sleep(0.05)
            self.stream.put(fake_jpeg(filler=bytes([i]) * 20))
        time.sleep(0.1)
        self.pilot.set_recording(False)
        for _ in range(30):
            if self.pilot.recording is None:
                break
            time.sleep(0.1)
        videos = list(self.pilot.video_dir.glob("*.avi"))
        self.assertEqual(len(videos), 1)
        data = videos[0].read_bytes()
        frames = struct.unpack("<I", data[data.index(b"avih") + 24:data.index(b"avih") + 28])[0]
        self.assertGreaterEqual(frames, 6)
        self.assertIn("Zapisano nagranie", self.pilot.saved)

    def test_switching_main_camera_stops_recording(self):
        self.stream.put(fake_jpeg())
        self.pilot.set_recording(True)
        self.pilot.camera.start = lambda *a, **k: None  # bez prawdziwego SSH
        self.pilot.set_camera(True, 1)
        self.assertTrue(self.pilot.recording is None or self.pilot.recording["stop"].is_set())

    def test_leaving_grid_restarts_main_camera_at_full_quality(self):
        started = []
        link = self.pilot.camera
        link._jobs.put = lambda job: started.append(job[1])  # bez prawdziwego SSH
        link.streams.clear()
        link.start("pies", range(3), fps=8)
        link.streams[1].state = "on"
        link.start("pies", [1], fps=30)
        self.assertEqual(started[-1], ("pies", 1, 30))
        self.assertEqual(link.streams[1].fps, 30)
        link.start("pies", [1], fps=8)  # siatka nie psuje już płynnej kamery
        self.assertEqual(len(started), 4)

    def _serve(self):
        Handler.pilot = self.pilot
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd.server_address

    def _get(self, address, path, read_for=0.0):
        sock = socket.create_connection(address)
        sock.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode())
        sock.settimeout(0.5)
        data, end = b"", time.monotonic() + read_for
        try:
            while chunk := sock.recv(65536):
                data += chunk
                if read_for and time.monotonic() > end:
                    break
        except socket.timeout:
            pass
        sock.close()
        return data

    def test_single_frame_endpoint(self):
        self.stream.put(fake_jpeg(filler=b"K"))
        reply = self._get(self._serve(), "/camera.jpg?cam=0")
        self.assertIn(b"200", reply.split(b"\r\n")[0])
        self.assertTrue(reply.endswith(fake_jpeg(filler=b"K")))

    def test_stream_endpoint_sends_multipart_frames(self):
        address = self._serve()
        self.stream.put(fake_jpeg(filler=b"1"))
        threading.Timer(0.2, lambda: self.stream.put(fake_jpeg(filler=b"2"))).start()
        reply = self._get(address, "/camera.mjpg?cam=0", read_for=0.6)
        self.assertIn(b"multipart/x-mixed-replace", reply)
        body = reply[reply.index(b"\r\n\r\n") + 4:]
        self.assertEqual(MjpegParser().feed(body), [fake_jpeg(filler=b"1"), fake_jpeg(filler=b"2")])

    def test_camera_off_gives_503(self):
        reply = self._get(self._serve(), "/camera.jpg?cam=3")
        self.assertIn(b"503", reply.split(b"\r\n")[0])


if __name__ == "__main__":
    unittest.main()
