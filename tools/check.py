"""Check a presentation: every problem the ?dev view shows, image sizes and engine versions.

    python tools/check.py <deck.html | folder> [--json]

Runs each deck headless in Chrome/Edge (offline, file://) and prints its problems per slide and
step (missing images/animations, bad step attributes, formula errors, files outside the folder,
…), plus <img> tags whose width/height are missing or wrong, plus outdated engine versions.
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

PROBE = """
  // Wait until every image has loaded or failed and every animation instance has answered the
  // handshake or been declared missing (at most 30 s), then a short grace for background images.
  const settled = () => [...document.images].every(img => img.complete)
    && Deck.animations.every(a => a.instances.every(i => i.ready || i.missing));
  const t0 = performance.now();
  while (!settled() && performance.now() - t0 < 30000) await new Promise(r => setTimeout(r, 200));
  await new Promise(r => setTimeout(r, 500));
  return { problems: Deck.problems, version: Deck.version, errors: window.__deckErrors || [],
           slides: Deck.slides.map(s => ({ label: s.label, title: s.title, type: s.type })) };
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


def check_deck(deck: Path, runtime: bool = True) -> Report:
    text = deck.read_text(encoding="utf-8")
    report = Report(deck, df.block_version(text, _blocks.DECK_ENGINE))
    repo = df.repo_version()
    if report.version is None:
        report.issues.append(("Deck", "no DECK-ENGINE block found: not a CustomPresentations deck?"))
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
        result = _browser.probe_file(deck, PROBE)
        report.slides = result["slides"]
        for p in sorted(result["problems"], key=lambda p: (-1 if p["slide"] is None else p["slide"], p["step"])):
            where = slide_name(report.slides, p["slide"]) + ("" if p["slide"] is None else f", step {p['step']}")
            report.issues.append((where, p["message"]))
        for message in result.get("errors", []):
            report.issues.append(("JavaScript", f"uncaught error: {message}"))
    elif runtime:
        report.notes.append("no working Chrome/Edge found: runtime checks (slides, images, animations) skipped")
    return report


def print_report(r: Report) -> None:
    head = f"{r.deck.name}  (engine v{r.version or '?'}" + (f", {len(r.slides)} slides)" if r.slides else ")")
    print(head)
    for where, message in r.issues:
        print(f"  ✗ {where}: {message}")
    for note in r.notes:
        print(f"  · {note}")
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
