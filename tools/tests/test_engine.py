"""Browser tests for the deck engine (P1: canvas, slides, steps, navigation, warnings).

Each test builds a fixture deck from tools/tests/fixtures/, opens it in headless Edge/Chrome
via file:// (network disabled) and drives it through the public `Deck` API and synthetic key
events. Skipped when no Chromium-based browser is installed.
    Run: python -m unittest discover tools/tests
"""
from __future__ import annotations

import datetime
import sys
import unittest
from functools import lru_cache
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))
import browser  # noqa: E402
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
def fixture(name: str, date: str | None = None) -> str:
    shell = (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
    if date is not None:
        shell = shell.replace("date:      '01.02.2026'", f"date:      '{date}'")
    return build.build_deck(shell, build.engine_version())


def probe(name: str, js: str, page: str | None = None, **kw):
    return browser.run(page or fixture(name.split("-")[0]), HELPERS + js, name, **kw)


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
        self.assertEqual([s["N"] for s in slides], [1, 1, 3, 4, 3, 5, 1, 1, 2, 1])
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
          for (let i = 0; i < 3; i++) { out.basic.push([Deck.state.step, vis('b2'), vis('b3')]); Deck.next(); }
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
          out.b1Layer = $('b1').classList.contains('step-layer');
          out.fx = ['r-late', 'r-slide', 'r-none', 'b2'].map(id => [...$(id).classList].filter(c => c.startsWith('fx-')));
          return out;
        """)
        self.assertEqual(r["basic"], [[1, False, False], [2, True, False], [3, True, True]])
        self.assertEqual(r["ranges"], [
            [1, False, False, False, False],
            [2, True, False, False, True],
            [3, True, True, False, True],
            [4, False, False, True, True],
        ])
        self.assertEqual(r["classes"], [[1, False, False], [2, True, False], [3, False, True]])
        self.assertFalse(r["b1Layer"])
        self.assertEqual(r["fx"], [["fx-fade"], ["fx-slide-left"], ["fx-none"], ["fx-rise"]])

    def test_navigation_state_machine_and_step_memory(self):
        r = probe("steps_deck-nav", """
          const o = {};
          o.start = st();
          o.prevAtStart = Deck.prev();
          Deck.next(); Deck.next();                       // toc -> basic (step 1)
          o.enterForward = st();
          Deck.next(); Deck.next(); Deck.next();          // basic 2, 3 -> ranges 1
          Deck.next();                                    // ranges 2
          Deck.prev(); Deck.prev();                       // ranges 1 -> basic (visited: restore 3)
          o.backToVisited = st();
          Deck.next();                                    // -> ranges (visited: restore 1)
          o.forwardToVisited = st();
          Deck.goTo('hooked');                            // unvisited jump -> step 1
          o.jumpUnvisited = st();
          Deck.next(); Deck.next();                       // hooked 3
          Deck.goTo('basic'); Deck.goTo('hooked');        // jump to visited -> restore 3
          o.jumpVisited = st();
          Deck.goTo('app2');
          Deck.prev();                                    // app1 unvisited, entered backwards -> N
          o.backUnvisited = st();
          Deck.prev(); Deck.prev();                       // app1 1 -> black
          o.black = st();
          Deck.prev();                                    // math (unvisited, N=1)
          o.math = st();
          Deck.goTo('ranges', 99); o.clampHigh = st();
          Deck.goTo('ranges', 0);  o.clampLow = st();
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
        self.assertEqual(r["start"], {"id": "slide-1", "step": 1, "label": "1"})
        self.assertFalse(r["prevAtStart"])
        self.assertEqual(r["enterForward"], {"id": "basic", "step": 1, "label": "3"})
        self.assertEqual(r["backToVisited"], {"id": "basic", "step": 3, "label": "3"})
        self.assertEqual(r["forwardToVisited"], {"id": "ranges", "step": 1, "label": "4"})
        self.assertEqual(r["jumpUnvisited"], {"id": "hooked", "step": 1, "label": "6"})
        self.assertEqual(r["jumpVisited"], {"id": "hooked", "step": 3, "label": "6"})
        self.assertEqual(r["backUnvisited"], {"id": "app1", "step": 2, "label": "Appendix 1"})
        self.assertEqual(r["black"], {"id": "slide-8", "step": 1, "label": ""})
        self.assertEqual(r["math"], {"id": "math", "step": 1, "label": "7"})
        self.assertEqual(r["clampHigh"]["step"], 4)
        self.assertEqual(r["clampLow"]["step"], 1)
        self.assertFalse(r["badGoTo"])
        self.assertFalse(r["nextAtEnd"])
        self.assertEqual(r["end"]["id"], "app2")
        # hook: [step, first, N, preview] for every render of 'hooked'
        self.assertEqual(r["hookCalls"], [[1, True, 5, False], [2, False, 5, False], [3, False, 5, False],
                                          [3, False, 5, False]])
        self.assertEqual(r["activeCount"], 1)
        self.assertTrue(r["inertOthers"])
        self.assertEqual(r["warnings"], ['Deck.goTo: no slide "nope"'])

    def test_keyboard(self):
        r = probe("steps_deck-keys", """
          const o = { forward: {}, back: {} };
          for (const k of ['ArrowRight', 'ArrowDown', ' ', 'PageDown', 'End']) {
            Deck.goTo('basic', 1);
            const notPrevented = key(k);
            o.forward[k] = [Deck.state.step, notPrevented];
          }
          for (const k of ['ArrowLeft', 'ArrowUp', 'PageUp', 'Home']) {
            Deck.goTo('basic', 2); key(k); o.back[k] = Deck.state.step;
          }
          Deck.goTo('basic', 1); key('End', { ctrlKey: true }); o.ctrlEnd = Deck.state.step;
          Deck.goTo('basic', 2); key('ArrowLeft', { altKey: true }); o.altLeft = Deck.state.step;
          Deck.goTo('basic', 2); key('ArrowLeft', { metaKey: true }); o.metaLeft = Deck.state.step;
          Deck.goTo('basic', 1); key('x'); o.otherKey = Deck.state.step;
          const input = document.createElement('input'); document.body.appendChild(input); input.focus();
          Deck.goTo('basic', 1); key('ArrowRight', {}, input); o.inInput = Deck.state.step;
          return o;
        """)
        for k, (step, not_prevented) in r["forward"].items():
            self.assertEqual(step, 2, k)
            self.assertFalse(not_prevented, f"{k} must call preventDefault")
        self.assertEqual(r["back"], {"ArrowLeft": 1, "ArrowUp": 1, "PageUp": 1, "Home": 1})
        self.assertEqual(r["ctrlEnd"], 2)
        self.assertEqual(r["altLeft"], 2)
        self.assertEqual(r["metaLeft"], 2)
        self.assertEqual(r["otherKey"], 1)
        self.assertEqual(r["inInput"], 1)

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
            'invalid data-step="2..1"',
            'unknown data-step-fx="wobble"',
            'invalid data-step-class rule "hi"',
            'data-steps="1" is lower than the highest step used (3)',
            'unknown data-layout="sideways"',
            "has no title",
            'DECK.hooks["ghost"] does not match any slide id',
            'DECK.hooks["thrower"] threw: boom',
            'formula error in "\\notacommand"',
        ]
        joined = "\n".join(r["warnings"])
        for fragment in expected:
            self.assertIn(fragment, joined)
        self.assertEqual(r["labels"], ["1", "2", "3", "4", "5"])   # no black: everything is main
        self.assertTrue(r["redFormula"], "a broken formula is still rendered (in red) by KaTeX")


if __name__ == "__main__":
    unittest.main()
