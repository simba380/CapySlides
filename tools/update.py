"""Bring a presentation to the current engine without touching its content.

    python tools/update.py <deck.html | folder> [--force] [--dry-run]

For each deck (*_presentation.html) the DECK-ENGINE block is replaced; for each animation file
(*_animations.html) in the same folder the ANIM-VENDOR and ANIM-CONTRACT blocks are replaced.
Everything outside these marker blocks stays byte-identical (verified), and a block keeps the line
endings it had (CRLF stays CRLF). A backup <file>.bak is written for every changed file. A folder also gets a fresh CLAUDE.md block and AUTHORING.md copy
(not a showcase copy made by tools/showcase.py: it is published and must not contain local paths).

Refuses to downgrade (file newer than this repository's engine) unless --force is given.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _blocks  # noqa: E402
import _deckfolder as df  # noqa: E402
import build  # noqa: E402


class UpdateError(Exception):
    pass


def outside_blocks(text: str, names) -> str:
    """The text with every named block removed: must not change during an update."""
    for name in names:
        text = _blocks.block_re(name).sub("", text)
    return text


def update_text(text: str, blocks: dict[str, str], version: str, force: bool) -> tuple[str, str | None]:
    old_version = None
    for name in blocks:
        found = _blocks.find(text, name)
        if len(found) != 1:
            raise UpdateError(f"expected exactly one {name} block, found {len(found)} (not a CapySlides file?)")
        old_version = old_version or found[0]["version"]
    if old_version and df.version_tuple(old_version) > df.version_tuple(version) and not force:
        raise UpdateError(f"file has engine v{old_version}, newer than this repository's v{version}; use --force to downgrade")
    new = text
    for name, block in blocks.items():
        crlf = "\r\n" in _blocks.find(new, name)[0].group(0)   # a deck saved on Windows keeps its line endings
        new = _blocks.replace(new, name, block.replace("\n", "\r\n") if crlf else block)
    if outside_blocks(new, blocks) != outside_blocks(text, blocks):
        raise UpdateError("content outside the engine blocks would change; aborted")
    return new, old_version


def update_file(path: Path, blocks: dict[str, str], version: str, force: bool, dry_run: bool) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new, old = update_text(text, blocks, version, force)
    if new == text:
        return f"up to date  {path.name} (v{version})"
    if not dry_run:
        path.with_name(path.name + ".bak").write_bytes(raw)
        path.write_text(new, encoding="utf-8", newline="\n")
    return f"{'would update' if dry_run else 'updated':<11} {path.name}: v{old} → v{version}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="deck file or presentation folder")
    ap.add_argument("--force", action="store_true", help="allow replacing a newer engine (downgrade)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):   # → and names print on any console (e.g. cp1252 when piped)
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    if not args.target.exists():
        print(f"error: {args.target} does not exist", file=sys.stderr)
        return 2
    version = build.engine_version()
    deck_blocks = {_blocks.DECK_ENGINE: build.deck_engine_block(version)}
    anim_blocks = {_blocks.ANIM_VENDOR: build.anim_vendor_block(version), _blocks.ANIM_CONTRACT: build.anim_contract_block(version)}
    folder = args.target if args.target.is_dir() else args.target.parent
    decks = df.find_decks(args.target)
    animations = df.find_animations(folder)
    if not decks and not animations:
        print(f"error: no *_presentation.html or *_animations.html in {args.target}", file=sys.stderr)
        return 2

    failed = False
    for path, blocks in [(d, deck_blocks) for d in decks] + [(a, anim_blocks) for a in animations]:
        try:
            print(update_file(path, blocks, version, args.force, args.dry_run))
        except (UpdateError, UnicodeDecodeError) as e:
            print(f"error       {path.name}: {e}", file=sys.stderr)
            failed = True
    if decks and not args.dry_run and not failed:
        if (folder / df.SHOWCASE_INFO).exists():   # a published copy (showcase.py) stays free of local paths
            print("skipped     CLAUDE.md, AUTHORING.md (showcase copy)")
        else:
            for name in df.write_helper_files(folder, version):
                print(f"refreshed   {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
