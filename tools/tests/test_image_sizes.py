"""Tests for tools/image_sizes.py.   Run: python -m unittest discover tools/tests"""
from __future__ import annotations

import contextlib
import io
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import _blocks  # noqa: E402
import image_sizes  # noqa: E402

ETH_JPEG_AS_PNG = TOOLS.parent / "template" / "images" / "eth_zurich_aerial.png"


# ── synthetic image files ───────────────────────────────────────────────────

def png(w: int, h: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    rows = b"".join(b"\0" + b"\0\0\0" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def jpeg(w: int, h: int, orientation: int | None = None, sof: int = 0xC0) -> bytes:
    def seg(marker: int, body: bytes) -> bytes:
        return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body
    out = b"\xff\xd8" + seg(0xE0, b"JFIF\0\1\1\0\0\1\0\1\0\0")
    if orientation is not None:
        ifd = struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0) + b"\0\0\0\0"
        out += seg(0xE1, b"Exif\0\0" + b"II*\0" + struct.pack("<I", 8) + ifd)
    out += seg(0xDB, b"\0" + bytes(64))                 # DQT
    out += seg(0xC4, b"\0" + bytes(16))                 # DHT (in the C0-CF range, but no frame size)
    out += seg(sof, b"\x08" + struct.pack(">HH", h, w) + b"\x03" + bytes(9))
    return out + seg(0xDA, b"\x03" + bytes(9)) + b"\0\0\xff\xd9"


def gif(w: int, h: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\0\0\0;"


def webp(kind: bytes, body: bytes) -> bytes:
    payload = b"WEBP" + kind + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def webp_vp8(w: int, h: int) -> bytes:
    return webp(b"VP8 ", b"\0\0\0" + b"\x9d\x01\x2a" + struct.pack("<HH", w, h) + bytes(8))


def webp_vp8l(w: int, h: int) -> bytes:
    return webp(b"VP8L", b"\x2f" + ((w - 1) | (h - 1) << 14).to_bytes(4, "little") + bytes(4))


def webp_vp8x(w: int, h: int) -> bytes:
    return webp(b"VP8X", bytes(4) + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little"))


def svg(attrs: str) -> bytes:
    return f'<?xml version="1.0"?>\n<!-- <svg width="1" height="1"> -->\n<svg xmlns="http://www.w3.org/2000/svg" {attrs}></svg>'.encode()


def deck(user: str, engine_body: str = "<style>#deck img{}</style>", newline: str = "\n") -> str:
    text = (
        "<!DOCTYPE html>\n<html>\n<head><title>t</title></head>\n<body>\n"
        f'  <main id="deck">\n{user}\n  </main>\n'
        f"{_blocks.wrap(_blocks.DECK_ENGINE, '0.1.0', engine_body)}\n</body>\n</html>\n"
    )
    return text.replace("\n", newline)


class ImageSizeTest(unittest.TestCase):
    def assertSize(self, data: bytes, size: tuple[int, int]):
        self.assertEqual(tuple(image_sizes.image_size(data)), size)

    def test_png(self):
        self.assertSize(png(37, 21), (37, 21))

    def test_jpeg(self):
        self.assertSize(jpeg(640, 480), (640, 480))
        self.assertSize(jpeg(640, 480, sof=0xC2), (640, 480))         # progressive

    def test_jpeg_exif_orientation(self):
        self.assertSize(jpeg(640, 480, orientation=1), (640, 480))
        self.assertSize(jpeg(640, 480, orientation=3), (640, 480))    # 180°
        self.assertSize(jpeg(640, 480, orientation=6), (480, 640))    # 90°: browsers swap

    def test_jpeg_with_png_extension(self):
        data = ETH_JPEG_AS_PNG.read_bytes()
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertSize(data, (1760, 862))

    def test_gif(self):
        self.assertSize(gif(300, 200), (300, 200))

    def test_webp(self):
        self.assertSize(webp_vp8(320, 240), (320, 240))
        self.assertSize(webp_vp8l(321, 241), (321, 241))
        self.assertSize(webp_vp8x(4000, 3000), (4000, 3000))

    def test_svg(self):
        self.assertSize(svg('width="120" height="80px"'), (120, 80))
        self.assertSize(svg('viewBox="0 0 400 300"'), (400, 300))
        self.assertSize(svg('width="200" viewBox="0,0,400,300"'), (200, 150))
        self.assertSize(svg('width="100%" height="100%" viewBox="0 0 64 32"'), (64, 32))
        self.assertSize(svg('width="1in" height="72pt"'), (96, 96))
        with self.assertRaises(image_sizes.UnreadableImage):
            image_sizes.image_size(svg('width="100%"'))

    def test_unknown(self):
        for data in (b"", b"hello world", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff\xd9"):
            with self.assertRaises(image_sizes.UnreadableImage, msg=data):
                image_sizes.image_size(data)


class DeckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "images").mkdir()
        (self.dir / "images" / "a.png").write_bytes(png(40, 30))
        (self.dir / "images" / "photo.png").write_bytes(jpeg(800, 600))   # JPEG despite .png
        (self.dir / "images" / "my pic.gif").write_bytes(gif(10, 20))
        (self.dir / "images" / "junk.png").write_bytes(b"not an image")
        self.deck = self.dir / "Talk_presentation.html"

    def run_tool(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = image_sizes.main([str(self.deck), *args])
        return code, out.getvalue()

    def write(self, text: str) -> bytes:
        raw = text.encode("utf-8")
        self.deck.write_bytes(raw)
        return raw

    def test_insert_correct_unchanged(self):
        self.write(deck(
            '<img src="images/a.png" alt="a">\n'
            '<img class="x" src="images/photo.png" width="10" height="600" data-step="3"/>\n'
            '<img src="images/a.png" width="40" height="30">\n'
            "<IMG SRC='images/my%20pic.gif' Height=5>"
        ))
        code, out = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("3 updated, 1 already correct, 0 file missing, 0 unreadable", out)
        self.assertEqual(self.deck.read_text(encoding="utf-8"), deck(
            '<img src="images/a.png" width="40" height="30" alt="a">\n'
            '<img class="x" src="images/photo.png" width="800" height="600" data-step="3"/>\n'
            '<img src="images/a.png" width="40" height="30">\n'
            "<IMG SRC='images/my%20pic.gif' width=\"10\" Height=\"20\">"
        ))
        # second run: nothing to do, deck not rewritten
        self.deck.with_name(self.deck.name + ".bak").unlink()
        code, out = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("0 updated, 4 already correct", out)
        self.assertFalse(self.deck.with_name(self.deck.name + ".bak").exists())

    def test_backup_and_line_endings(self):
        raw = self.write(deck('<img src="images/a.png">\n<p>Grüße – ✓</p>', newline="\r\n"))
        self.assertEqual(self.run_tool()[0], 0)
        self.assertEqual(self.deck.with_name(self.deck.name + ".bak").read_bytes(), raw)
        new = self.deck.read_bytes()
        self.assertEqual(new, raw.replace(b'<img src="images/a.png">', b'<img src="images/a.png" width="40" height="30">'))
        self.assertNotIn(b"\n", new.replace(b"\r\n", b""))

    def test_missing_and_unreadable_left_unchanged(self):
        raw = self.write(deck(
            '<img src="images/gone.png">\n<img src="images/junk.png" width="1" height="1">\n'
            '<img src="data:image/png;base64,AAAA">\n<img src="https://example.com/x.png">\n<img alt="no src">'
        ))
        code, out = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("0 updated, 0 already correct, 1 file missing, 1 unreadable, 3 skipped", out)
        self.assertIn("placeholder", out)
        self.assertEqual(self.deck.read_bytes(), raw)
        self.assertFalse(self.deck.with_name(self.deck.name + ".bak").exists())
        code, out = self.run_tool("--check")       # missing/unreadable do not fail the check
        self.assertEqual(code, 0)

    def test_engine_block_and_non_markup_untouched(self):
        engine = '<main id="deck"><img src="images/a.png"></main><script>x = "<img src=\'images/a.png\'>";</script>'
        user = ('<!-- <img src="images/a.png"> -->\n'
                '<script>const t = \'<img src="images/a.png">\';</script>\n'
                '<style>/* <img src="images/a.png"> */</style>\n'
                '<img src="images/a.png">')
        text = deck(user, engine_body=engine)
        self.write(text)
        code, out = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("1 updated", out)
        new = self.deck.read_text(encoding="utf-8")
        last = '\n<img src="images/a.png">\n  </main>'
        self.assertEqual(text.count(last), 1)
        self.assertEqual(new, text.replace(last, '\n<img src="images/a.png" width="40" height="30">\n  </main>'))
        self.assertEqual(_blocks.find(new, _blocks.DECK_ENGINE)[0][0], _blocks.find(text, _blocks.DECK_ENGINE)[0][0])

    def test_real_template_has_nothing_to_do(self):
        template = TOOLS.parent / "template" / "template_presentation.html"
        self.deck = template
        code, out = self.run_tool("--check")
        self.assertEqual(code, 0)
        self.assertIn("0 to update", out)

    def test_check_exit_codes(self):
        raw = self.write(deck('<img src="images/a.png" width="40">'))
        code, out = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("1 to update", out)
        self.assertEqual(self.deck.read_bytes(), raw)
        self.assertFalse(self.deck.with_name(self.deck.name + ".bak").exists())
        self.assertEqual(self.run_tool()[0], 0)
        self.assertEqual(self.run_tool("--check")[0], 0)
        # as a script
        proc = subprocess.run([sys.executable, str(TOOLS / "image_sizes.py"), str(self.deck), "--check"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_errors(self):
        self.write("<html><body><main id='other'><img src='images/a.png'></main></body></html>")
        code, out = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn('no <main id="deck">', out)
        self.deck = self.dir / "nope.html"
        self.assertEqual(self.run_tool()[0], 2)


if __name__ == "__main__":
    unittest.main()
