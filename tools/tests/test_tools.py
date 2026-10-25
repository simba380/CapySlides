"""Tests for the presentation tools: new.py, update.py, check.py, pack.py (+ TOOLS.html completeness).
    Run: python -m unittest discover tools/tests
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import _blocks  # noqa: E402
import _browser  # noqa: E402
import build  # noqa: E402

ANSWERS = "\n".join([
    "Talk",                                   # prefix
    "Scaling CNNs",                           # title
    "Tan & Le (2019)",                        # subtitle
    "",                                       # presenter → default Simon Meier
    "252-4811-00L Machine Learning",          # course title
    "",                                       # course type → Seminar
    "FS27",                                   # semester
    "Model Scaling", "Second", "",            # two animations, then done
]) + "\n"


def run(tool: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOLS / tool), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", timeout=600, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-tools-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = self.tmp / "Talk"
        proc = run("new.py", str(self.folder), stdin=ANSWERS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.deck = self.folder / "Talk_presentation.html"


class NewTest(ToolTestCase):
    def test_creates_a_filled_self_contained_folder(self):
        names = sorted(p.relative_to(self.folder).as_posix() for p in self.folder.rglob("*") if p.is_file())
        self.assertEqual(names, ["AUTHORING.md", "CLAUDE.md", "Model_Scaling_animations.html", "Second_animations.html",
                                 "Talk_presentation.html", "images/eth_zurich_aerial.png"])
        deck = self.deck.read_text(encoding="utf-8")
        for line in ['title:     "Scaling CNNs",', 'subtitle:  "Tan & Le (2019)",', 'presenter: "Simon Meier",',
                     'course:    { title: "252-4811-00L Machine Learning", type: "Seminar", semester: "FS27" },',
                     '{ id: "Model_Scaling", name: "Model Scaling", file: "Model_Scaling_animations.html" },',
                     '{ id: "Second", name: "Second", file: "Second_animations.html" },',
                     '<title>Scaling CNNs — Simon Meier</title>']:
            self.assertIn(line, deck)
        self.assertEqual(_blocks.version_of(deck, _blocks.DECK_ENGINE), build.engine_version())
        anim = (self.folder / "Model_Scaling_animations.html").read_text(encoding="utf-8")
        self.assertIn("<h1>Model Scaling</h1>", anim)
        self.assertEqual(_blocks.version_of(anim, _blocks.ANIM_CONTRACT), build.engine_version())
        claude = (self.folder / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn(str(ROOT / "AUTHORING.md"), claude)
        self.assertIn(f"engine v{build.engine_version()}", claude)
        self.assertEqual((self.folder / "AUTHORING.md").read_text(encoding="utf-8"), build.authoring_text(build.engine_version()))

    def test_refuses_existing_presentation_and_bad_prefix(self):
        self.assertEqual(run("new.py", str(self.folder), stdin=ANSWERS).returncode, 2)
        self.assertEqual(run("new.py", str(self.tmp / "Other"), stdin="bad prefix!\n").returncode, 2)


class UpdateTest(ToolTestCase):
    def age(self, path: Path, name: str, version: str, body: str = "old engine") -> str:
        text = _blocks.replace(path.read_text(encoding="utf-8"), name, _blocks.wrap(name, version, body))
        path.write_text(text, encoding="utf-8", newline="\n")
        return text

    def test_updates_engine_blocks_only(self):
        old = self.age(self.deck, _blocks.DECK_ENGINE, "0.9.0")
        anim = self.folder / "Second_animations.html"
        old_anim = self.age(anim, _blocks.ANIM_CONTRACT, "0.9.0", "old contract")
        claude = self.folder / "CLAUDE.md"
        claude.write_text("My own notes stay.\n\n" + claude.read_text(encoding="utf-8"), encoding="utf-8")
        proc = run("update.py", str(self.folder))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("v0.9.0 → v" + build.engine_version(), proc.stdout)
        new = self.deck.read_text(encoding="utf-8")
        self.assertEqual(_blocks.version_of(new, _blocks.DECK_ENGINE), build.engine_version())
        strip = lambda t: _blocks.block_re(_blocks.DECK_ENGINE).sub("", t)
        self.assertEqual(strip(new), strip(old), "user zone untouched")
        self.assertEqual((self.folder / "Talk_presentation.html.bak").read_text(encoding="utf-8"), old)
        self.assertEqual(_blocks.version_of(anim.read_text(encoding="utf-8"), _blocks.ANIM_CONTRACT), build.engine_version())
        self.assertEqual((self.folder / "Second_animations.html.bak").read_text(encoding="utf-8"), old_anim)
        self.assertTrue(claude.read_text(encoding="utf-8").startswith("My own notes stay."))
        self.assertEqual(claude.read_text(encoding="utf-8").count("CUSTOMPRESENTATIONS:BEGIN"), 1)
        again = run("update.py", str(self.folder))
        self.assertIn("up to date", again.stdout)

    def test_refuses_downgrade_and_foreign_files(self):
        self.age(self.deck, _blocks.DECK_ENGINE, "9.9.9")
        proc = run("update.py", str(self.deck))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("newer than this repository", proc.stderr)
        self.assertEqual(run("update.py", str(self.deck), "--force").returncode, 0)
        foreign = self.tmp / "x_presentation.html"
        foreign.write_text("<html>no markers</html>", encoding="utf-8")
        self.assertEqual(run("update.py", str(foreign)).returncode, 1)


@unittest.skipUnless(_browser.find_browser(), "no Chromium-based browser found")
class CheckAndPackTest(ToolTestCase):
    def break_deck(self):
        deck = self.deck.read_text(encoding="utf-8")
        deck = deck.replace('<h2 class="slide-title">Slide 4 – title</h2>',
                            '<h2 class="slide-title">Slide 4 – title</h2>\n'
                            '      <img src="images/missing.png" width="10" height="10" data-step="1">\n'
                            '      <img src="../outside.png" width="10" height="10">\n'
                            '      <img src="images/eth_zurich_aerial.png">', 1)
        self.deck.write_text(deck, encoding="utf-8", newline="\n")

    def test_check_clean_and_broken(self):
        proc = run("check.py", str(self.folder), "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)[0]["ok"])
        self.break_deck()
        proc = run("check.py", str(self.folder))
        self.assertEqual(proc.returncode, 1)
        out = proc.stdout
        self.assertIn('Slide 4 "Slide 4 – title", step 1: image "missing.png" not found', out)
        self.assertIn('points outside the presentation folder', out)
        self.assertIn("eth_zurich_aerial.png has missing/wrong width/height (1760x862)", out)

    def test_pack_zips_only_presentation_files(self):
        (self.folder / "Talk_presentation.html.bak").write_text("backup", encoding="utf-8")
        proc = run("pack.py", str(self.folder))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with zipfile.ZipFile(self.tmp / "Talk.zip") as z:
            names = sorted(z.namelist())
        self.assertEqual(names, ["Talk/Model_Scaling_animations.html", "Talk/Second_animations.html",
                                 "Talk/Talk_presentation.html", "Talk/images/eth_zurich_aerial.png"])
        self.assertIn("✓ no problems", proc.stdout)

    def test_pack_refuses_broken_deck(self):
        self.break_deck()
        (self.tmp / "Talk.zip").unlink(missing_ok=True)
        proc = run("pack.py", str(self.folder))
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((self.tmp / "Talk.zip").exists())
        self.assertEqual(run("pack.py", str(self.folder), "--force").returncode, 0)
        self.assertTrue((self.tmp / "Talk.zip").exists())


class ToolsPageTest(unittest.TestCase):
    def test_every_tool_is_documented(self):
        page = (ROOT / "TOOLS.html").read_text(encoding="utf-8")
        for tool in sorted(TOOLS.glob("*.py")):
            if not tool.name.startswith("_"):
                self.assertIn(f"tools/{tool.name}", page, f"TOOLS.html must document {tool.name}")
        self.assertIn("AUTHORING.md", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
