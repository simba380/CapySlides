"""Helpers shared by new.py, update.py, check.py and pack.py: finding decks, engine versions, and the
AI helper files (CLAUDE.md pointer + AUTHORING.md copy) in a presentation folder (SPEC §16, R12)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _blocks  # noqa: E402
import build  # noqa: E402

ROOT = build.ROOT
PRESENTATIONS = ROOT / "presentations"   # all presentation projects (each one self-contained)
PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
POINTER_BEGIN = "<!-- CUSTOMPRESENTATIONS:BEGIN"
POINTER_END = "<!-- CUSTOMPRESENTATIONS:END -->"
# Files that help authoring but are never part of a submitted presentation.
NOT_SUBMITTED = ("CLAUDE.md", "AUTHORING.md")


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version)[:3])


def repo_version() -> str:
    return build.engine_version()


def block_version(text: str, name: str) -> str | None:
    found = _blocks.find(text, name)
    return found[0]["version"] if len(found) == 1 else None


def find_decks(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.glob("*_presentation.html") if not p.name.startswith(".deck-check-"))


def find_animations(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*_animations.html") if not p.name.startswith(".deck-check-"))


def tool(name: str) -> str:
    return f'python "{ROOT / "tools" / name}"'


def pointer_block(version: str, folder: Path) -> str:
    return f"""{POINTER_BEGIN} v{version} (managed by tools/new.py and tools/update.py) -->
# Presentation folder (CustomPresentations engine v{version})

This folder is a self-contained presentation: it needs nothing outside this folder to run.

- **Authoring guide:** central and newest `{ROOT / "AUTHORING.md"}`; the local `AUTHORING.md` is the
  copy matching this deck's engine (use it when the repository is not available).
- **Before editing:** if the central guide's engine version is newer than this deck's
  (`<!-- DECK-ENGINE:BEGIN v…` in the deck), first run `{tool("update.py")} "{folder}"`.
- Edit only the user zone of `*_presentation.html`; never read or edit past `<!-- DECK-ENGINE:BEGIN`.
- After adding images: `{tool("image_sizes.py")} <deck>`. After every change: `{tool("check.py")} "{folder}"`.
- Another animation: `{tool("add_animation.py")} "{folder}" "Name"` (creates the file and registers it).
- Submit with `{tool("pack.py")} "{folder}"` (a zip without CLAUDE.md / AUTHORING.md).
{POINTER_END}
"""


def write_helper_files(folder: Path, version: str) -> list[str]:
    """Create/refresh CLAUDE.md (only the managed block; other text is kept) and the AUTHORING.md copy."""
    folder = folder.resolve()
    block = pointer_block(version, folder)
    claude = folder / "CLAUDE.md"
    if claude.exists():
        old = claude.read_text(encoding="utf-8")
        start, end = old.find(POINTER_BEGIN), old.find(POINTER_END)
        new = (old[:start] + block.rstrip("\n") + old[end + len(POINTER_END):]) if 0 <= start < end else (old.rstrip("\n") + "\n\n" + block)
    else:
        new = block
    claude.write_text(new, encoding="utf-8", newline="\n")
    (folder / "AUTHORING.md").write_text(build.authoring_text(version), encoding="utf-8", newline="\n")
    return ["CLAUDE.md", "AUTHORING.md"]
