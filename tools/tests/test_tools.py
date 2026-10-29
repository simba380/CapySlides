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


def run(tool: str, *args: str, stdin: str | None = None, io_encoding: str = "utf-8") -> subprocess.CompletedProcess:
    """io_encoding = the console encoding the tool starts with (it switches its output to UTF-8)."""
    return subprocess.run([sys.executable, str(TOOLS / tool), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", timeout=600, env={**__import__("os").environ, "PYTHONIOENCODING": io_encoding})


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-tools-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = self.tmp / "Talk"
        proc = run("new.py", "Talk", "--parent", str(self.tmp), stdin=ANSWERS)
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

    def test_script_safe_values(self):
        # A "</script>" in a title must not end the DECK config script (regression).
        answers = "Evil\nA </script><b>x</b> B\n\n\n\n\n\n\n"
        self.assertEqual(run("new.py", "Evil", "--parent", str(self.tmp), stdin=answers).returncode, 0)
        deck = (self.tmp / "Evil" / "Evil_presentation.html").read_text(encoding="utf-8")
        config = deck[deck.index('<script id="deck-config">'):]
        config = config[:config.index("</script>")]
        self.assertIn('title:     "A <\\/script><b>x<\\/b> B",', config)
        self.assertIn("<title>A &lt;/script&gt;&lt;b&gt;x&lt;/b&gt; B — Simon Meier</title>", deck)

    def test_refuses_existing_project_and_bad_names(self):
        self.assertEqual(run("new.py", "Talk", "--parent", str(self.tmp), stdin=ANSWERS).returncode, 2)
        self.assertEqual(run("new.py", "bad name!", "--parent", str(self.tmp)).returncode, 2)
        self.assertEqual(run("new.py", "Other", "--parent", str(self.tmp), stdin="bad prefix!\n").returncode, 2)

    def test_default_location_is_presentations_folder(self):
        import _deckfolder
        self.assertEqual(_deckfolder.PRESENTATIONS, ROOT / "presentations")
        self.assertIn("presentations", run("new.py", "--help").stdout)


class AddAnimationTest(ToolTestCase):
    def test_creates_file_and_registers_it_after_the_existing_ones(self):
        old = self.deck.read_text(encoding="utf-8")
        proc = run("add_animation.py", str(self.folder), "Third One")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        anim = (self.folder / "Third_One_animations.html").read_text(encoding="utf-8")
        self.assertIn("<h1>Third One</h1>", anim)
        self.assertIn("<title>Third One — Simon Meier</title>", anim)
        self.assertEqual(_blocks.version_of(anim, _blocks.ANIM_CONTRACT), build.engine_version())
        second = '        { id: "Second", name: "Second", file: "Second_animations.html" },\n'
        third = '        { id: "Third_One", name: "Third One", file: "Third_One_animations.html" },\n'
        self.assertEqual(self.deck.read_text(encoding="utf-8"), old.replace(second, second + third, 1))
        self.assertEqual((self.folder / "Talk_presentation.html.bak").read_text(encoding="utf-8"), old)
        self.assertIn('data-anim="Third_One"', proc.stdout)

    def test_refuses_duplicates_and_ambiguous_folders(self):
        self.assertEqual(run("add_animation.py", str(self.folder), "Second").returncode, 2)   # file exists
        (self.folder / "Second_animations.html").unlink()
        proc = run("add_animation.py", str(self.folder), "Second")                           # still registered
        self.assertEqual(proc.returncode, 1)
        self.assertIn("already has an entry", proc.stderr)
        self.assertFalse((self.folder / "Second_animations.html").exists())
        shutil.copy(self.deck, self.folder / "Other_presentation.html")
        self.assertEqual(run("add_animation.py", str(self.folder), "X").returncode, 2)
        self.assertEqual(run("add_animation.py", str(self.deck), "X").returncode, 0)

    def test_config_variants(self):
        import add_animation as aa
        entry = {"id": "main", "name": "Main", "file": "main_animations.html"}
        line = '{ id: "main", name: "Main", file: "main_animations.html" },'

        def deck(body: str, nl: str = "\n") -> str:
            return nl.join(['<script id="deck-config">', "    const DECK = {", *body.split("\n"), "    };", "  </script>",
                            "<script>const x = { animations: [] };</script>"])

        # The starter's comment-only list (its commented example uses the same id).
        starter = '      animations: [\n        // { id: \'main\', name: \'My animation\', file: \'x.html\' },\n      ],'
        self.assertIn(f"x.html' }},\n        {line}\n      ],", aa.register(deck(starter), entry))
        # One-line empty list, last entry without trailing comma, missing key, CRLF file.
        self.assertIn(f"animations: [\n        {line}\n      ],", aa.register(deck("      animations: [],"), entry))
        out = aa.register(deck("      animations: [\n        { id: 'a', file: 'a.html' }\n      ],"), entry)
        self.assertIn(f"{{ id: 'a', file: 'a.html' }},\n        {line}\n      ],", out)
        out = aa.register(deck("      title: 'T' // no comma"), entry)
        self.assertIn(f"title: 'T', // no comma\n      animations: [\n        {line}\n      ],\n    }};", out)
        out = aa.register(deck("      animations: [],", "\r\n"), entry)
        self.assertIn(f"animations: [\r\n        {line}\r\n      ],\r\n", out)
        self.assertNotIn("\n", out.replace("\r\n", ""))
        # The engine's own `animations: []` default (outside the config script) is never touched.
        self.assertTrue(out.endswith("<script>const x = { animations: [] };</script>"))
        with self.assertRaises(aa.ConfigError):
            aa.register(deck("      animations: [\n        { id: 'main', file: 'm.html' },\n      ],"), entry)
        with self.assertRaises(aa.ConfigError):
            aa.register(deck("      animations: ANIMS,"), entry)


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
        self.assertEqual(claude.read_text(encoding="utf-8").count("CAPYSLIDES:BEGIN"), 1)
        again = run("update.py", str(self.folder))
        self.assertIn("up to date", again.stdout)

    def test_keeps_windows_line_endings(self):
        # A deck saved with CRLF: at the same version nothing is rewritten; a new engine comes in as CRLF.
        self.deck.write_bytes(self.deck.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        proc = run("update.py", str(self.folder))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"up to date  {self.deck.name}", proc.stdout)
        self.assertFalse(self.deck.with_name(self.deck.name + ".bak").exists())
        old = _blocks.wrap(_blocks.DECK_ENGINE, "0.9.0", "old engine").replace("\n", "\r\n")
        self.deck.write_bytes(_blocks.replace(self.deck.read_bytes().decode("utf-8"), _blocks.DECK_ENGINE, old).encode("utf-8"))
        proc = run("update.py", str(self.folder))
        self.assertIn("v0.9.0 → v" + build.engine_version(), proc.stdout)
        new = self.deck.read_bytes().decode("utf-8")
        self.assertEqual(_blocks.version_of(new, _blocks.DECK_ENGINE), build.engine_version())
        self.assertNotIn("\n", new.replace("\r\n", ""), "only CRLF line endings")

    def test_replaces_the_block_of_projects_from_before_the_rename(self):
        # Projects created as "CustomPresentations" (before R18-1) carry the old markers.
        claude = self.folder / "CLAUDE.md"
        claude.write_text("My own notes stay.\n\n<!-- CUSTOMPRESENTATIONS:BEGIN v1.2.0 (managed) -->\n# old pointer\n"
                          "<!-- CUSTOMPRESENTATIONS:END -->\n\nNotes after it stay too.\n", encoding="utf-8")
        proc = run("update.py", str(self.folder))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = claude.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("My own notes stay.\n\n<!-- CAPYSLIDES:BEGIN"), text[:80])
        self.assertTrue(text.endswith("<!-- CAPYSLIDES:END -->\n\nNotes after it stay too.\n"), text[-80:])
        self.assertNotIn("CUSTOMPRESENTATIONS", text)
        self.assertNotIn("old pointer", text)
        self.assertEqual(text.count("CAPYSLIDES:BEGIN"), 1)

    def test_output_works_on_a_cp1252_console(self):
        self.age(self.deck, _blocks.DECK_ENGINE, "0.9.0")
        proc = run("update.py", str(self.folder), io_encoding="cp1252")   # Windows console, output piped
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("v0.9.0 → v" + build.engine_version(), proc.stdout)

    def test_refuses_downgrade_and_foreign_files(self):
        self.age(self.deck, _blocks.DECK_ENGINE, "9.9.9")
        proc = run("update.py", str(self.deck))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("newer than this repository", proc.stderr)
        self.assertEqual(run("update.py", str(self.deck), "--force").returncode, 0)
        foreign = self.tmp / "x_presentation.html"
        foreign.write_text("<html>no markers</html>", encoding="utf-8")
        self.assertEqual(run("update.py", str(foreign)).returncode, 1)


class PackSelectionTest(ToolTestCase):
    """Which files pack.py takes (no browser needed: the running deck's references are passed in)."""

    def test_names_matches_whole_paths_only(self):
        import pack
        self.assertTrue(pack.names('<img src="images/a.png">', "images/a.png"))
        self.assertTrue(pack.names("url('./images/a.png')", "images/a.png"))
        self.assertTrue(pack.names('src="images/my%20fig.png"', "images/my fig.png"))
        self.assertTrue(pack.names("file: 'x_animations.html' }", "x_animations.html"))
        self.assertFalse(pack.names('src="old/images/a.png"', "images/a.png"))
        self.assertFalse(pack.names('src="images/a.png2"', "images/a.png"))
        self.assertFalse(pack.names('src="images/data.png"', "a.png"))

    def test_needed_files(self):
        import pack
        images = self.folder / "images"
        for name in ("your_figure.png", "only_in_a_comment.png", "unused.png"):
            (images / name).write_bytes(b"x")
        deck = self.deck.read_text(encoding="utf-8")
        deck = re.sub(r"\n[ \t]*cover:[^\n]*", "", deck, count=1)                # the engine's default cover then
        deck = deck.replace("</main>", "<!-- images/only_in_a_comment.png --></main>", 1)
        self.deck.write_text(deck, encoding="utf-8", newline="\n")
        rel = lambda paths: [p.as_posix() for p in paths]
        needed, left_out = pack.needed_files(self.deck)
        self.assertEqual(rel(needed), ["Model_Scaling_animations.html", "Second_animations.html", "Talk_presentation.html",
                                       "images/only_in_a_comment.png"])
        # your_figure.png is only named in the engine block (component example), the cover only by the engine's default
        self.assertEqual(rel(left_out), ["images/eth_zurich_aerial.png", "images/unused.png", "images/your_figure.png"])
        needed, _ = pack.needed_files(self.deck, ["images/eth_zurich_aerial.png", "Second_animations.html?deck-embed=1",
                                                  "../outside.png", "missing.png"])
        self.assertIn("images/eth_zurich_aerial.png", rel(needed))


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

    def test_added_animation_passes_check(self):
        self.assertEqual(run("add_animation.py", str(self.folder), "Third").returncode, 0)
        deck = self.deck.read_text(encoding="utf-8")
        deck = deck.replace('<section data-type="black">',
                            '<section data-type="animation" data-anim="Third" data-title="Third"></section>\n    <section data-type="black">', 1)
        self.deck.write_text(deck, encoding="utf-8", newline="\n")
        proc = run("check.py", str(self.folder), "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def zipped(self) -> list[str]:
        with zipfile.ZipFile(self.tmp / "Talk.zip") as z:
            return sorted(z.namelist())

    def test_pack_zips_only_presentation_files(self):
        (self.folder / "Talk_presentation.html.bak").write_text("backup", encoding="utf-8")
        (self.folder / "notes.txt").write_text("my notes", encoding="utf-8")
        shutil.copy(self.folder / "images" / "eth_zurich_aerial.png", self.folder / "images" / "unused.png")
        proc = run("pack.py", str(self.folder))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.zipped(), ["Talk/Model_Scaling_animations.html", "Talk/Second_animations.html",
                                         "Talk/Talk_presentation.html", "Talk/images/eth_zurich_aerial.png"])
        self.assertIn("Left out (nothing in the presentation uses them):\n  images/unused.png\n  notes.txt", proc.stdout)
        # Each step starts with "[STEP n/4] …"; everything inside it is indented exactly below that text.
        progress = [line for line in proc.stdout.split("\nWrote ")[0].splitlines() if line.strip()]
        indent = " " * len("[STEP 1/4] ")
        self.assertEqual([line[:30] for line in progress if line.startswith("[STEP ")], [
            "[STEP 1/4] Finding the files T", "[STEP 2/4] Copying them to a t",
            "[STEP 3/4] Checking the copy o", "[STEP 4/4] Writing Talk.zip"])
        for line in progress:
            if not line.startswith("[STEP "):
                self.assertTrue(line.startswith(indent) and not line[len(indent)].isspace(), repr(line))
        results = [line.strip() for line in progress if line.strip().startswith(("PASSED", "FAILED"))]
        self.assertEqual([r[:22] for r in results], [
            "PASSED: 4 files used, ", "PASSED: 4 files copied", "PASSED: no problems fo", "PASSED: Talk.zip writt"])
        self.assertEqual(results[0], "PASSED: 4 files used, 2 left out")

    def test_pack_follows_animations_and_engine_defaults(self):
        # An image only an animation names goes in; the engine's default cover (no DECK.cover) too.
        shutil.copy(self.folder / "images" / "eth_zurich_aerial.png", self.folder / "images" / "anim_pic.png")
        anim = self.folder / "Second_animations.html"
        anim.write_text(anim.read_text(encoding="utf-8").replace(
            '<div class="main-row">', '<div class="main-row"><img src="images/anim_pic.png" width="10" height="10" alt="">', 1),
            encoding="utf-8", newline="\n")
        deck = self.deck.read_text(encoding="utf-8")
        self.deck.write_text(re.sub(r"\n[ \t]*cover:[^\n]*", "", deck, count=1), encoding="utf-8", newline="\n")
        self.assertNotIn("eth_zurich_aerial", self.deck.read_text(encoding="utf-8").split("<!-- DECK-ENGINE:BEGIN")[0])
        proc = run("pack.py", str(self.folder))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Talk/images/anim_pic.png", self.zipped())
        self.assertIn("Talk/images/eth_zurich_aerial.png", self.zipped())

    def test_check_finds_broken_animation_image(self):
        anim = self.folder / "Second_animations.html"
        anim.write_text(anim.read_text(encoding="utf-8").replace(
            '<div class="main-row">', '<div class="main-row"><img src="images/nope.png" width="10" height="10" alt="">', 1),
            encoding="utf-8", newline="\n")
        proc = run("check.py", str(self.folder))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn('✗ Second_animations.html: image "images/nope.png" not found', proc.stdout)

    def test_pack_refuses_broken_deck(self):
        self.break_deck()
        (self.tmp / "Talk.zip").unlink(missing_ok=True)
        proc = run("pack.py", str(self.folder))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("\n" + " " * len("[STEP 3/4] ") + "FAILED: ", proc.stdout)
        self.assertNotIn("[STEP 4/4]", proc.stdout)
        self.assertFalse((self.tmp / "Talk.zip").exists())
        proc = run("pack.py", str(self.folder), "--force")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("(zipping anyway: --force)", proc.stdout)
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
