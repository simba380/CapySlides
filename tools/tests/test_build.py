"""Tests for the P0 build pipeline.   Run: python -m unittest discover tools/tests"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import _blocks  # noqa: E402
import build  # noqa: E402
import fetch_vendor  # noqa: E402

KATEX_FAMILIES = (
    "KaTeX_AMS", "KaTeX_Caligraphic", "KaTeX_Fraktur", "KaTeX_Main", "KaTeX_Math",
    "KaTeX_SansSerif", "KaTeX_Script", "KaTeX_Size1", "KaTeX_Size2", "KaTeX_Size3",
    "KaTeX_Size4", "KaTeX_Typewriter",
)
RESOURCE_RE = re.compile(r"""(?:\b(?:src|href)\s*=\s*["']?|url\(\s*["']?|@import\s+["'])(?P<ref>[^"')\s>]*)""", re.I)


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outputs = build.build_outputs()
        cls.deck = cls.outputs["template_presentation.html"].decode("utf-8")
        cls.anim = cls.outputs["template_animations.html"].decode("utf-8")

    def test_markers_exactly_once_and_ordered(self):
        version = (build.ENGINE / "VERSION").read_text(encoding="utf-8").strip()
        for html, names in ((self.deck, _blocks.DECK_BLOCKS), (self.anim, _blocks.ANIM_BLOCKS)):
            positions = []
            for name in names:
                self.assertEqual(html.count(_blocks.begin(name, version)), 1, name)
                self.assertEqual(html.count(_blocks.end(name)), 1, name)
                self.assertEqual(_blocks.version_of(html, name), version)
                positions.append(html.index(_blocks.begin(name, version)))
                self.assertLess(html.index(_blocks.begin(name, version)), html.index(_blocks.end(name)))
            self.assertEqual(positions, sorted(positions))
        # vendor block in <head>, contract at the end of <body>
        marker = lambda html, name: html.index(f"<!-- {name}:BEGIN")   # comments may mention block names
        self.assertLess(marker(self.anim, _blocks.ANIM_VENDOR), self.anim.index("</head>"))
        self.assertGreater(marker(self.anim, _blocks.ANIM_CONTRACT), self.anim.index("<body"))
        self.assertGreater(marker(self.deck, _blocks.DECK_ENGINE), self.deck.index('<main id="deck">'))

    def test_no_placeholders_left(self):
        for html in (self.deck, self.anim):
            self.assertNotIn("<!-- @@", html)
            self.assertNotIn("__ENGINE_VERSION__", html)

    def test_offline_no_external_or_relative_resources(self):
        allowed_relative = {"images/eth_zurich_main_building.jpg"}  # user content, resolved next to the deck
        for name, html in (("deck", self.deck), ("anim", self.anim)):
            # Scan markup and CSS; inline script bodies are code, not resource references.
            markup = re.sub(r"(<script\b[^>]*>).*?(</script>)", r"\1\2", html, flags=re.S | re.I)
            for m in RESOURCE_RE.finditer(markup):
                ref = m["ref"]
                if not ref or ref.startswith(("data:", "#")) or ref in allowed_relative:
                    continue
                self.fail(f"{name}: non-inlined resource reference {ref[:80]!r}")

    def test_every_font_face_is_inlined(self):
        for html in (self.deck, self.anim):
            faces = re.findall(r"@font-face\s*\{[^}]*\}", html)
            self.assertTrue(faces)
            for face in faces:
                self.assertRegex(face, r"src:\s*url\(data:font/woff2;base64,[A-Za-z0-9+/=]+\)")
                self.assertNotIn("format(\"woff\")", face)

    def test_font_families_present(self):
        def families(html):
            return set(re.findall(r"font-family:\s*'?([A-Za-z0-9_ ]+?)'?\s*;", html))
        deck, anim = families(self.deck), families(self.anim)
        for fam in ("Inter", "Fira Code", *KATEX_FAMILIES):
            self.assertIn(fam, deck)
        for fam in ("DM Sans", "DM Serif Display", "DM Mono", *KATEX_FAMILIES):
            self.assertIn(fam, anim)
        self.assertNotIn("Inter Variable", self.deck)

    def test_scripts_are_not_terminated_early(self):
        for html in (self.deck, self.anim):
            opens = len(re.findall(r"<script\b", html, re.I))
            closes = len(re.findall(r"</script>", html, re.I))
            self.assertEqual(opens, closes)

    def test_deterministic(self):
        build.deck_engine_block.cache_clear()
        self.assertEqual(build.build_outputs(), self.outputs)

    def test_cascade_layers(self):
        # Deck: layer order declared before any layered rule; vendor CSS layered, reset below it.
        vendor_css = self.deck[self.deck.index('<style id="deck-vendor-css">'):]
        self.assertTrue(vendor_css.split("\n", 2)[1] == build.DECK_LAYER_ORDER)
        self.assertIn("@layer vendor {", vendor_css)
        self.assertIn(build.DECK_LAYER_ORDER, (build.ENGINE / "deck.css").read_text(encoding="utf-8"))
        # Animations: vendor CSS stays unlayered (page CSS like `* {margin:0}` must not beat KaTeX).
        anim_vendor = self.anim[self.anim.index('<style id="anim-vendor-css">'):self.anim.index("</style>")]
        self.assertNotIn("@layer", anim_vendor)

    def test_check_detects_stale_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(sorted(build.stale(self.outputs, out)), sorted(self.outputs))
            for rel, data in self.outputs.items():
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                (out / rel).write_bytes(data)
            self.assertEqual(build.stale(self.outputs, out), [])
            (out / "template_presentation.html").write_bytes(b"changed")
            self.assertEqual(build.stale(self.outputs, out), ["template_presentation.html"])


class VendorTest(unittest.TestCase):
    def test_vendor_matches_lock(self):
        self.assertEqual(fetch_vendor.verify(), [])

    def test_tampered_file_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            vendor = Path(tmp) / "vendor"
            shutil.copytree(fetch_vendor.VENDOR, vendor)
            lock = json.loads((vendor / "lock.json").read_text(encoding="utf-8"))["files"]
            victim = sorted(lock)[0]
            (vendor / victim).write_bytes((vendor / victim).read_bytes() + b"x")
            problems = fetch_vendor.verify(vendor, vendor / "lock.json")
            self.assertEqual(problems, [f"hash mismatch: {victim}"])


class BlocksTest(unittest.TestCase):
    def test_replace_requires_exactly_one_block(self):
        block = _blocks.wrap("X-BLOCK", "1.2.3", "old")
        doc = f"a\n{block}\nb"
        new = _blocks.replace(doc, "X-BLOCK", _blocks.wrap("X-BLOCK", "1.3.0", "new"))
        self.assertEqual(_blocks.version_of(new, "X-BLOCK"), "1.3.0")
        self.assertTrue(new.startswith("a\n") and new.endswith("\nb"))
        with self.assertRaises(ValueError):
            _blocks.replace(doc + block, "X-BLOCK", "")
        with self.assertRaises(ValueError):
            _blocks.replace("no block", "X-BLOCK", "")


if __name__ == "__main__":
    unittest.main()
