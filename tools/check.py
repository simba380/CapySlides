"""Check a presentation: every problem the ?dev view shows, image sizes and engine versions.

    python tools/check.py <deck.html | folder> [--json]

Runs each deck headless in Chrome/Edge (offline, file://) and prints its problems per slide and
step (missing images/animations, bad step attributes, formula errors, files outside the folder,
…), plus <img> tags whose width/height are missing or wrong, images that animation files cannot
load, plus outdated engine versions.
Exit code 1 if anything needs fixing, 2 on usage errors. Without a browser only the static
checks run (and a note says so).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _blocks  # noqa: E402
import _browser  # noqa: E402
import _deckfolder as df  # noqa: E402
import image_sizes  # noqa: E402

SETTLE = """
  // Wait until every image has loaded or failed and every animation instance has answered the
  // handshake or been declared missing (at most 30 s), then a short grace for background images.
  const settled = () => [...document.images].every(img => img.complete)
    && Deck.animations.every(a => a.instances.every(i => i.ready || i.missing));
  const t0 = performance.now();
  while (!settled() && performance.now() - t0 < 30000) await new Promise(r => setTimeout(r, 200));
  await new Promise(r => setTimeout(r, 500));
"""
PROBE = SETTLE + """
  return { problems: Deck.problems, version: Deck.version, errors: window.__deckErrors || [],
           slides: Deck.slides.map(s => ({ label: s.label, title: s.title, type: s.type })) };
"""
# Every local file the running deck uses, after the engine has filled in its defaults (e.g. the
# cover image when DECK.cover names none): images, backgrounds, animation frames, links.
ASSETS_PROBE = SETTLE + r"""
  const ATTRS = ['src', 'data-bg', 'href', 'poster', 'data-asset-missing'];
  const local = v => v && !/^\s*(#|[a-z][a-z0-9+.-]*:)/i.test(v);   // no data:, file:, http:, #anchor
  const used = new Set();
  for (const el of document.querySelectorAll(ATTRS.map(a => `[${a}]`).join(',')))
    for (const a of ATTRS) if (local(el.getAttribute(a))) used.add(el.getAttribute(a).trim());
  return [...used];
"""
# An animation file on its own: the <img> sources that do not load. Each one is loaded afresh, so
# images in hidden views count too.
ANIM_PROBE = """
  const loads = src => new Promise(ok => { const im = new Image(); im.onload = () => ok(true); im.onerror = () => ok(false); im.src = src; });
  const srcs = new Set([...document.images].map(img => img.getAttribute('src') || '').filter(s => s && !/^data:/i.test(s)));
  const broken = [];
  for (const src of srcs) if (!(await loads(src))) broken.push(src);
  return broken;
"""


@dataclass
class Report:
    deck: Path
    version: str | None = None
    slides: list = field(default_factory=list)
    issues: list = field(default_factory=list)   # (where, message): need fixing
    notes: list = field(default_factory=list)    # informational

    @property
    def ok(self) -> bool:
        return not self.issues


def slide_name(slides: list, index) -> str:
    if index is None:
        return "Deck"
    s = slides[index] if 0 <= index < len(slides) else {"label": str(index + 1), "title": ""}
    label = s["label"]
    name = "Black slide" if not label else label if label.startswith("Appendix") else f"Slide {label}"
    return f'{name} "{s["title"]}"'


def check_deck(deck: Path, runtime: bool = True, progress=None) -> Report:
    """`progress(text)`, if given, is told what is being checked (pack.py prints it)."""
    progress = progress or (lambda text: None)
    text = deck.read_text(encoding="utf-8")
    report = Report(deck, df.block_version(text, _blocks.DECK_ENGINE))
    repo = df.repo_version()
    if report.version is None:
        report.issues.append(("Deck", "no DECK-ENGINE block found: not a CapySlides deck?"))
    elif df.version_tuple(report.version) < df.version_tuple(repo):
        report.notes.append(f"engine v{report.version} is older than the repository's v{repo}: run {df.tool('update.py')} \"{deck.parent}\"")
    for anim in df.find_animations(deck.parent):
        v = df.block_version(anim.read_text(encoding="utf-8"), _blocks.ANIM_CONTRACT)
        if v is None:
            report.notes.append(f"{anim.name} has no ANIM-CONTRACT block: the deck will treat it as missing")
        elif df.version_tuple(v) < df.version_tuple(repo):
            report.notes.append(f"{anim.name} uses contract v{v}, older than v{repo}: run update.py")

    for status, img, detail in image_sizes.process(deck, text).rows:
        if status == "updated":
            report.issues.append(("Images", f"line {img.line}: {img.src} has missing/wrong width/height ({detail}) → run {df.tool('image_sizes.py')} \"{deck}\""))
        elif status == "unreadable":
            report.issues.append(("Images", f"line {img.line}: {img.src} cannot be read ({detail})"))

    if runtime and _browser.find_browser():
        progress(f"running {deck.name}: every slide, image and animation …")
        result = _browser.probe_file(deck, PROBE)
        report.slides = result["slides"]
        for p in sorted(result["problems"], key=lambda p: (-1 if p["slide"] is None else p["slide"], p["step"])):
            where = slide_name(report.slides, p["slide"]) + ("" if p["slide"] is None else f", step {p['step']}")
            report.issues.append((where, p["message"]))
        for message in result.get("errors", []):
            report.issues.append(("JavaScript", f"uncaught error: {message}"))
        for anim in df.find_animations(deck.parent):
            progress(f"loading the images of {anim.name} …")
            for src in _browser.probe_file(anim, ANIM_PROBE, budget_ms=15000):
                report.issues.append((anim.name, f'image "{src}" not found'))
    elif runtime:
        report.notes.append("no working Chrome/Edge found: runtime checks (slides, images, animations) skipped")
    return report


def deck_assets(deck: Path) -> list[str]:
    """The local references of the running deck (as written, e.g. "images/x.png", "a_animations.html?view=2")."""
    return _browser.probe_file(deck, ASSETS_PROBE)


def report_lines(r: Report) -> list[str]:
    """The report without its summary, unindented: the deck line, then one line per issue and note."""
    head = f"{r.deck.name}  (engine v{r.version or '?'}" + (f", {len(r.slides)} slides)" if r.slides else ")")
    return [head] + [f"✗ {where}: {message}" for where, message in r.issues] + [f"· {note}" for note in r.notes]


def print_report(r: Report) -> None:
    head, *lines = report_lines(r)
    print(head)
    for line in lines:
        print(f"  {line}")
    print("  ✓ no problems" if r.ok else f"  {len(r.issues)} problem{'s' if len(r.issues) != 1 else ''} to fix")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="deck file or presentation folder")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    decks = df.find_decks(args.target) if args.target.exists() else []
    if not decks:
        print(f"error: no *_presentation.html found at {args.target}", file=sys.stderr)
        return 2
    reports = [check_deck(d) for d in decks]
    if args.json:
        print(json.dumps([{"deck": str(r.deck), "version": r.version, "ok": r.ok, "notes": r.notes,
                           "issues": [{"where": w, "message": m} for w, m in r.issues]} for r in reports], indent=2))
    else:
        for r in reports:
            print_report(r)
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
