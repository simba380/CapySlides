"""Create the zip to submit: only the presentation files, verified to work on their own.

    python tools/pack.py <folder | deck.html> [--out DIR] [--force] [--no-check]

Includes everything in the presentation folder except the authoring helpers (CLAUDE.md,
AUTHORING.md), backups (*.bak), zips, hidden files and Python caches. The files are first copied
to a temporary folder outside this repository and checked there with tools/check.py, so the zip is
proven to be self-contained and to work offline. Writes <prefix>.zip (with a top-level <prefix>/
folder) next to the presentation folder, or into --out.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deckfolder as df  # noqa: E402
import check  # noqa: E402


def submitted_files(folder: Path) -> list[Path]:
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
    prefix = decks[0].name[: -len("_presentation.html")] or decks[0].stem
    files = submitted_files(folder)

    with tempfile.TemporaryDirectory(prefix="deck-pack-") as tmp:
        staged = Path(tmp) / prefix
        for rel in files:
            (staged / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / rel, staged / rel)
        if not args.no_check:
            print(f"Checking a copy outside the repository ({len(files)} files) …")
            report = check.check_deck(staged / decks[0].name)
            check.print_report(report)
            if not report.ok and not args.force:
                print("Not packed: fix the problems above (or use --force).", file=sys.stderr)
                return 1
        out_dir = (args.out or folder.parent).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"{prefix}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for rel in files:
                z.write(staged / rel, f"{prefix}/{rel.as_posix()}")

    print(f"\nWrote {zip_path} ({zip_path.stat().st_size / 1024:.0f} KB):")
    for rel in files:
        print(f"  {prefix}/{rel.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
