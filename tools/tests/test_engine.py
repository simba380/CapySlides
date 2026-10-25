"""Browser tests for the deck engine (P1: canvas, slides, steps, navigation, warnings).

Each test builds a fixture deck from tools/tests/fixtures/, opens it in headless Edge/Chrome
via file:// (network disabled) and drives it through the public `Deck` API and synthetic key
events. Skipped when no Chromium-based browser is installed.
    Run: python -m unittest discover tools/tests
"""
from __future__ import annotations

import datetime
import shutil
import sys
import unittest
from functools import lru_cache
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))
import browser  # noqa: E402
import _blocks  # noqa: E402
import build  # noqa: E402

FIXTURES = TESTS / "fixtures"

HELPERS = """
  const $ = id => document.getElementById(id);
  const vis = id => $(id).classList.contains('is-shown');
  const st = () => { const s = Deck.state; return { id: s.id, step: s.step, label: s.label }; };
  const key = (k, opts = {}, target = document) =>
    target.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts }));
"""


@lru_cache(maxsize=None)
def fixture(name: str, date: str | None = None, title: str | None = None) -> str:
    shell = (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
    if date is not None:
        shell = shell.replace("date:      '01.02.2026'", f"date:      '{date}'")
    if title is not None:
        shell = shell.replace("title:     'Fixture deck for the engine tests'", f"title:     {title!r}")
    return build.build_deck(shell, build.engine_version())


@lru_cache(maxsize=None)
def anim_template() -> str:
    """The built template_animations.html (it carries the animation contract)."""
    return build.build_outputs()["template_animations.html"].decode("utf-8")


def probe(name: str, js: str, page: str | None = None, files: dict | None = None, **kw):
    """Run a fixture; the built animation template sits next to it as demo_animations.html."""
    files = {"demo_animations.html": anim_template(), **(files or {})}
    return browser.run(page or fixture(name.split("-")[0]), HELPERS + js, name, files=files, **kw)


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class EngineTest(unittest.TestCase):

    def test_structure_numbering_footer_and_toc(self):
        r = probe("steps_deck-structure", """
          return {
            slides: Deck.slides,
            warnings: Deck.warnings,
            footers: [...document.querySelectorAll('#deck > section')].map(s => ({
              id: s.id,
              date: s.querySelector('.footer-date')?.textContent ?? null,
              number: s.querySelector('.footer-number')?.textContent ?? null,
            })),
            toc: [...document.querySelectorAll('.toc-item')].map(li => ({
              num: li.querySelector('.num').textContent,
              text: li.querySelector('.toc-text').textContent,
              sub: [...li.querySelectorAll('.toc-sub li')].map(x => x.textContent),
            })),
            badge: !!document.getElementById('deck-warnings'),
            katex: document.querySelectorAll('.katex').length,
            katexDisplay: document.querySelectorAll('.katex-display').length,
            katexErrors: document.querySelectorAll('.katex-error').length,
            loading: document.documentElement.classList.contains('deck-loading'),
          };
        """)
        self.assertEqual(r["warnings"], [])
        self.assertFalse(r["loading"])
        self.assertFalse(r["badge"], "badge must only appear with ?dev")
        slides = r["slides"]
        self.assertEqual([s["label"] for s in slides],
                         ["1", "2", "3", "4", "5", "6", "7", "", "Appendix 1", "Appendix 2"])
        self.assertEqual([s["N"] for s in slides], [1, 2, 4, 4, 4, 5, 2, 1, 2, 1])   # unmarked content = extra final step
        self.assertEqual([s["zone"] for s in slides], ["main"] * 8 + ["appendix"] * 2)
        self.assertEqual(slides[2]["title"], "Basic steps")
        self.assertEqual(slides[9]["title"], "Appendix animation")    # from data-title
        self.assertEqual(slides[1]["title"], "Table of Contents")
        self.assertEqual(slides[0]["id"], "slide-1")                   # auto id
        footers = {f["id"]: f for f in r["footers"]}
        self.assertIsNone(footers["slide-1"]["number"])                # title: no footer
        self.assertIsNone(footers["slide-8"]["number"])                # black: no footer
        self.assertEqual(footers["basic"], {"id": "basic", "date": "01.02.2026", "number": "3"})
        self.assertEqual(footers["app1"]["number"], "Appendix 1")
        self.assertEqual(r["toc"], [
            {"num": "1", "text": "Alpha", "sub": []},
            {"num": "2", "text": "Beta", "sub": ["Beta one", "Beta two"]},
            {"num": "3", "text": "Gamma x2x^2x2", "sub": []},           # KaTeX text content (mathml + html)
        ])
        self.assertEqual(r["katexErrors"], 0)
        self.assertEqual(r["katexDisplay"], 1)
        self.assertGreaterEqual(r["katex"], 3)

    def test_step_visibility_and_class_rules(self):
        r = probe("steps_deck-steps", """
          const out = { basic: [], ranges: [], classes: [] };
          Deck.goTo('basic');
          const ids = ['b1', 'b2', 'b3', 'b-static', 'b-li-plain', 'b-li-one', 'b-li-three', 'b-gone'];
          out.titleAlways = !$('basic').querySelector('.slide-title').classList.contains('step-layer');
          out.listStructural = !$('b-list').classList.contains('step-layer');
          out.implicit = [...$('basic').querySelectorAll('[data-step-implicit]')].map(e => e.id);
          for (let i = 0; i < 4; i++) { out.basic.push([Deck.state.step, ...ids.map(vis)]); Deck.next(); }
          Deck.goTo('ranges');
          for (let i = 0; i < 4; i++) {
            out.ranges.push([Deck.state.step, vis('r-range'), vis('r-only'), vis('r-late'), vis('r-slide')]);
            Deck.next();
          }
          Deck.goTo('classes');
          for (let i = 0; i < 3; i++) {
            const c = $('c-word').classList;
            out.classes.push([Deck.state.step, c.contains('hi'), c.contains('bold')]);
            Deck.next();
          }
          out.fx = ['r-late', 'r-slide', 'r-none', 'b2'].map(id => [...$(id).classList].filter(c => c.startsWith('fx-')));
          return out;
        """)
        # columns: step, b1, b2, b3, b-static, b-li-plain, b-li-one, b-li-three, b-gone
        self.assertEqual(r["basic"], [
            [0, False, False, False, True, False, True, False, True],    # step 0: title + explicit step-0 only
            [1, False, True, False, True, False, True, False, True],
            [2, False, True, True, True, False, True, True, False],      # 0..1 layer removed again
            [3, True, True, True, True, True, True, True, False],        # final step: all unmarked content
        ])
        self.assertTrue(r["titleAlways"])
        self.assertTrue(r["listStructural"])
        self.assertEqual(r["implicit"], ["b1", "b-li-plain"])
        self.assertEqual(r["ranges"], [
            [0, False, False, False, False],
            [1, True, False, False, True],
            [2, True, True, False, True],
            [3, False, False, True, True],
        ])
        self.assertEqual(r["classes"], [[0, False, False], [1, True, False], [2, False, True]])
        self.assertEqual(r["fx"], [["fx-fade"], ["fx-slide-left"], ["fx-none"], ["fx-rise"]])

    def test_navigation_state_machine_and_step_memory(self):
        r = probe("steps_deck-nav", """
          const o = {};
          o.start = st();
          o.prevAtStart = Deck.prev();
          Deck.next(); Deck.next(); Deck.next();          // toc 0, toc 1 (list) -> basic (step 0)
          o.enterForward = st();
          Deck.next(); Deck.next(); Deck.next(); Deck.next();   // basic 2, 3, 4 -> ranges 1
          Deck.next();                                    // ranges 2
          Deck.prev(); Deck.prev();                       // ranges 1 -> basic (visited: restore 4)
          o.backToVisited = st();
          Deck.next();                                    // -> ranges (visited: restore 1)
          o.forwardToVisited = st();
          Deck.goTo('hooked');                            // unvisited jump -> step 0
          o.jumpUnvisited = st();
          Deck.next(); Deck.next();                       // hooked 3
          Deck.goTo('basic'); Deck.goTo('hooked');        // jump to visited -> restore 3
          o.jumpVisited = st();
          Deck.goTo('app2');
          Deck.prev();                                    // app1 unvisited, entered backwards -> N
          o.backUnvisited = st();
          Deck.prev(); Deck.prev();                       // app1 1 -> black
          o.black = st();
          Deck.prev();                                    // math (unvisited, entered backwards -> N=2)
          o.math = st();
          Deck.goTo('ranges', 99); o.clampHigh = st();
          Deck.goTo('ranges', -3); o.clampLow = st();
          o.badGoTo = Deck.goTo('nope');
          Deck.goTo('app2');
          o.nextAtEnd = Deck.next();
          o.end = st();
          o.hookCalls = window.hookCalls;
          o.activeCount = document.querySelectorAll('#deck > section.is-active').length;
          o.inertOthers = [...document.querySelectorAll('#deck > section:not(.is-active)')].every(s => s.inert);
          o.warnings = Deck.warnings;
          return o;
        """)
        self.assertEqual(r["start"], {"id": "slide-1", "step": 0, "label": "1"})
        self.assertFalse(r["prevAtStart"])
        self.assertEqual(r["enterForward"], {"id": "basic", "step": 0, "label": "3"})
        self.assertEqual(r["backToVisited"], {"id": "basic", "step": 3, "label": "3"})
        self.assertEqual(r["forwardToVisited"], {"id": "ranges", "step": 0, "label": "4"})
        self.assertEqual(r["jumpUnvisited"], {"id": "hooked", "step": 0, "label": "6"})
        self.assertEqual(r["jumpVisited"], {"id": "hooked", "step": 2, "label": "6"})
        self.assertEqual(r["backUnvisited"], {"id": "app1", "step": 1, "label": "Appendix 1"})
        self.assertEqual(r["black"], {"id": "slide-8", "step": 0, "label": ""})
        self.assertEqual(r["math"], {"id": "math", "step": 1, "label": "7"})
        self.assertEqual(r["clampHigh"]["step"], 3)
        self.assertEqual(r["clampLow"]["step"], 0)
        self.assertFalse(r["badGoTo"])
        self.assertFalse(r["nextAtEnd"])
        self.assertEqual(r["end"]["id"], "app2")
        # hook: [step, first, N, preview] for every render of 'hooked'
        self.assertEqual(r["hookCalls"], [[0, True, 5, False], [1, False, 5, False], [2, False, 5, False],
                                          [2, False, 5, False]])
        self.assertEqual(r["activeCount"], 1)
        self.assertTrue(r["inertOthers"])
        self.assertEqual(r["warnings"], ['Deck.goTo: no slide "nope"'])

    def test_keyboard(self):
        r = probe("steps_deck-keys", """
          const o = { forward: {}, back: {} };
          for (const k of ['ArrowRight', 'ArrowDown', ' ', 'PageDown', 'End']) {
            Deck.goTo('basic', 0);
            const notPrevented = key(k);
            o.forward[k] = [Deck.state.step, notPrevented];
          }
          for (const k of ['ArrowLeft', 'ArrowUp', 'PageUp', 'Home']) {
            Deck.goTo('basic', 1); key(k); o.back[k] = Deck.state.step;
          }
          Deck.goTo('basic', 0); key('End', { ctrlKey: true }); o.ctrlEnd = Deck.state.step;
          Deck.goTo('basic', 1); key('ArrowLeft', { altKey: true }); o.altLeft = Deck.state.step;
          Deck.goTo('basic', 1); key('ArrowLeft', { metaKey: true }); o.metaLeft = Deck.state.step;
          Deck.goTo('basic', 0); key('x'); o.otherKey = Deck.state.step;
          const input = document.createElement('input'); document.body.appendChild(input); input.focus();
          Deck.goTo('basic', 0); key('ArrowRight', {}, input); o.inInput = Deck.state.step;
          return o;
        """)
        for k, (step, not_prevented) in r["forward"].items():
            self.assertEqual(step, 1, k)
            self.assertFalse(not_prevented, f"{k} must call preventDefault")
        self.assertEqual(r["back"], {"ArrowLeft": 0, "ArrowUp": 0, "PageUp": 0, "Home": 0})
        self.assertEqual(r["ctrlEnd"], 1)
        self.assertEqual(r["altLeft"], 1)
        self.assertEqual(r["metaLeft"], 1)
        self.assertEqual(r["otherKey"], 0)
        self.assertEqual(r["inInput"], 0)

    def test_canvas_scaling_and_letterbox(self):
        js = """
          const vp = $('deck-viewport'), rect = $('deck-stage').getBoundingClientRect();
          const bg = () => vp.style.backgroundColor;
          const o = { iw: innerWidth, ih: innerHeight, scale: Deck.state.scale,
                      rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height } };
          o.bgTitle = bg();
          Deck.goTo('basic');  o.bgContent = bg();
          Deck.goTo('hooked'); o.bgCustom = bg();
          Deck.goTo(7);        o.bgBlack = bg();
          return o;
        """
        for size in ((1138, 711), (1920, 1080), (1280, 1024)):
            with self.subTest(size=size):
                r = probe(f"steps_deck-canvas{size[0]}x{size[1]}", js, size=size)
                s = min(r["iw"] / 1280, r["ih"] / 800)
                self.assertAlmostEqual(r["scale"], s, places=6)
                self.assertAlmostEqual(r["rect"]["w"], 1280 * s, delta=0.5)
                self.assertAlmostEqual(r["rect"]["h"], 800 * s, delta=0.5)
                self.assertAlmostEqual(r["rect"]["x"], (r["iw"] - 1280 * s) / 2, delta=0.5)
                self.assertAlmostEqual(r["rect"]["y"], (r["ih"] - 800 * s) / 2, delta=0.5)
                self.assertEqual(r["bgTitle"], "rgb(28, 47, 82)")
                self.assertEqual(r["bgContent"], "rgb(255, 255, 255)")
                self.assertEqual(r["bgCustom"], "rgb(245, 243, 238)")
                self.assertEqual(r["bgBlack"], "rgb(0, 0, 0)")

    def test_auto_date(self):
        r = probe("steps_deck-autodate", "return $('basic').querySelector('.footer-date').textContent;",
                  page=fixture("steps_deck", date="auto"))
        self.assertEqual(r, datetime.date.today().strftime("%d.%m.%Y"))

    def test_dev_badge(self):
        js = """
          const b = $('deck-warnings');
          return b && { cls: b.className, label: b.querySelector('.dw-toggle').textContent,
                        items: b.querySelectorAll('.dw-list li').length };
        """
        ok = probe("steps_deck-dev", js, query="?dev")
        self.assertEqual(ok, {"cls": "no-warnings", "label": "✓ no deck warnings", "items": 0})
        bad = probe("broken_deck-dev", js, query="?dev")
        self.assertEqual(bad["cls"], "has-warnings")
        self.assertRegex(bad["label"], r"^⚠ \d+ deck warnings$")
        self.assertGreater(bad["items"], 5)

    def test_warnings_for_broken_deck(self):
        r = probe("broken_deck-warnings", """
          Deck.goTo('thrower');                 // hooks only run when their slide renders
          return { warnings: Deck.warnings, labels: Deck.slides.map(s => s.label),
                   redFormula: !!document.querySelector('#thrower .katex') };
        """)
        expected = [
            "DECK.toc must be an array",
            'DECK.hooks["notfn"] is not a function',
            '<div> directly inside #deck is ignored',
            'slide 3: unknown data-type="weird"',
            'duplicate slide id "dup"',
            "the title slide must be the first slide",
            "the toc slide must be the second slide",
            "no black slide",
            'invalid data-step="1..0"',
            'unknown data-step-fx="wobble"',
            'invalid data-step-class rule "hi"',
            'data-steps="1" is lower than the number of steps used (3)',
            'unknown data-layout="sideways"',
            "has no title",
            'DECK.hooks["ghost"] does not match any slide id',
            'DECK.hooks["thrower"] threw: boom',
            'formula error in "\\notacommand"',
        ]
        joined = "\n".join(r["warnings"])
        for fragment in expected:
            self.assertIn(fragment, joined)
        self.assertEqual(r["labels"], ["1", "2", "3", "4", "5", "6"])   # no black: everything is main
        self.assertTrue(r["redFormula"], "a broken formula is still rendered (in red) by KaTeX")


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class PreviewTest(unittest.TestCase):

    def test_preview_mode_renders_one_slide_at_final_step(self):
        js = """
          const before = Deck.state;
          key('ArrowRight');                               // no keyboard handling in preview
          return { state: before, after: Deck.state, preview: Deck.preview,
                   active: [...document.querySelectorAll('#deck > section.is-active')].map(s => s.id),
                   topbar: !!$('deck-topbar'), badge: !!$('deck-warnings'), hint: !!$('deck-hint'),
                   nav: !!$('nav-overlay'), cls: document.documentElement.className,
                   hooks: window.hookCalls || [] };
        """
        r = probe("steps_deck-preview", js, query="?preview=3")
        self.assertTrue(r["preview"])
        self.assertEqual(r["active"], ["ranges"])
        self.assertEqual((r["state"]["id"], r["state"]["step"]), ("ranges", 3))   # final step
        self.assertEqual(r["after"]["step"], 3)
        for part in ("topbar", "badge", "hint", "nav"):
            self.assertFalse(r[part], part)
        self.assertIn("deck-preview", r["cls"])
        r = probe("steps_deck-preview-id", js, query="?preview=hooked&step=2&dev")
        self.assertEqual((r["state"]["id"], r["state"]["step"]), ("hooked", 2))
        self.assertFalse(r["badge"], "preview never shows dev UI, even with ?dev")
        self.assertEqual(r["hooks"], [[2, True, 5, True]])                     # ctx.preview = true


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class NavigatorTest(unittest.TestCase):

    ROWS = """
      [...document.querySelectorAll('#nav-overlay .deck-row')].map(row => ({
        slide: Number(row.dataset.slide),
        num: row.querySelector('.row-num').textContent,
        label: row.querySelector('.row-label').textContent,
        current: row.classList.contains('is-current'),
        bad: row.classList.contains('has-problems'),
        problems: [...row.querySelectorAll('.row-problems li')].map(li => li.textContent),
        src: row.querySelector('iframe').getAttribute('src'),
      }))
    """

    def test_navigator_rows_thumbnails_and_step_memory(self):
        r = probe("steps_deck-nav-panel", f"""
          const o = {{}};
          const btn = $('nav-btn');
          o.button = {{ text: btn.textContent, red: btn.classList.contains('has-problems'),
                       last: $('deck-topbar').lastElementChild === btn }};
          o.devBtn = !!$('dev-btn');
          o.hint = $('deck-hint').textContent;
          const frames = [...document.querySelectorAll('#nav-overlay iframe')];
          const queued = [...frames, ...document.querySelectorAll('#anim-overlay iframe')];
          o.loadingAtStart = queued.filter(f => f.getAttribute('src')).length;    // one at a time
          o.animFirst = !!document.querySelector('#anim-overlay iframe')?.getAttribute('src');
          await new Promise(done => {{
            const t0 = performance.now();
            (function poll() {{
              if (frames.every(f => f.getAttribute('src')) || performance.now() - t0 > 7000) done();
              else setTimeout(poll, 100);
            }})();
          }});
          Deck.goTo('basic', 2); Deck.goTo('math');
          btn.click();
          o.open = $('nav-overlay').classList.contains('open');
          o.locked = Deck.state.locked;
          o.rows = {self.ROWS};
          o.deckBox = !$('nav-overlay').querySelector('.nav-deck-problems')?.hidden;
          key('ArrowRight'); o.keysBlocked = Deck.state.id === 'math';
          key('Escape'); o.escClosed = !$('nav-overlay').classList.contains('open') && !Deck.state.locked;
          btn.click(); $('nav-overlay').click();             // click on the backdrop
          o.backdropClosed = !$('nav-overlay').classList.contains('open');
          btn.click(); document.querySelector('#nav-overlay .deck-row[data-slide="2"]').click();
          o.toVisited = st();                                 // basic was left at step 2
          btn.click(); document.querySelector('#nav-overlay .deck-row[data-slide="3"]').click();
          o.toUnvisited = st();
          o.closed = !$('nav-overlay').classList.contains('open');
          return o;
        """, budget_ms=8000)
        self.assertEqual(r["button"], {"text": "☰ Slides", "red": False, "last": True})
        self.assertFalse(r["devBtn"])
        self.assertEqual(r["hint"], "← → to navigate")
        self.assertEqual(r["loadingAtStart"], 1, "queued frames (animations, then thumbnails) load one at a time")
        self.assertTrue(r["animFirst"], "animation instances are queued before the navigator thumbnails")
        self.assertTrue(r["open"] and r["locked"])
        rows = r["rows"]
        self.assertEqual([row["num"] for row in rows],
                         ["Slide 1", "Slide 2", "Slide 3", "Slide 4", "Slide 5", "Slide 6", "Slide 7", "–",
                          "Appendix 1", "Appendix 2"])
        self.assertEqual(rows[0]["label"], "Fixture deck for the engine tests")
        self.assertEqual(rows[2]["label"], "Basic steps")
        self.assertEqual([row["current"] for row in rows], [i == 6 for i in range(10)])
        self.assertTrue(all(row["src"] and row["src"].endswith(f"?preview={i}") for i, row in enumerate(rows)),
                        "all thumbnails loaded (sequentially) after startup")
        self.assertFalse(any(row["bad"] or row["problems"] for row in rows), "no problem UI without ?dev")
        self.assertFalse(r["deckBox"])
        self.assertTrue(r["keysBlocked"])
        self.assertTrue(r["escClosed"])
        self.assertTrue(r["backdropClosed"])
        self.assertEqual(r["toVisited"], {"id": "basic", "step": 2, "label": "3"})
        self.assertEqual(r["toUnvisited"], {"id": "ranges", "step": 0, "label": "4"})
        self.assertTrue(r["closed"])

    def test_dev_problems_in_navigator(self):
        r = probe("broken_deck-nav-dev", f"""
          const o = {{}};
          Deck.goTo('thrower');                                  // runs the throwing hook (step 0)
          o.red = $('nav-btn').classList.contains('has-problems');
          o.devBtn = !!$('dev-btn');
          $('nav-btn').click();
          const box = document.querySelector('#nav-overlay .nav-deck-problems');
          o.deckBox = {{ hidden: box.hidden, items: [...box.querySelectorAll('li')].map(li => li.textContent) }};
          o.rows = {self.ROWS};
          document.querySelector('#nav-overlay .deck-row[data-slide="5"]').click();
          o.late = st();                                         // first problem at step 2
          $('nav-btn').click();
          document.querySelector('#nav-overlay .deck-row[data-slide="2"]').click();
          o.thrower = st();
          o.problems = Deck.problems;
          return o;
        """, query="?dev")
        self.assertTrue(r["red"])
        self.assertFalse(r["devBtn"])
        self.assertFalse(r["deckBox"]["hidden"])
        self.assertTrue(any("DECK.toc must be an array" in i for i in r["deckBox"]["items"]))
        self.assertTrue(any("no black slide" in i for i in r["deckBox"]["items"]))
        rows = {row["slide"]: row for row in r["rows"]}
        self.assertEqual(len(rows), 6)
        thrower = rows[2]
        self.assertTrue(thrower["bad"])
        self.assertTrue(all(p.startswith("step ") for p in thrower["problems"]))
        steps = [int(p.split()[1]) for p in thrower["problems"]]
        self.assertEqual(steps, sorted(steps))                                  # sorted by step
        joined = "\n".join(thrower["problems"])
        self.assertIn('step 0 · slide 3: unknown data-type="weird"', joined)
        self.assertIn('step 1 · slide 3 ("thrower"): unknown data-step-fx="wobble"', joined)
        self.assertIn("step 0 · DECK.hooks[\"thrower\"] threw: boom", joined)
        self.assertIn('step 2 · formula error in "\\notacommand"', joined)       # unmarked paragraph: final step
        self.assertEqual(rows[5]["problems"], [rows[5]["problems"][0]])
        self.assertTrue(rows[5]["problems"][0].startswith('step 2 · formula error in "\\alsonotacommand"'))
        self.assertEqual(r["late"], {"id": "late", "step": 2, "label": "6"})
        self.assertEqual(r["thrower"]["step"], 0)
        late = [p for p in r["problems"] if p["slide"] == 5]
        self.assertEqual([p["step"] for p in late], [2])

    def test_dev_clean_slide_uses_step_memory(self):
        r = probe("steps_deck-nav-dev", """
          const o = { red: $('nav-btn').classList.contains('has-problems') };
          Deck.goTo('ranges', 2); Deck.goTo(0);
          $('nav-btn').click();
          o.deckBoxHidden = document.querySelector('#nav-overlay .nav-deck-problems').hidden;
          o.anyBad = !!document.querySelector('#nav-overlay .deck-row.has-problems');
          document.querySelector('#nav-overlay .deck-row[data-slide="3"]').click();
          o.ranges = st();
          return o;
        """, query="?dev")
        self.assertFalse(r["red"])
        self.assertTrue(r["deckBoxHidden"])
        self.assertFalse(r["anyBad"])
        self.assertEqual(r["ranges"]["step"], 2)


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class TitleSlideTest(unittest.TestCase):

    MEASURE = """
      await document.fonts.ready;
      await new Promise(r => setTimeout(r, 50));
      const box = document.querySelector('.cover-box');
      const lines = el => { const r = document.createRange(); r.selectNodeContents(el); return r.getClientRects().length; };
      return {
        width: box.offsetWidth,
        texts: [...box.children].map(c => [c.className, c.textContent]),
        overflow: [...box.children].some(c => c.scrollWidth > c.clientWidth + 1),
        titleLines: lines(box.querySelector('.cover-title')),
        header: [...document.querySelectorAll('.cover-header > div')].map(d => d.textContent),
        logo: document.querySelector('.cover-eth').textContent,
        footer: !!$('slide-1').querySelector('.slide-footer'),
        bg: getComputedStyle(document.querySelector('.cover-bg')).backgroundImage,
        warnings: Deck.warnings,
      };
    """

    def test_cover_structure(self):
        r = probe("steps_deck-cover", self.MEASURE)
        self.assertEqual(r["texts"], [["cover-title", "Fixture deck for the engine tests"],
                                      ["cover-subtitle", "Engine test (2026)"],
                                      ["cover-presenter", "Test Presenter"]])
        self.assertEqual(r["header"], ["000-0000-00L Testing", "Seminar, FS26"])
        self.assertEqual(r["logo"], "ETH zürich")
        self.assertFalse(r["footer"])
        self.assertIn("images/eth_zurich_aerial.png", r["bg"])
        self.assertEqual(r["warnings"], [])

    def test_box_shrinks_to_content(self):
        short = probe("steps_deck-cover-short", self.MEASURE, page=fixture("steps_deck", title="Short"))
        long = probe("steps_deck-cover-long", self.MEASURE, page=fixture(
            "steps_deck", title="EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks"))
        self.assertLess(short["width"], long["width"])
        self.assertLessEqual(long["width"], 0.58 * 1280 + 1)
        self.assertGreater(long["titleLines"], 1)
        self.assertEqual(short["titleLines"], 1)
        self.assertFalse(short["overflow"] or long["overflow"])
        # short title: the box is as wide as the widest of title / subtitle / presenter + padding
        self.assertLess(short["width"], 0.58 * 1280 * 0.6)

    def test_title_content_is_ignored_with_warning(self):
        page = fixture("steps_deck").replace('<section data-type="title"></section>',
                                             '<section data-type="title"><p data-step="2">custom</p></section>')
        r = probe("steps_deck-cover-content", "return { w: Deck.warnings, N: Deck.slides[0].N };", page=page)
        self.assertEqual(r["N"], 1)
        self.assertTrue(any("title slide content is ignored" in w for w in r["w"]))


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class AssetsTest(unittest.TestCase):

    IMG = """
      const box = el => { const r = el.getBoundingClientRect(), s = Deck.state.scale;
                          return [Math.round(r.width / s), Math.round(r.height / s)]; };
      const unxml = t => t.replace(/&quot;/g, '"').replace(/&amp;/g, '&');
      const label = el => unxml(decodeURIComponent((el.currentSrc || el.src || '').split(',')[1] || ''));
      const bgLabel = el => unxml(decodeURIComponent((getComputedStyle(el).backgroundImage.match(/,(.*)"\\)$/) || [])[1] || ''));
    """

    def test_missing_images_become_sized_placeholders(self):
        r = probe("assets_deck-imgs", self.IMG + """
          await new Promise(r => setTimeout(r, 300));
          Deck.goTo('imgs', 2);
          const info = id => { const el = $(id); return {
            missing: el.hasAttribute('data-asset-missing'), box: box(el),
            svg: (el.getAttribute('src') || '').startsWith('data:image/svg+xml'),
            label: label(el), shown: el.classList.contains('step-layer') ? vis(id) : null }; };
          return { ok: info('ok'), miss: info('miss'), missStep: info('miss-step'), nosize: info('nosize'),
                   missNosize: info('miss-nosize'), problems: Deck.problems.filter(p => p.slide === 2),
                   okNatural: $('ok').naturalWidth };
        """)
        self.assertFalse(r["ok"]["missing"])
        self.assertEqual(r["okNatural"], 1760)
        self.assertEqual(r["ok"]["box"], [176, 86])
        miss = r["miss"]
        self.assertTrue(miss["missing"] and miss["svg"])
        self.assertEqual(miss["box"], [400, 200])                 # CSS width 400, aspect from width/height attrs
        self.assertIn('image "missing_figure.png" not found', miss["label"])
        self.assertIn('stroke="#c9c9c9"', miss["label"])
        step = r["missStep"]
        self.assertEqual(step["box"], [150, 150])
        self.assertTrue(step["shown"], "a missing image keeps its step layer")
        self.assertFalse(r["nosize"]["missing"])
        self.assertEqual(r["missNosize"]["box"], [480, 270])     # parent width at 16:9
        by_msg = {p["message"]: p["step"] for p in r["problems"]}
        self.assertEqual(by_msg['image "missing_figure.png" not found (images/missing_figure.png)'], 0)
        self.assertEqual(by_msg['image "late.png" not found (images/late.png)'], 2)
        self.assertEqual(by_msg['image "nope.png" not found (images/nope.png)'], 1)
        self.assertIn(0, [s for m, s in by_msg.items() if 'eth_zurich_aerial.png" has no width/height' in m])
        self.assertTrue(any('"nope.png" has no width/height' in m for m in by_msg))

    def test_backgrounds_and_css_urls(self):
        r = probe("assets_deck-bgs", self.IMG + """
          await new Promise(r => setTimeout(r, 300));
          const ok = $('bg-ok'), miss = $('bg-miss'), cs = el => getComputedStyle(el);
          return {
            ok: { img: cs(ok).backgroundImage, size: cs(ok).backgroundSize, missing: ok.classList.contains('asset-missing') },
            miss: { missing: miss.classList.contains('asset-missing'), size: cs(miss).backgroundSize, label: bgLabel(miss) },
            warnings: Deck.warnings,
            cssUrlSlide: Deck.problems.find(p => p.message.startsWith('inline style loads'))?.slide,
          };
        """)
        self.assertIn("images/eth_zurich_aerial.png", r["ok"]["img"])
        self.assertEqual(r["ok"]["size"], "contain")
        self.assertFalse(r["ok"]["missing"])
        self.assertTrue(r["miss"]["missing"])
        self.assertEqual(r["miss"]["size"], "100% 100%")
        self.assertIn('image "gone.png" not found', r["miss"]["label"])
        self.assertIn('width="300" height="150"', r["miss"]["label"])
        self.assertIn('image "gone.png" not found (images/gone.png)', r["warnings"])
        self.assertEqual(r["cssUrlSlide"], 3)

    def test_missing_images_folder(self):
        r = probe("steps_deck-noimages", self.IMG + """
          await new Promise(r => setTimeout(r, 300));
          const title = $('slide-1');
          return { coverMissing: title.classList.contains('cover-missing'),
                   letterbox: $('deck-viewport').style.backgroundColor,
                   header: getComputedStyle(title.querySelector('.cover-header')).color,
                   bgLabel: bgLabel(title.querySelector('.cover-bg')),
                   problems: Deck.problems };
        """, images=False)
        self.assertTrue(r["coverMissing"])
        self.assertEqual(r["letterbox"], "rgb(255, 255, 255)")
        self.assertEqual(r["header"], "rgb(26, 26, 26)")
        self.assertIn('image "eth_zurich_aerial.png" not found', r["bgLabel"])
        self.assertIn({"message": 'image "eth_zurich_aerial.png" not found (images/eth_zurich_aerial.png)',
                       "slide": 0, "step": 0}, r["problems"])

    def test_remembered_size_for_image_without_attributes(self):
        # 1st open: image present, no width/height → its natural size is remembered (localStorage).
        # 2nd open of the same file with the image gone → placeholder keeps the real aspect ratio.
        page = fixture("steps_deck").replace(
            '<h2 class="slide-title">Basic steps</h2>',
            '<h2 class="slide-title">Basic steps</h2>'
            '<img id="mem" data-step="0" src="images/remembered.png" style="width:352px">'
            '<img id="never" data-step="0" src="images/never_seen.png" style="width:320px">')
        folder = browser.FIXTURES_OUT / "memory"
        (folder / "images").mkdir(parents=True, exist_ok=True)
        shutil.copy(browser.TEMPLATE_IMAGES / "eth_zurich_aerial.png", folder / "images" / "remembered.png")
        js = self.IMG + """
          await new Promise(r => setTimeout(r, 300));
          Deck.goTo('basic');
          return { mem: box($('mem')), memMissing: $('mem').hasAttribute('data-asset-missing'),
                   never: box($('never')),
                   stored: JSON.parse(localStorage.getItem('deck-image-sizes:' + location.pathname) || '{}') };
        """
        first = probe("steps_deck-memory", js, page=page, subdir="memory")
        self.assertFalse(first["memMissing"])
        self.assertEqual(first["stored"].get("images/remembered.png"), [1760, 862])
        (folder / "images" / "remembered.png").unlink()
        second = probe("steps_deck-memory", js, page=page, subdir="memory")
        self.assertTrue(second["memMissing"])
        self.assertEqual(second["mem"], [352, 172])            # 1760 x 862 scaled to width 352
        self.assertEqual(second["never"], [320, 180])          # never seen: 16:9 fallback
        self.assertNotIn("images/never_seen.png", second["stored"], "placeholder sizes are never remembered")

    def test_placeholders_in_dev_navigator(self):
        r = probe("assets_deck-dev", """
          await new Promise(r => setTimeout(r, 300));
          $('nav-btn').click();
          return [...document.querySelectorAll('#nav-overlay .deck-row[data-slide="2"] .row-problems li')].map(li => li.textContent);
        """, query="?dev")
        self.assertIn('step 2 · image "late.png" not found (images/late.png)', r)


LEGACY_ANIMATION = """<!DOCTYPE html><html><body><p>legacy animation without the deck contract</p>
<script>document.addEventListener('keydown', e => parent.postMessage({ type: 'keydown', key: e.key }, '*'));</script>
</body></html>"""


def anim_files() -> dict:
    return {"second_animations.html": anim_template(), "legacy_animations.html": LEGACY_ANIMATION}


def contract_js() -> str:
    page = anim_template()
    start = page.index('<script id="anim-contract-js">') + len('<script id="anim-contract-js">')
    return page[start:page.index("</script>", start)]


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class AnimationTest(unittest.TestCase):

    WAIT = "await new Promise(r => setTimeout(r, 6000));   // handshakes + missing-file timeouts\n"
    SEND = """
      const frameOf = sel => document.querySelector(sel + ' iframe');
      const send = (frame, data) => window.dispatchEvent(new MessageEvent('message', { data, source: frame.contentWindow }));
      const fwd = (frame, key) => send(frame, { ns: 'deck', v: 1, type: 'key', key });
    """

    def run_anim(self, name, js, **kw):
        return probe(name, self.WAIT + js, page=fixture("anim_deck"), files=anim_files(), budget_ms=15000, **kw)

    def test_animation_slides_handshake_and_placeholders(self):
        r = self.run_anim("anim_deck-slides", self.SEND + """
          const label = sel => {
            const ph = document.querySelector(sel + ' .anim-missing');
            if (!ph) return null;
            const m = getComputedStyle(ph).backgroundImage.match(/,(.*)"\\)$/);
            return decodeURIComponent(m ? m[1] : '').replace(/&quot;/g, '"');
          };
          return {
            src: frameOf('#anim-demo')?.getAttribute('src'),
            instances: Object.fromEntries(Deck.animations.map(a => [a.id, a.instances])),
            ghost: label('#anim-ghost'), unknown: label('#anim-unknown'), legacy: label('#anim-legacy'),
            slides: Deck.slides.filter(s => s.type === 'animation').map(s => [s.id, s.N, s.label]),
            footer: !!document.querySelector('#anim-demo .slide-footer'),
            full: document.querySelector('#anim-demo .slide-content').classList.contains('layout-full'),
            problems: Deck.problems,
          };
        """)
        self.assertEqual(r["src"], "demo_animations.html?deck-embed=1&phi=3")
        inst = r["instances"]
        self.assertEqual([(i["kind"], i["ready"], i["missing"]) for i in inst["demo"]],
                         [("slide", True, False), ("overlay", True, False), ("thumb", True, False)])
        self.assertTrue(all(i["ready"] for i in inst["second"]))
        self.assertTrue(all(i["missing"] and not i["ready"] for i in inst["ghost"]))
        self.assertTrue(all(i["missing"] for i in inst["legacy"]), "no contract = treated as missing")
        self.assertIn('animation "ghost_animations.html" not found', r["ghost"])
        self.assertIn('animation "nope" not found', r["unknown"])
        self.assertIn('animation "legacy_animations.html" not found', r["legacy"])
        self.assertEqual(r["slides"], [["anim-demo", 1, "4"], ["anim-ghost", 1, "5"],
                                       ["anim-unknown", 1, "6"], ["anim-legacy", 1, "7"]])
        self.assertTrue(r["footer"] and r["full"])
        msgs = {(p["message"], p["slide"]) for p in r["problems"]}
        ghost = 'animation "ghost_animations.html" not found (DECK.animations "ghost" → ghost_animations.html)'
        self.assertIn((ghost, 4), msgs)        # the slide instance
        self.assertIn((ghost, None), msgs)     # the ▶ button instance: deck-wide
        self.assertIn(('slide 6 ("anim-unknown"): unknown animation id "nope" (not in DECK.animations)', 5), msgs)
        self.assertTrue(any(m.startswith('animation "legacy_animations.html" not found') for m, _ in msgs))

    def test_keys_forwarded_from_the_current_animation_slide(self):
        r = self.run_anim("anim_deck-keys", self.SEND + """
          const o = {};
          Deck.goTo('anim-demo');
          send(frameOf('#anim-demo'), { ns: 'other', type: 'key', key: 'ArrowRight' });
          o.foreignNsIgnored = Deck.state.id;
          fwd(frameOf('#anim-demo'), 'ArrowRight');
          o.forward = Deck.state.id;
          Deck.goTo('anim-demo');
          fwd(frameOf('#anim-demo'), 'ArrowLeft');
          o.back = Deck.state.id;
          Deck.goTo('anim-demo');
          send(frameOf('#anim-demo'), { type: 'keydown', key: 'PageDown' });   // legacy message format
          o.legacy = Deck.state.id;
          Deck.goTo('intro');
          fwd(frameOf('#anim-demo'), 'ArrowRight');
          o.notCurrent = Deck.state.id;
          fwd(document.querySelector('#anim-overlay iframe'), 'ArrowRight');
          o.overlayIgnored = Deck.state.id;
          return o;
        """)
        self.assertEqual(r["foreignNsIgnored"], "anim-demo")
        self.assertEqual(r["forward"], "anim-ghost")
        self.assertEqual(r["back"], "intro")
        self.assertEqual(r["legacy"], "anim-ghost")
        self.assertEqual(r["notCurrent"], "intro")
        self.assertEqual(r["overlayIgnored"], "intro")

    def test_picker_overlay_instances_and_navigation_lock(self):
        r = self.run_anim("anim_deck-picker", self.SEND + """
          const o = {}, btn = $('anim-btn'), open = () => $('anim-overlay').classList.contains('open');
          o.order = [...$('deck-topbar').children].map(b => b.id);
          o.label0 = btn.textContent;
          btn.click();
          o.pickerOpen = $('anim-picker').classList.contains('open');
          o.rows = [...document.querySelectorAll('#anim-picker .deck-row')].map(row => [
            row.dataset.anim, row.querySelector('.row-label').textContent,
            !!row.querySelector('.anim-missing'), row.classList.contains('is-current')]);
          document.querySelector('#anim-picker .deck-row[data-anim="demo"]').click();
          o.afterPick = { open: open(), anim: Deck.state.animOpen, label: btn.textContent,
                          picker: $('anim-picker').classList.contains('open') };
          const demoFrame = document.querySelector('#anim-overlay .anim-box.is-active iframe');
          demoFrame.dataset.marker = 'kept';
          const before = Deck.state.id;
          key('ArrowRight'); fwd(demoFrame, 'ArrowRight'); key('Escape');
          o.blocked = Deck.state.id === before && open();
          btn.click();
          o.currentRow = document.querySelector('#anim-picker .deck-row.is-current')?.dataset.anim;
          document.querySelector('#anim-picker .deck-row[data-anim=""]').click();
          o.back = { open: open(), anim: Deck.state.animOpen, label: btn.textContent };
          key('ArrowRight');
          o.navigatesAgain = Deck.state.id !== before;
          Deck.openAnimation('demo');
          o.kept = document.querySelector('#anim-overlay .anim-box.is-active iframe')?.dataset.marker;
          Deck.openAnimation('second');
          $('nav-btn').click();
          document.querySelector('#nav-overlay .deck-row[data-slide="7"]').click();
          o.jump = { open: open(), anim: Deck.state.animOpen, id: Deck.state.id };
          return o;
        """)
        self.assertEqual(r["order"], ["anim-btn", "nav-btn"])
        self.assertEqual(r["label0"], "▶ Animations")
        self.assertTrue(r["pickerOpen"])
        self.assertEqual(r["rows"], [
            ["", "Animations fixture", False, True],     # Presentation first, current
            ["demo", "Demo", False, False],
            ["second", "Second", False, False],
            ["ghost", "Ghost", True, False],
            ["legacy", "Legacy", True, False],
        ])
        self.assertEqual(r["afterPick"], {"open": True, "anim": "demo", "label": "⇄ Switch", "picker": False})
        self.assertTrue(r["blocked"], "keys, forwarded keys and Esc do not touch an open animation")
        self.assertEqual(r["currentRow"], "demo")
        self.assertEqual(r["back"], {"open": False, "anim": None, "label": "▶ Animations"})
        self.assertTrue(r["navigatesAgain"])
        self.assertEqual(r["kept"], "kept", "the overlay instance (and its state) persists")
        self.assertEqual(r["jump"], {"open": False, "anim": None, "id": "after"})

    def test_single_and_no_animation_button(self):
        r = probe("steps_deck-anim-single", """
          await new Promise(r => setTimeout(r, 2500));
          const btn = $('anim-btn'), o = { order: [...$('deck-topbar').children].map(b => b.id) };
          o.labels = [btn.textContent];
          btn.click(); o.labels.push(btn.textContent); o.open = Deck.state.animOpen;
          btn.click(); o.labels.push(btn.textContent); o.closed = Deck.state.animOpen;
          o.picker = !!$('anim-picker');
          return o;
        """, budget_ms=8000)
        self.assertEqual(r["order"], ["anim-btn", "nav-btn"])
        self.assertEqual(r["labels"], ["▶ Animation", "◀ Presentation", "▶ Animation"])
        self.assertEqual((r["open"], r["closed"], r["picker"]), ("demo", None, False))
        r = probe("assets_deck-noanim", "return { btn: !!$('anim-btn'), overlay: !!$('anim-overlay') };")
        self.assertEqual(r, {"btn": False, "overlay": False})

    def test_contract_snippet(self):
        js = """
          const frame = document.createElement('iframe');
          const got = [];
          addEventListener('message', e => { if (e.source === frame.contentWindow) got.push(e.data); });
          frame.srcdoc = '<!doctype html><body><input id="t" type="text"><input id="r" type="range">' +
            '<script>window.applyPreset = c => parent.postMessage({ presetSeen: c }, "*");<\\/script>' +
            '<script>' + CONTRACT + '<\\/script></body>';
          document.body.appendChild(frame);
          await new Promise(r => frame.addEventListener('load', r, { once: true }));
          await new Promise(r => setTimeout(r, 50));
          const win = frame.contentWindow, doc = frame.contentDocument;
          const press = (target, key, opts = {}) =>
            target.dispatchEvent(new win.KeyboardEvent('keydown', { key, bubbles: true, ...opts }));
          press(doc.body, 'ArrowRight');
          press(doc.body, 'ArrowRight', { ctrlKey: true });
          press(doc.body, 'ArrowLeft', { shiftKey: true });
          press(doc.body, 'End', { ctrlKey: true });
          press(doc.getElementById('t'), ' ');
          press(doc.getElementById('r'), 'ArrowLeft');
          press(doc.body, 'x');
          win.postMessage({ ns: 'deck', v: 1, type: 'ping' }, '*');
          win.postMessage({ ns: 'deck', v: 1, type: 'preset', preset: { phi: 2 } }, '*');
          await new Promise(r => setTimeout(r, 100));
          return { got, embedded: win.DeckAnim.embedded };
        """.replace("CONTRACT", __import__("json").dumps(contract_js()))
        r = probe("assets_deck-contract", js)
        got = r["got"]
        self.assertTrue(r["embedded"])
        self.assertEqual(got[0]["type"], "ready")
        keys = [m["key"] for m in got if m.get("type") == "key"]
        self.assertEqual(keys, ["ArrowRight", "End", "ArrowLeft"])   # Ctrl/Shift+arrows stay; text input ignored
        self.assertTrue(all(m.get("ns") == "deck" and m.get("v") == 1 for m in got if "type" in m))
        self.assertEqual([m["type"] for m in got if m.get("type") == "ready"], ["ready", "ready"])   # load + ping
        self.assertIn({"presetSeen": {"phi": 2}}, got)

    def test_template_animation_panel_system(self):
        r = browser.run(anim_template(), """
          const wait = ms => new Promise(r => setTimeout(r, ms));
          const shown = () => [...document.querySelectorAll('.panel.active')]
            .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x).map(p => p.dataset.panel);
          const click = id => document.querySelector(`.scard[data-panel="${id}"] .scard-header`).click();
          const o = { embedded: DeckAnim.embedded, order: Panels.order };
          await wait(600);
          o.default = shown();
          o.bars = document.querySelectorAll('#scaling-viz rect').length;
          o.phi = document.getElementById('phi-val').textContent;
          click('notes'); click('grid'); await wait(600);
          o.three = { queue: Panels.openIds, shown: shown() };        // opened out of order, shown in sidebar order
          click('formula'); await wait(600);
          o.fourth = { queue: Panels.openIds, shown: shown() };       // the oldest (scaling) closed
          o.katex = document.querySelectorAll('#formula .katex').length;
          o.cards = [...document.querySelectorAll('.scard.open')].map(c => c.dataset.panel);
          click('grid'); await wait(100);
          o.closed = Panels.openIds;
          applyPreset({ open: ['grid', 'scaling'] }); await wait(600);
          o.preset = shown();
          return o;
        """, "template_animations-panels", query="?phi=3", budget_ms=8000)
        self.assertFalse(r["embedded"])
        self.assertEqual(r["order"], ["scaling", "formula", "grid", "notes"])
        self.assertEqual(r["default"], ["scaling"])                         # first panel by default
        self.assertEqual((r["bars"], r["phi"]), (1 + 6, "3"))               # input + round(2*1.2^3 + 3) layers
        self.assertEqual(r["three"], {"queue": ["scaling", "notes", "grid"], "shown": ["scaling", "grid", "notes"]})
        self.assertEqual(r["fourth"], {"queue": ["notes", "grid", "formula"], "shown": ["formula", "grid", "notes"]})
        self.assertEqual(r["katex"], 1)
        self.assertEqual(r["cards"], ["formula", "grid", "notes"])
        self.assertEqual(r["closed"], ["notes", "formula"])                 # clicking an open card closes it
        self.assertEqual(r["preset"], ["scaling", "grid"])                  # URL order does not matter


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class MathAndCodeTest(unittest.TestCase):

    def test_escaped_dollars_and_display_size(self):
        r = probe("p5_deck-math", """
          const p = $('dollars');
          return {
            text: [...p.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join('|'),
            katex: p.querySelectorAll('.katex').length,
            tex: [...p.querySelectorAll('annotation')].map(a => a.textContent),
            display: getComputedStyle($('display').querySelector('.katex-display > .katex')).fontSize,
            inline: getComputedStyle(p.querySelector('.katex')).fontSize,
            code: $('code-dollar').textContent,
            warnings: Deck.warnings,
          };
        """)
        self.assertEqual(r["warnings"], ["code language \"rust\" is not coloured automatically (only python); "
                                         "use the token classes .ck .cf .ca .cn .cs .cc"])
        self.assertIn("It costs $5 and ", r["text"])
        self.assertIn(" and $10, inside math ", r["text"])
        self.assertEqual(r["katex"], 2)
        self.assertEqual(r["tex"], ["x^2", "a \\$ b"])
        self.assertEqual(r["display"], "36px")                    # --fs-math
        self.assertEqual(r["inline"], f"{27 * 1.21:.2f}".rstrip("0") + "px")   # KaTeX 1.21em of --fs-body
        self.assertEqual(r["code"], "echo \\$HOME", "code blocks are left alone")

    def test_python_highlighting(self):
        r = probe("p5_deck-code", """
          const spans = id => [...$(id).querySelectorAll('span')].map(s => [s.className, s.textContent]);
          return { py: spans('py'), text: $('py').textContent, manual: $('manual').innerHTML, rust: $('rust').innerHTML };
        """)
        self.assertEqual(r["py"], [
            ["cn", "1"], ["ck", "self"], ["cf", "Conv2d"], ["ca", "in_channels"], ["cn", "3"], ["ca", "name"],
            ["cs", '"a=b"'], ["cn", "2"], ["cc", "# done"], ["ck", "def"], ["cf", "f"], ["ck", "return"], ["ck", "None"],
        ])
        self.assertTrue(r["text"].startswith("x = 1\nself.conv"), "text is unchanged, only wrapped")
        self.assertEqual(r["manual"], '<span class="cf">kept</span>(x)', "hand-coloured blocks stay as written")
        self.assertEqual(r["rust"], "fn main() {}")


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class ComponentsTest(unittest.TestCase):

    def test_components_button_and_panel(self):
        r = probe("steps_deck-components", """
          const btn = $('comp-btn');
          const o = { order: [...$('deck-topbar').children].map(b => b.id), label: btn.textContent };
          btn.click();
          o.open = $('comp-overlay').classList.contains('open');
          o.wide = $('comp-overlay').querySelector('.deck-panel').classList.contains('wide');
          o.inSlides = !!$('nav-overlay').querySelector('.comp-item');
          const panel = $('comp-overlay').querySelector('.deck-panel').getBoundingClientRect();
          o.items = [...document.querySelectorAll('#comp-overlay .comp-item')].map(item => {
            const p = item.querySelector('.comp-preview').getBoundingClientRect();
            const s = item.querySelector('.comp-stage').getBoundingClientRect();
            return { title: item.querySelector('.comp-title').textContent, from: item.querySelector('.comp-from').textContent,
                     h: p.height, fitsPreview: s.width <= p.width + 1, fitsPanel: p.right <= panel.right && p.left >= panel.left,
                     folded: !item.querySelector('details').open, code: item.querySelector('pre').textContent.length };
          });
          o.glow = !!document.querySelector('#comp-overlay .hl-orange');
          o.katex = document.querySelectorAll('#comp-overlay .katex').length;
          key('ArrowRight'); o.locked = Deck.state.id === 'slide-1';
          key('Escape'); o.closed = !$('comp-overlay').classList.contains('open');
          return o;
        """, query="?dev")
        self.assertEqual(r["order"], ["anim-btn", "comp-btn", "nav-btn"])
        self.assertEqual(r["label"], "▦ Components")
        self.assertTrue(r["open"] and r["wide"])
        self.assertFalse(r["inSlides"], "components are no longer part of the Slides panel")
        names = [c["name"] for c in build.component_catalog()]
        self.assertEqual([i["title"] for i in r["items"]], names)
        for item in r["items"]:
            with self.subTest(item["title"]):
                self.assertTrue(item["from"].startswith("from: "))
                self.assertGreater(item["h"], 40)
                self.assertTrue(item["fitsPreview"] and item["fitsPanel"], "examples never overflow")
                self.assertTrue(item["folded"])
                self.assertGreater(item["code"], 20)
        self.assertTrue(r["glow"], "open-ended data-step-class rules are shown (final state)")
        self.assertGreater(r["katex"], 3)
        self.assertTrue(r["locked"] and r["closed"])
        r = probe("steps_deck-nocomponents", "return { btn: !!$('comp-btn'), overlay: !!$('comp-overlay') };")
        self.assertEqual(r, {"btn": False, "overlay": False}, "Components is a ?dev authoring tool only")

    def test_every_catalog_snippet_works_as_a_slide(self):
        catalog = build.component_catalog()
        sections = "\n".join(f'<section data-type="content" id="c{i}"><h2 class="slide-title">{c["name"]}</h2>\n{c["html"]}\n</section>'
                             for i, c in enumerate(catalog))
        shell = (FIXTURES / "p5_deck.html").read_text(encoding="utf-8")
        start, end = shell.index('<section data-type="content" id="math">'), shell.index('<section data-type="black">')
        page = build.build_deck(shell[:start] + sections + "\n" + shell[end:], build.engine_version())
        r = probe("p5_deck-catalog", "await new Promise(r => setTimeout(r, 300)); return Deck.warnings;", page=page)
        unexpected = [w for w in r if "not found (images/your_" not in w]
        self.assertEqual(unexpected, [])

    def test_efficientnet_project_on_current_engine(self):
        # presentations/EfficientNet is a normal project; run a copy upgraded to the current engine
        # (exactly what tools/update.py does), so engine changes cannot silently break it.
        project = build.ROOT / "presentations" / "EfficientNet"
        folder = browser.FIXTURES_OUT / "efficientnet"
        shutil.copytree(project / "images", folder / "images", dirs_exist_ok=True)
        version = build.engine_version()
        deck = _blocks.replace((project / "EfficientNet_presentation.html").read_text(encoding="utf-8"),
                               _blocks.DECK_ENGINE, build.deck_engine_block(version))
        anim = (project / "EfficientNet_animations.html").read_text(encoding="utf-8")
        for name, block in ((_blocks.ANIM_VENDOR, build.anim_vendor_block(version)),
                            (_blocks.ANIM_CONTRACT, build.anim_contract_block(version))):
            anim = _blocks.replace(anim, name, block)
        self.assertNotIn("fonts.googleapis", anim)
        self.assertNotIn("postMessage({ type: 'keydown'", anim, "the contract forwards keys, not the old code")
        r = probe("efficientnet", """
          await new Promise(r => setTimeout(r, 7000));
          return { w: Deck.warnings, s: Deck.slides.map(s => [s.id, s.type, s.N, s.label]),
                   anim: Deck.animations.map(a => a.instances.map(i => [i.kind, i.ready, i.missing])),
                   btn: document.getElementById('anim-btn').textContent };
        """, page=deck, subdir="efficientnet", files={"EfficientNet_animations.html": anim}, budget_ms=20000)
        self.assertEqual(r["w"], [])
        self.assertEqual(len(r["s"]), 21)                                   # 20 original slides + TOC
        types = [t for _, t, _, _ in r["s"]]
        self.assertEqual(types.count("animation"), 5)
        steps = {sid: n for sid, _, n, _ in r["s"]}
        self.assertEqual((steps["motivation"], steps["pimr"], steps["resolution"], steps["arms-race"], steps["constraints"]),
                         (5, 4, 5, 4, 3))
        self.assertEqual(r["s"][-1][3], "Appendix 1")
        self.assertTrue(all(ready and not missing for kind, ready, missing in r["anim"][0]), r["anim"])
        self.assertEqual(r["btn"], "▶ Animation")

    def test_template_has_no_warnings(self):
        r = probe("template", "return { w: Deck.warnings, t: Deck.slides.map(s => s.title) };",
                  page=build.build_outputs()["template_presentation.html"].decode("utf-8"))
        self.assertEqual(r["w"], [])
        self.assertEqual(r["t"][2:], ["Slide 3 – title", "Slide 4 – title", "Slide 5 – title", "End", "Appendix 1 – title"])


WALK = """
  await new Promise(r => setTimeout(r, 500));
  const total = Deck.slides.reduce((n, s) => n + s.N, 0);
  let forward = 1, back = 1;
  while (Deck.next()) forward++;
  const end = Deck.state;
  while (Deck.prev()) back++;
  return { total, forward, back, end, start: Deck.state, last: Deck.slides.length - 1,
           errors: window.__deckErrors, warnings: Deck.warnings };
"""


@unittest.skipUnless(browser.find_browser(), "no Chromium-based browser found")
class RegressionTest(unittest.TestCase):
    """Bugs found in the final review (each test fails on the old code)."""

    def test_walk_through_template_and_efficientnet(self):
        cases = [("template-walk", build.build_outputs()["template_presentation.html"].decode("utf-8"), {}, None)]
        project = build.ROOT / "presentations" / "EfficientNet"
        folder = browser.FIXTURES_OUT / "efficientnet"
        shutil.copytree(project / "images", folder / "images", dirs_exist_ok=True)
        deck = _blocks.replace((project / "EfficientNet_presentation.html").read_text(encoding="utf-8"),
                               _blocks.DECK_ENGINE, build.deck_engine_block(build.engine_version()))
        cases.append(("efficientnet-walk", deck,
                      {"EfficientNet_animations.html": (project / "EfficientNet_animations.html").read_text(encoding="utf-8")},
                      "efficientnet"))
        for name, page, files, subdir in cases:
            with self.subTest(name):
                r = probe(name, WALK, page=page, files=files, subdir=subdir, budget_ms=20000)
                self.assertEqual(r["errors"], [])
                self.assertEqual(r["forward"], r["total"], "every step of every slide is visited going forward")
                self.assertEqual(r["back"], r["total"], "and going back")
                self.assertEqual((r["end"]["current"], r["start"]["current"], r["start"]["step"]), (r["last"], 0, 0))

    def test_closed_panels_are_not_focusable_and_open_panels_keep_their_keys(self):
        r = probe("steps_deck-panelkeys", """
          const nav = $('nav-overlay'), visibility = () => getComputedStyle(nav).visibility;
          const o = { closed: visibility() };
          $('nav-btn').click();
          o.open = visibility();
          const before = Deck.state.id;
          o.notPrevented = key('ArrowDown') && key(' ');      // the panel may scroll / use Space itself
          o.unchanged = Deck.state.id === before;
          key('Escape');
          o.afterEsc = Deck.state.locked;
          return o;
        """, query="?dev")
        self.assertEqual((r["closed"], r["open"]), ("hidden", "visible"))
        self.assertTrue(r["notPrevented"])
        self.assertTrue(r["unchanged"])
        self.assertFalse(r["afterEsc"])

    def test_authoring_example_slide_matches_its_description(self):
        guide = (build.ROOT / "AUTHORING.md").read_text(encoding="utf-8")
        example = guide[guide.index("**A complete content slide**"):]
        example = example[example.index("```html\n") + 8:example.index("\n```", example.index("```html"))]
        shell = (FIXTURES / "p5_deck.html").read_text(encoding="utf-8")
        start, end = shell.index('<section data-type="content" id="math">'), shell.index('<section data-type="black">')
        page = build.build_deck(shell[:start] + example + "\n" + shell[end:], build.engine_version())
        r = probe("p5_deck-authoring-example", """
          await new Promise(r => setTimeout(r, 300));
          return { s: Deck.slides.find(s => s.id === 'results'), w: Deck.warnings };
        """, page=page)
        self.assertEqual(r["s"]["N"], 4, "title, figure, red line, conclusion")
        self.assertEqual([w for w in r["w"] if "results.png" not in w], [])

    def test_math_in_navigator_labels(self):
        r = probe("p5_deck-navmath", "return document.querySelector('#nav-overlay .deck-row[data-slide=\"2\"] .row-label .katex') !== null;")
        self.assertTrue(r)

    def test_template_panels_ignore_unknown_and_duplicate_ids(self):
        r = browser.run(anim_template(), """
          const wait = ms => new Promise(r => setTimeout(r, ms));
          applyPreset({ open: ['typo'] }); await wait(100);
          const typo = Panels.openIds;
          applyPreset({ open: ['grid', 'grid', 'formula'] }); await wait(100);
          return { typo, dup: Panels.openIds };
        """, "template_animations-ids")
        self.assertEqual(r, {"typo": ["scaling"], "dup": ["grid", "formula"]})


if __name__ == "__main__":
    unittest.main()
