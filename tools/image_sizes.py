"""Write every deck image's natural pixel size into its <img> tag (SPEC §10.2).

    python tools/image_sizes.py MyTalk/MyTalk_presentation.html           insert/correct width + height
    python tools/image_sizes.py MyTalk/MyTalk_presentation.html --check   write nothing; exit 1 if any
                                                                          attribute is missing or wrong

Only <img src="..."> tags inside <main id="deck"> are touched (never the DECK-ENGINE block,
comments, <script> or <style>). Each src is resolved relative to the deck file and its size is
read from the file header: PNG, JPEG (EXIF orientation applied, as browsers do), GIF, WebP, SVG.
The format is detected by content, not by extension. Files that are missing or unreadable are
reported and their tags left unchanged; they do not affect the exit code.

Edits are minimal: existing width/height values are replaced in place, missing attributes are
inserted after src (width) and after width (height). Everything else is preserved byte-for-byte.
The original is saved as <deck>.html.bak before writing.
"""
from __future__ import annotations

import argparse
import html
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _blocks  # noqa: E402

ATTR_VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+)"""
IMG_RE = re.compile(r"""<img\b(?:"[^"]*"|'[^']*'|[^'">])*>""", re.I)
ATTR_RE = re.compile(rf"""(?P<name>[^\s"'>/=]+)(?:\s*=\s*(?P<value>{ATTR_VALUE}))?""")
MAIN_RE = re.compile(r"""<main\b(?:"[^"]*"|'[^']*'|[^'">])*>""", re.I)
MAIN_END_RE = re.compile(r"</main\s*>", re.I)
# Regions inside the user zone that are not markup: an <img> there is text, not an element.
OPAQUE_RE = re.compile(r"<!--.*?-->|<(script|style|textarea|title)\b[^>]*>.*?</\1\s*>", re.I | re.S)
URL_SCHEME_RE = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//)", re.I)


class DeckError(Exception):
    pass


class UnreadableImage(Exception):
    pass


# ── image headers ─────────────────────────────────────────────────────────────

def image_size(data: bytes) -> tuple[int, int]:
    """Natural (width, height) in CSS pixels as a browser reports it, or UnreadableImage."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _png(data)
    if data.startswith(b"\xff\xd8"):
        return _jpeg(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        if len(data) < 10:
            raise UnreadableImage("truncated GIF")
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp(data)
    if _looks_like_svg(data):
        return _svg(data)
    raise UnreadableImage("unknown image format")


def _png(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise UnreadableImage("PNG without IHDR")
    return struct.unpack(">II", data[16:24])


# SOFn markers carry the frame size; C4 (DHT), C8 (JPG) and CC (DAC) share the range but do not.
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg(data: bytes) -> tuple[int, int]:
    i, orientation = 2, 1
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise UnreadableImage("corrupt JPEG marker")
        marker = data[i + 1]
        if marker == 0xFF:            # fill byte
            i += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD8)):   # stand-alone markers
            i += 2
            continue
        if marker in (0xD9, 0xDA):    # EOI / start of scan before any frame header
            break
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        segment = data[i + 4:i + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\0\0"):
            orientation = _exif_orientation(segment[6:]) or orientation
        elif marker in _SOF:
            if len(segment) < 5:
                raise UnreadableImage("truncated JPEG frame header")
            h, w = struct.unpack(">HH", segment[1:5])
            # Browsers apply EXIF orientation by default (image-orientation: from-image);
            # orientations 5-8 rotate by 90°, so the natural size is swapped.
            return (h, w) if orientation in (5, 6, 7, 8) else (w, h)
        i += 2 + length
    raise UnreadableImage("JPEG without frame header")


def _exif_orientation(tiff: bytes) -> int | None:
    try:
        endian = {b"II": "<", b"MM": ">"}[tiff[:2]]
        ifd = struct.unpack(endian + "I", tiff[4:8])[0]
        count = struct.unpack(endian + "H", tiff[ifd:ifd + 2])[0]
        for k in range(count):
            entry = tiff[ifd + 2 + 12 * k: ifd + 14 + 12 * k]
            tag, typ = struct.unpack(endian + "HH", entry[:4])
            if tag == 0x0112 and typ == 3:
                return struct.unpack(endian + "H", entry[8:10])[0]
    except (KeyError, struct.error):
        pass
    return None


def _webp(data: bytes) -> tuple[int, int]:
    chunk, body = data[12:16], data[20:]
    if chunk == b"VP8X" and len(body) >= 10:
        return (int.from_bytes(body[4:7], "little") + 1, int.from_bytes(body[7:10], "little") + 1)
    if chunk == b"VP8 " and len(body) >= 10 and body[3:6] == b"\x9d\x01\x2a":
        w, h = struct.unpack("<HH", body[6:10])
        return (w & 0x3FFF, h & 0x3FFF)
    if chunk == b"VP8L" and len(body) >= 5 and body[0] == 0x2F:
        bits = int.from_bytes(body[1:5], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    raise UnreadableImage("unsupported WebP chunk")


def _looks_like_svg(data: bytes) -> bool:
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<?xml", b"<svg", b"<!--", b"<!doctype svg")) and b"<svg" in data[:65536].lower()


# Absolute CSS units → px (96 dpi). Percentages and font-relative units have no natural size.
_UNITS = {"": 1, "px": 1, "in": 96, "cm": 96 / 2.54, "mm": 96 / 25.4, "q": 96 / 101.6, "pt": 96 / 72, "pc": 16}
_LENGTH_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:e[+-]?[0-9]+)?)\s*([a-z]*)\s*$", re.I)


def _svg_length(value: str | None) -> float | None:
    m = _LENGTH_RE.match(value or "")
    if not m or m[2].lower() not in _UNITS:
        return None
    return float(m[1]) * _UNITS[m[2].lower()]


def _svg(data: bytes) -> tuple[int, int]:
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"<!--.*?-->|<\?.*?\?>|<!DOCTYPE[^>\[]*(?:\[.*?\])?\s*>", "", text, flags=re.S | re.I)
    m = re.search(r"<svg\b((?:\"[^\"]*\"|'[^']*'|[^'\">])*)>", text, re.I)
    if not m:
        raise UnreadableImage("SVG without <svg> root")
    attrs = {a["name"].lower(): _unquote(a["value"]) for a in ATTR_RE.finditer(m[1])}
    w, h = _svg_length(attrs.get("width")), _svg_length(attrs.get("height"))
    try:
        box = [float(v) for v in re.split(r"[\s,]+", (attrs.get("viewbox") or "").strip())]
    except ValueError:
        box = []
    if len(box) == 4 and box[2] > 0 and box[3] > 0:
        ratio = box[2] / box[3]
        if w is None and h is None:
            w, h = box[2:]
        elif w is None:
            w = h * ratio
        elif h is None:
            h = w / ratio
    if w is None or h is None or w <= 0 or h <= 0:
        raise UnreadableImage("SVG without absolute width/height or viewBox")
    return (round(w), round(h))


# ── deck scanning ─────────────────────────────────────────────────────────────

@dataclass
class ImgTag:
    start: int                 # offset of "<img" in the deck text
    end: int
    tag: str
    src: str | None            # attribute value, entities decoded; None without src
    line: int


def _unquote(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return html.unescape(value)


def _attrs(tag: str, skip: int = 4) -> dict[str, re.Match]:
    """Attribute name (lower case) → match within tag (after the first `skip` chars, i.e. "<img");
    the first occurrence wins, as in HTML."""
    found: dict[str, re.Match] = {}
    for m in ATTR_RE.finditer(tag, skip):
        found.setdefault(m["name"].lower(), m)
    return found


def _attr(tag: str, name: str, skip: int = 4) -> str | None:
    m = _attrs(tag, skip).get(name)
    return _unquote(m["value"]) if m else None


def user_zone(text: str) -> tuple[int, int]:
    """(start, end) of the contents of <main id="deck">, ignoring anything inside an engine block."""
    engine = [(m.start(), m.end()) for m in _blocks.find(text, _blocks.DECK_ENGINE)]
    inside_engine = lambda pos: any(a <= pos < b for a, b in engine)   # noqa: E731
    start = next((m.end() for m in MAIN_RE.finditer(text)
                  if not inside_engine(m.start()) and _attr(m[0], "id", skip=5) == "deck"), None)
    if start is None:
        raise DeckError('no <main id="deck"> found')
    end = next((m.start() for m in MAIN_END_RE.finditer(text, start) if not inside_engine(m.start())), None)
    if end is None:
        raise DeckError('<main id="deck"> is not closed')
    for a, b in engine:
        if a < end and b > start:
            raise DeckError("DECK-ENGINE block inside <main id=\"deck\">")
    return start, end


def find_images(text: str) -> list[ImgTag]:
    start, end = user_zone(text)
    zone = text[start:end]
    masked = OPAQUE_RE.sub(lambda m: " " * len(m[0]), zone)
    tags = []
    for m in IMG_RE.finditer(masked):
        tag = zone[m.start():m.end()]
        tags.append(ImgTag(start + m.start(), start + m.end(), tag, _attr(tag, "src"),
                           text.count("\n", 0, start + m.start()) + 1))
    return tags


def resolve(deck: Path, src: str) -> Path | None:
    """Local file for src relative to the deck, or None for URLs/data URIs."""
    src = src.strip()
    if not src or URL_SCHEME_RE.match(src):
        return None
    path = unquote(re.split(r"[?#]", src, maxsplit=1)[0])
    return deck.parent / path


def fix_tag(tag: str, w: int, h: int) -> str:
    """tag with width="w" height="h"; existing values replaced in place, missing ones inserted."""
    for name, value, after in (("width", w, "src"), ("height", h, "width")):
        attrs = _attrs(tag)
        cur = attrs.get(name)
        if cur is not None:
            if (_attr(tag, name) or "").strip() != str(value):
                tag = tag[:cur.start()] + f'{cur["name"]}="{value}"' + tag[cur.end():]
        else:
            anchor = attrs[after].end()
            tag = tag[:anchor] + f' {name}="{value}"' + tag[anchor:]
    return tag


def sizes_ok(tag: str, w: int, h: int) -> bool:
    return all((_attr(tag, name) or "").strip() == str(v) for name, v in (("width", w), ("height", h)))


# ── command line ──────────────────────────────────────────────────────────────

@dataclass
class Result:
    text: str                                   # new deck text
    rows: list[tuple[str, ImgTag, str]]         # (status, tag, detail)

    def count(self, status: str) -> int:
        return sum(1 for s, _, _ in self.rows if s == status)


def process(deck: Path, text: str) -> Result:
    rows, out, pos, cache = [], [], 0, {}
    for img in find_images(text):
        path = resolve(deck, img.src) if img.src is not None else None
        if path is None:
            rows.append(("skipped", img, "no src" if img.src is None else "not a local file"))
            continue
        key = path.resolve()
        if key not in cache:
            try:
                cache[key] = image_size(path.read_bytes())
            except FileNotFoundError:
                cache[key] = "missing"
            except (OSError, UnreadableImage) as e:
                cache[key] = e
        size = cache[key]
        if size == "missing":
            sized = _attr(img.tag, "width") and _attr(img.tag, "height")
            rows.append(("missing", img, "file not found; the engine shows a placeholder"
                         + ("" if sized else " - no width/height, so its size is a guess")))
        elif isinstance(size, Exception):
            rows.append(("unreadable", img, str(size) or type(size).__name__))
        elif sizes_ok(img.tag, *size):
            rows.append(("ok", img, f"{size[0]}x{size[1]}"))
        else:
            rows.append(("updated", img, f"{size[0]}x{size[1]}"))
            out += [text[pos:img.start], fix_tag(img.tag, *size)]
            pos = img.end
    return Result("".join(out) + text[pos:], rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck", type=Path, help="deck file (…_presentation.html)")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if any width/height is missing or wrong")
    args = ap.parse_args(argv)

    try:
        raw = args.deck.read_bytes()
        # surrogateescape keeps any non-UTF-8 bytes intact; newline handling is untouched (bytes I/O).
        text = raw.decode("utf-8", errors="surrogateescape")
        result = process(args.deck, text)
    except (OSError, DeckError) as e:
        print(f"error: {args.deck}: {e}", file=sys.stderr)
        return 2

    labels = {"updated": "wrong/missing" if args.check else "updated"}
    for status, img, detail in result.rows:
        print(f"{labels.get(status, status):<13} line {img.line:<5} {img.src or '<img>'}  ({detail})")

    n_upd = result.count("updated")
    summary = (f"{n_upd} {'to update' if args.check else 'updated'}, {result.count('ok')} already correct, "
               f"{result.count('missing')} file missing, {result.count('unreadable')} unreadable")
    if result.count("skipped"):
        summary += f", {result.count('skipped')} skipped"
    print(summary)

    if args.check:
        if n_upd:
            print(f"run: python tools/image_sizes.py {args.deck}")
        return 1 if n_upd else 0
    if n_upd:
        backup = args.deck.with_name(args.deck.name + ".bak")
        backup.write_bytes(raw)
        args.deck.write_bytes(result.text.encode("utf-8", errors="surrogateescape"))
        print(f"wrote {args.deck} (backup: {backup.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
