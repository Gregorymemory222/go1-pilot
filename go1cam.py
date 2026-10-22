"""Serwer podglądu kamery – uruchamiany przez Go1 Pilot NA komputerze kamer psa (Jetson, Python 3.6).

Czyta kamerę przez OpenCV i wysyła ją jako MJPEG każdemu, kto połączy się z portem.
Kamery Go1 są stereo (dwa obrazy obok siebie) – zostawiamy lewy obraz.
Gdy na danym Jetsonie Python nie ma OpenCV, obraz idzie przez gst-launch-1.0 (GStreamer z JetPacka).
Nie wolno tu używać składni nowszej niż Python 3.6.

Do Go1 Pilot wypisujemy tylko dwa znaczniki: GO1CAM-READY albo GO1CAM-ERROR <opis>.
Wszystko inne w logu (np. ostrzeżenia GStreamera) to tylko informacje.
"""
import argparse
import glob
import os
import socket
import subprocess
import sys
import threading
import time

try:
    import cv2
except ImportError:  # na niektórych Jetsonach psa OpenCV jest tylko dla C++
    cv2 = None


def ready():
    print("GO1CAM-READY", flush=True)


def fail(message):
    print("GO1CAM-ERROR " + message, flush=True)
    sys.exit(1)


def who_holds(device):
    """Nazwy programów, które trzymają /dev/videoN (do komunikatu o błędzie)."""
    names = []
    for fd in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            if os.readlink(fd) == "/dev/video%d" % device:
                pid = fd.split("/")[2]
                with open("/proc/%s/comm" % pid) as f:
                    names.append("%s (pid %s)" % (f.read().strip(), pid))
        except OSError:
            continue
    return sorted(set(names))


class Camera(object):
    def __init__(self, device, width, quality, test=False, fps=30):
        self.device, self.width, self.quality, self.test = device, width, quality, test
        self.min_gap = 1.0 / max(1, fps)  # ogranicza klatki przez Wi-Fi (siatka kamer)
        self.jpeg = None
        self.frame_id = 0
        self.cond = threading.Condition()

    def open(self):
        if self.test:
            return None
        if not os.path.exists("/dev/video%d" % self.device):
            raise RuntimeError("nie ma kamery /dev/video%d na tym komputerze" % self.device)
        # najpierw V4L2: domyślny backend na Jetsonie (GStreamer) potrafi nie otworzyć zwykłej kamery USB
        for backend in (getattr(cv2, "CAP_V4L2", None), None):
            cap = cv2.VideoCapture(self.device) if backend is None else cv2.VideoCapture(self.device, backend)
            if cap.isOpened():
                ok, frame = cap.read()
                if ok:
                    return cap
            cap.release()
        holders = who_holds(self.device)
        if holders:
            raise RuntimeError("kamera /dev/video%d jest zajęta przez: %s" % (self.device, ", ".join(holders)))
        raise RuntimeError("nie mogę otworzyć /dev/video%d (zajęta przez program, którego nie widać, "
                           "albo nietypowy format)" % self.device)

    def run(self, cap):
        params = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        n = 0
        last = 0.0
        while True:
            if self.test:
                frame = test_frame(n)
                n += 1
                time.sleep(1 / 15.0)
            else:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
            now = time.time()
            if now - last < self.min_gap:
                continue
            last = now
            h, w = frame.shape[:2]
            if w > 1.6 * h:  # stereo: lewy i prawy obraz obok siebie
                frame = frame[:, : w // 2]
                w //= 2
            if w > self.width:
                frame = cv2.resize(frame, (self.width, int(h * self.width / w)))
            ok, buf = cv2.imencode(".jpg", frame, params)
            if ok:
                with self.cond:
                    self.jpeg = buf.tobytes()
                    self.frame_id += 1
                    self.cond.notify_all()

    def frames(self):
        last = -1
        while True:
            with self.cond:
                self.cond.wait_for(lambda: self.frame_id != last, timeout=2)
                if self.frame_id == last:
                    continue
                last = self.frame_id
                jpeg = self.jpeg
            yield jpeg


def test_frame(n):
    import numpy as np
    img = np.zeros((400, 464, 3), np.uint8)
    img[:] = (60, 40, 20)
    cv2.circle(img, (232 + int(150 * np.sin(n / 10.0)), 200), 40, (255, 200, 90), -1)
    cv2.putText(img, "Go1 test %d" % n, (20, 380), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return img


def serve(camera, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(4)
    ready()
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=client, args=(camera, conn), daemon=True).start()


def client(camera, conn):
    try:
        conn.sendall(b"HTTP/1.0 200 OK\r\nCache-Control: no-store\r\n"
                     b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n")
        for jpeg in camera.frames():
            conn.sendall(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                         str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
    except (OSError, socket.error):
        pass
    finally:
        conn.close()


def gstreamer(args):
    """Bez OpenCV: GStreamer sam koduje JPEG i wystawia strumień MJPEG na porcie (obraz stereo w całości)."""
    if not os.path.exists("/dev/video%d" % args.device):
        fail("nie ma kamery /dev/video%d na tym komputerze" % args.device)
    pipeline = ("gst-launch-1.0 -q v4l2src device=/dev/video{d} ! videoconvert ! videoscale ! "
                "video/x-raw,width={w} ! videorate max-rate={fps} ! jpegenc quality={q} ! "
                "multipartmux boundary=frame ! tcpserversink host=127.0.0.1 port={p}").format(
        d=args.device, w=args.width * 2, fps=args.fps, q=args.quality, p=args.port)
    proc = subprocess.Popen(pipeline, shell=True, stderr=subprocess.PIPE)
    time.sleep(2.5)
    if proc.poll() is not None:
        err = proc.stderr.read().decode("utf-8", "replace").strip().splitlines()
        holders = who_holds(args.device)
        if holders:
            fail("kamera /dev/video%d jest zajęta przez: %s" % (args.device, ", ".join(holders)))
        fail("brak OpenCV, a GStreamer nie ruszył: " + (err[-1] if err else "kod %s" % proc.returncode))
    ready()
    proc.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--quality", type=int, default=70)
    ap.add_argument("--fps", type=int, default=30, help="najwyżej tyle klatek na sekundę")
    ap.add_argument("--test", action="store_true", help="obraz testowy zamiast kamery")
    args = ap.parse_args()
    if cv2 is None:
        return gstreamer(args)
    camera = Camera(args.device, args.width, args.quality, args.test, args.fps)
    try:
        cap = camera.open()
    except RuntimeError as e:
        fail(str(e))
    threading.Thread(target=camera.run, args=(cap,), daemon=True).start()
    serve(camera, args.port)


if __name__ == "__main__":
    main()
