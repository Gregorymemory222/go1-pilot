"""Klatki MJPEG: odczyt ze strumienia go1cam.py i zapis nagrania do pliku AVI (MJPEG, bez przekodowania)."""
import struct

BOUNDARY = b"--frame\r\n"


class MjpegParser:
    """Składa klatki JPEG z kawałków strumienia multipart (format z go1cam.py)."""

    def __init__(self):
        self._buf = b""

    def feed(self, data):
        self._buf += data
        frames = []
        while True:
            start = self._buf.find(BOUNDARY)
            if start < 0:
                self._buf = self._buf[-len(BOUNDARY):]  # zostaw ogon – granica mogła się przeciąć
                return frames
            head_end = self._buf.find(b"\r\n\r\n", start)
            if head_end < 0:
                self._buf = self._buf[start:]
                return frames
            length = None
            for line in self._buf[start + len(BOUNDARY):head_end].split(b"\r\n"):
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value.strip())
            body = head_end + 4
            if length is None:  # bez długości (np. GStreamer): klatka kończy się na następnej granicy
                end = self._buf.find(BOUNDARY, body)
                if end < 0:
                    self._buf = self._buf[start:]
                    return frames
                frames.append(self._buf[body:end].rstrip(b"\r\n"))
                self._buf = self._buf[end:]
                continue
            if len(self._buf) < body + length:
                self._buf = self._buf[start:]
                return frames
            frames.append(self._buf[body:body + length])
            self._buf = self._buf[body + length:]


def jpeg_size(jpeg):
    """(szerokość, wysokość) z nagłówka SOF obrazu JPEG albo None."""
    i = 2
    while i + 9 < len(jpeg):
        if jpeg[i] != 0xFF:
            return None
        marker = jpeg[i + 1]
        length = struct.unpack(">H", jpeg[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", jpeg[i + 5:i + 9])
            return width, height
        i += 2 + length
    return None


class AviWriter:
    """Plik AVI z klatkami MJPEG. Nagłówki (liczba klatek, fps) uzupełniane przy zamknięciu."""

    def __init__(self, path, width, height):
        self.path, self.width, self.height = path, width, height
        self.f = open(path, "wb")
        self.index = []  # (przesunięcie względem 'movi', rozmiar)
        self._write_headers(fps=15, frames=0)
        self.movi_pos = self.f.tell() - 4  # pozycja FOURCC 'movi'

    def add(self, jpeg):
        pos = self.f.tell()
        self.f.write(b"00dc" + struct.pack("<I", len(jpeg)) + jpeg)
        if len(jpeg) % 2:
            self.f.write(b"\0")
        self.index.append((pos - self.movi_pos, len(jpeg)))

    def close(self, fps):
        movi_end = self.f.tell()
        self.f.write(b"idx1" + struct.pack("<I", 16 * len(self.index)))
        for offset, size in self.index:
            self.f.write(b"00dc" + struct.pack("<III", 0x10, offset, size))  # 0x10 = klatka kluczowa
        end = self.f.tell()
        self.f.seek(0)
        self._write_headers(fps=fps, frames=len(self.index), riff_size=end - 8, movi_size=movi_end - self.movi_pos)
        self.f.close()

    def _write_headers(self, fps, frames, riff_size=0, movi_size=4):
        fps = max(1, round(fps))
        w, h = self.width, self.height
        largest = max((size for _, size in self.index), default=w * h)
        avih = struct.pack("<10I4I", 1_000_000 // fps, largest * fps, 0, 0x10, frames, 0, 1, largest, w, h, 0, 0, 0, 0)
        # fccType, fccHandler, flags, priority, language, initialFrames, scale, rate, start, length,
        # suggestedBufferSize, quality (-1 = domyślna), sampleSize, rcFrame
        strh = struct.pack("<4s4sIHHIIIIIIiI4h", b"vids", b"MJPG", 0, 0, 0, 0, 1, fps, 0, frames, largest, -1, 0,
                           0, 0, w, h)
        assert len(avih) == 56 and len(strh) == 56
        strf = struct.pack("<IiiHH4sIiiII", 40, w, h, 1, 24, b"MJPG", w * h * 3, 0, 0, 0, 0)
        strl = _list(b"strl", _chunk(b"strh", strh) + _chunk(b"strf", strf))
        hdrl = _list(b"hdrl", _chunk(b"avih", avih) + strl)
        self.f.write(b"RIFF" + struct.pack("<I", riff_size) + b"AVI " + hdrl)
        self.f.write(b"LIST" + struct.pack("<I", movi_size) + b"movi")


def _chunk(fourcc, data):
    return fourcc + struct.pack("<I", len(data)) + data


def _list(kind, data):
    return b"LIST" + struct.pack("<I", len(data) + 4) + kind + data
