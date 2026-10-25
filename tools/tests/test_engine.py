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
        self.assertEqual([s["N"] for s in slides], [1, 2, 3, 4, 3, 5, 2, 1, 2, 1])   # toc + math: title, then content
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
          for (let i = 0; i < 3; i++) { out.basic.push([Deck.state.step, ...ids.map(vis)]); Deck.next(); }
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
            [1, False, False, False, True, False, True, False, True],    # step 1: title + explicit step-1 only
            [2, True, True, False, True, True, True, False, True],
            [3, True, True, True, True, True, True, True, False],        # 1..2 layer removed again
        ])
        self.assertTrue(r["titleAlways"])
        self.assertTrue(r["listStructural"])
        self.assertEqual(r["implicit"], ["b1", "b-li-plain"])
        self.assertEqual(r["ranges"], [
            [1, False, False, False, False],
            [2, True, False, False, True],
            [3, True, True, False, True],
            [4, False, False, True, True],
        ])
        self.assertEqual(r["classes"], [[1, False, False], [2, True, False], [3, False, True]])
        self.assertEqual(r["fx"], [["fx-fade"], ["fx-slide-left"], ["fx-none"], ["fx-rise"]])

    def test_navigation_state_machine_and_step_memory(self):
        r = probe("steps_deck-nav", """
          const o = {};
          o.start = st();
          o.prevAtStart = Deck.prev();
          Deck.next(); Deck.next(); Deck.next();          // toc 1, toc 2 (list) -> basic (step 1)
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
          Deck.prev();                                    // math (unvisited, entered backwards -> N=2)
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
        self.assertEqual(r["math"], {"id": "math", "step": 2, "label": "7"})
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
        self.assertEqual((r["state"]["id"], r["state"]["step"]), ("ranges", 4))   # final step
        self.assertEqual(r["after"]["step"], 4)
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
          o.loadingAtStart = frames.filter(f => f.getAttribute('src')).length;   // one at a time
          await new Promise(done => {{
            const t0 = performance.now();
            (function poll() {{
              if (frames.every(f => f.getAttribute('src')) || performance.now() - t0 > 7000) done();
              else setTimeout(poll, 100);
            }})();
          }});
          Deck.goTo('basic', 3); Deck.goTo('math');
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
          o.toVisited = st();                                 // basic was left at step 3
          btn.click(); document.querySelector('#nav-overlay .deck-row[data-slide="3"]').click();
          o.toUnvisited = st();
          o.closed = !$('nav-overlay').classList.contains('open');
          return o;
        """, budget_ms=8000)
        self.assertEqual(r["button"], {"text": "☰ Slides", "red": False, "last": True})
        self.assertFalse(r["devBtn"])
        self.assertEqual(r["hint"], "← → to navigate")
        self.assertEqual(r["loadingAtStart"], 1, "thumbnails start loading one at a time")
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
        self.assertEqual(r["toVisited"], {"id": "basic", "step": 3, "label": "3"})
        self.assertEqual(r["toUnvisited"], {"id": "ranges", "step": 1, "label": "4"})
        self.assertTrue(r["closed"])

    def test_dev_problems_in_navigator(self):
        r = probe("broken_deck-nav-dev", f"""
          const o = {{}};
          Deck.goTo('thrower');                                  // runs the throwing hook (step 1)
          o.red = $('nav-btn').classList.contains('has-problems');
          o.devBtn = !!$('dev-btn');
          $('nav-btn').click();
          const box = document.querySelector('#nav-overlay .nav-deck-problems');
          o.deckBox = {{ hidden: box.hidden, items: [...box.querySelectorAll('li')].map(li => li.textContent) }};
          o.rows = {self.ROWS};
          document.querySelector('#nav-overlay .deck-row[data-slide="5"]').click();
          o.late = st();                                         // first problem at step 3
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
        self.assertIn('step 1 · slide 3: unknown data-type="weird"', joined)
        self.assertIn('step 2 · slide 3 ("thrower"): unknown data-step-fx="wobble"', joined)
        self.assertIn("step 1 · DECK.hooks[\"thrower\"] threw: boom", joined)
        self.assertIn('step 2 · formula error in "\\notacommand"', joined)       # implicit step-2 paragraph
        self.assertEqual(rows[5]["problems"], [rows[5]["problems"][0]])
        self.assertTrue(rows[5]["problems"][0].startswith('step 3 · formula error in "\\alsonotacommand"'))
        self.assertEqual(r["late"], {"id": "late", "step": 3, "label": "6"})
        self.assertEqual(r["thrower"]["step"], 1)
        late = [p for p in r["problems"] if p["slide"] == 5]
        self.assertEqual([p["step"] for p in late], [3])

    def test_dev_clean_slide_uses_step_memory(self):
        r = probe("steps_deck-nav-dev", """
          const o = { red: $('nav-btn').classList.contains('has-problems') };
          Deck.goTo('ranges', 3); Deck.goTo(0);
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
        self.assertEqual(r["ranges"]["step"], 3)


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
          Deck.goTo('imgs', 3);
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
        self.assertEqual(by_msg['image "missing_figure.png" not found (images/missing_figure.png)'], 1)
        self.assertEqual(by_msg['image "late.png" not found (images/late.png)'], 3)
        self.assertEqual(by_msg['image "nope.png" not found (images/nope.png)'], 2)
        self.assertIn(1, [s for m, s in by_msg.items() if 'eth_zurich_aerial.png" has no width/height' in m])
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
                       "slide": 0, "step": 1}, r["problems"])

    def test_remembered_size_for_image_without_attributes(self):
        # 1st open: image present, no width/height → its natural size is remembered (localStorage).
        # 2nd open of the same file with the image gone → placeholder keeps the real aspect ratio.
        page = fixture("steps_deck").replace(
            '<h2 class="slide-title">Basic steps</h2>',
            '<h2 class="slide-title">Basic steps</h2>'
            '<img id="mem" data-step="1" src="images/remembered.png" style="width:352px">'
            '<img id="never" data-step="1" src="images/never_seen.png" style="width:320px">')
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
        self.assertIn('step 3 · image "late.png" not found (images/late.png)', r)


if __name__ == "__main__":
    unittest.main()
