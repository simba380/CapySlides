"""Create the zip to submit: the deck and only the files it uses, verified to work on their own.

    python tools/pack.py <folder | deck.html> [--out DIR] [--force] [--no-check]

A file goes into the zip only if the presentation uses it: the deck, every file the deck names
(the animation files in DECK.animations, images, linked files, …) and in turn every file those name
(e.g. an animation's images). Names count only in the authored parts; the generated engine, font
and contract blocks are skipped. With a browser, the deck is also opened headless to add what the
engine uses by default (the cover image when DECK.cover names none). Never included: CLAUDE.md,
AUTHORING.md, backups (*.bak), zips, hidden files and Python caches; files nothing names are listed
as left out. The files are first copied to a temporary folder outside this repository and checked
there with tools/check.py, so the zip is proven to be self-contained and to work offline. Writes
<prefix>.zip (with a top-level <prefix>/ folder) next to the presentation folder, or into --out.
Progress is printed per step: "[STEP n/4] what it does", then, indented below it, what happens and
"PASSED: …" or "FAILED: …" with the result.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _blocks  # noqa: E402
import _browser  # noqa: E402
import _deckfolder as df  # noqa: E402
import check  # noqa: E402

TEXT_SUFFIXES = (".html", ".htm", ".css", ".js", ".svg", ".json")   # files whose own references count
GENERATED = _blocks.DECK_BLOCKS + _blocks.ANIM_BLOCKS
STEPS = 4
INDENT = " " * len(f"[STEP {STEPS}/{STEPS}] ")   # lines inside a step start below its text


def step(n: int, text: str) -> None:
    """The start of a step: "[STEP n/4] …" (flushed, so it shows up while the step runs)."""
    print(f"[STEP {n}/{STEPS}] {text}", flush=True)


def detail(text: str) -> None:
    """A line inside the current step, indented below it."""
    print(f"{INDENT}{text}", flush=True)


def done(text: str, ok: bool = True) -> None:
    """The end of a step, indented below it: "PASSED: …" (or "FAILED: …")."""
    detail(f"{'PASSED' if ok else 'FAILED'}: {text}")


def candidate_files(folder: Path) -> list[Path]:
    """Files that may be submitted (relative paths): no AI helpers, backups, zips, hidden files or caches."""
    files = []
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if not path.is_file() or any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if len(rel.parts) == 1 and rel.name in df.NOT_SUBMITTED:
            continue
        if path.suffix.lower() in (".bak", ".zip"):
            continue
        files.append(rel)
    return files


def authored_text(path: Path) -> str:
    """The file's text without the generated blocks (they name engine defaults and placeholders)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    for name in GENERATED:
        text = _blocks.block_re(name).sub("", text)
    return text


def names(text: str, path: str) -> bool:
    """True if `text` contains `path` as a whole path: images/x.png, ./images/x.png or URL-encoded."""
    for form in {path, urllib.parse.quote(path)}:
        if re.search(rf"(?<![\w./\\%-])(?:\./)?{re.escape(form)}(?![\w-])", text):
            return True
    return False


def local_path(ref: str, folder: Path) -> Path | None:
    """A reference of the deck ("images/x.png", "a_animations.html?view=2") → its path relative to
    the folder, or None if it leaves the folder."""
    ref = urllib.parse.unquote(re.split(r"[?#]", ref.strip(), maxsplit=1)[0])
    if not ref:
        return None
    try:
        return (folder / ref).resolve().relative_to(folder.resolve())
    except ValueError:
        return None


def needed_files(deck: Path, used: list[str] = ()) -> tuple[list[Path], list[Path]]:
    """(needed, left out), relative to the deck's folder: the deck, every file it names, every file
    those name, and so on. `used` = the references the running deck reported (check.deck_assets)."""
    folder = deck.parent
    pending = [rel for rel in candidate_files(folder) if rel != Path(deck.name)]
    needed, todo = [Path(deck.name)], [Path(deck.name)]

    def take(rel: Path) -> None:
        pending.remove(rel)
        needed.append(rel)
        todo.append(rel)

    for ref in used:
        rel = local_path(ref, folder)
        if rel in pending:
            take(rel)
    while todo:
        rel = todo.pop()
        if rel.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text, base = authored_text(folder / rel), (folder / rel).parent
        for other in [p for p in pending if names(text, Path(os.path.relpath(folder / p, base)).as_posix())]:
            take(other)
    by_name = lambda p: p.as_posix()   # the same order on every OS
    return sorted(needed, key=by_name), sorted(pending, key=by_name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="presentation folder (or its deck file)")
    ap.add_argument("--out", type=Path, help="folder for the zip (default: next to the presentation folder)")
    ap.add_argument("--force", action="store_true", help="write the zip even if the check finds problems")
    ap.add_argument("--no-check", action="store_true", help="skip the verification (not recommended)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    folder = (args.target if args.target.is_dir() else args.target.parent).resolve()
    decks = df.find_decks(args.target) if args.target.exists() else []
    if len(decks) != 1:
        print(f"error: expected exactly one *_presentation.html in {folder}, found {len(decks)}"
              + (" (pass the deck file)" if decks else ""), file=sys.stderr)
        return 2
    deck = decks[0]
    prefix = deck.name[: -len("_presentation.html")] or deck.stem

    step(1, f"Finding the files {deck.name} uses")
    used = []
    if _browser.find_browser():
        detail("opening the deck headless to see what it loads (e.g. the default cover image) …")
        try:
            used = check.deck_assets(deck)
        except _browser.ProbeError as e:
            detail(f"note: the deck could not be opened headless, only files named in it are packed ({e})")
    else:
        detail("note: no Chrome/Edge found: only files named in the deck and its animations are packed "
               "(not the engine's default cover image)")
    files, left_out = needed_files(deck, used)
    done(f"{len(files)} file{'s' if len(files) != 1 else ''} used, {len(left_out)} left out")

    with tempfile.TemporaryDirectory(prefix="deck-pack-") as tmp:
        staged = Path(tmp) / prefix
        step(2, "Copying them to a temporary folder outside the repository")
        for rel in files:
            (staged / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / rel, staged / rel)
        done(f"{len(files)} files copied ({sum((staged / rel).stat().st_size for rel in files) / 1024:.0f} KB)")
        if args.no_check:
            step(3, "Checking the copy offline: skipped (--no-check)")
        else:
            step(3, "Checking the copy offline in headless Chrome/Edge (network blocked)")
            report = check.check_deck(staged / deck.name, progress=detail)
            for line in check.report_lines(report):
                detail(line)
            if report.ok:
                done("no problems found")
            else:
                n = len(report.issues)
                done(f"{n} problem{'s' if n != 1 else ''}" + (" (zipping anyway: --force)" if args.force else ""), ok=False)
                if not args.force:
                    print("Not packed: fix the problems above (or use --force).", file=sys.stderr)
                    return 1
        out_dir = (args.out or folder.parent).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"{prefix}.zip"
        step(4, f"Writing {zip_path.name}")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for rel in files:
                z.write(staged / rel, f"{prefix}/{rel.as_posix()}")
        done(f"{zip_path.name} written ({zip_path.stat().st_size / 1024:.0f} KB)")

    print(f"\nWrote {zip_path} ({zip_path.stat().st_size / 1024:.0f} KB):")
    for rel in files:
        print(f"  {prefix}/{rel.as_posix()}")
    if left_out:
        print("\nLeft out (nothing in the presentation uses them):")
        for rel in left_out:
            print(f"  {rel.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
