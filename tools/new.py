"""Create a new presentation project in presentations/<name> (asks for the details).

    python tools/new.py [name]

Asks for: project name (if not given), file prefix, title, subtitle, presenter, course
title/type, semester, and the names of animations (one per prompt, empty answer = done). Empty
answers keep the template's placeholder. Projects live in CustomPresentations/presentations/
(--parent DIR creates it elsewhere). The project folder is self-contained and gets:

    <prefix>_presentation.html     the deck (engine inlined, works offline)
    <name>_animations.html         one per animation name, registered in DECK.animations
    images/eth_zurich_aerial.png   cover background
    CLAUDE.md, AUTHORING.md        helpers for AI agents (not part of a submission, see pack.py)

Answers can also be piped in (one per line), e.g. by an AI agent.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deckfolder as df  # noqa: E402
import build  # noqa: E402

# Lines of engine/shell/presentation.html that new.py fills in.
TITLE_TAG = "<title>Presentation Title — Simon Meier</title>"
CONFIG_LINES = {
    "title": "      title:     'Presentation Title',",
    "subtitle": "      subtitle:  'Authors (Year)',",
    "presenter": "      presenter: 'Simon Meier',",
    "course": "      course:    { title: 'Course number and name', type: 'Seminar', semester: 'FS26' },",
}
ANIMATIONS_BLOCK = """      animations: [
        // One entry per animation file next to this deck; the order is the picker order.
        // { id: 'main', name: 'My animation', file: 'template_animations.html' },
      ],"""


def ask(question: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{shown}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip()).strip("_")


def js(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def fill_deck(template: str, v: dict, animations: list[dict]) -> str:
    def rep(old: str, new: str) -> None:
        nonlocal template
        if template.count(old) != 1:
            raise SystemExit(f"internal error: template line not found: {old.strip()}")
        template = template.replace(old, new)

    rep(TITLE_TAG, f"<title>{html.escape(v['title'] or 'Presentation Title')} — {html.escape(v['presenter'])}</title>")
    if v["title"]:
        rep(CONFIG_LINES["title"], f"      title:     {js(v['title'])},")
    if v["subtitle"]:
        rep(CONFIG_LINES["subtitle"], f"      subtitle:  {js(v['subtitle'])},")
    rep(CONFIG_LINES["presenter"], f"      presenter: {js(v['presenter'])},")
    course = {"title": v["course_title"] or "Course number and name", "type": v["course_type"], "semester": v["semester"] or "FS26"}
    rep(CONFIG_LINES["course"], f"      course:    {{ title: {js(course['title'])}, type: {js(course['type'])}, semester: {js(course['semester'])} }},")
    if animations:
        entries = "".join(f"        {{ id: {js(a['id'])}, name: {js(a['name'])}, file: {js(a['file'])} }},\n" for a in animations)
        rep(ANIMATIONS_BLOCK, "      animations: [\n        // One entry per animation file next to this deck; the order is the picker order.\n"
                              + entries + "      ],")
    return template


def fill_animation(template: str, name: str, presenter: str) -> str:
    template = template.replace("<title>Animation template — Simon Meier</title>",
                                f"<title>{html.escape(name)} — {html.escape(presenter)}</title>", 1)
    return template.replace("<h1>Animation template</h1>", f"<h1>{html.escape(name)}</h1>", 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="project name = folder name in presentations/ (asked if omitted)")
    ap.add_argument("--parent", type=Path, default=df.PRESENTATIONS, help=f"where projects live (default: {df.PRESENTATIONS})")
    args = ap.parse_args(argv)

    name = (args.name or ask("Project name (letters, digits, _ and -)")).strip()
    if not df.PREFIX_RE.match(name):
        print(f"error: invalid project name {name!r} (use letters, digits, _ and -)", file=sys.stderr)
        return 2
    folder = args.parent.expanduser() / name
    if folder.exists() and any(folder.iterdir()):
        print(f"error: {folder} already exists and is not empty", file=sys.stderr)
        return 2

    prefix = ask("File prefix (letters, digits, _ and -)", name)
    if not df.PREFIX_RE.match(prefix):
        print(f"error: invalid prefix {prefix!r}", file=sys.stderr)
        return 2
    values = {
        "title": ask("Title"),
        "subtitle": ask("Subtitle (authors, year)"),
        "presenter": ask("Presenter", "Simon Meier"),
        "course_title": ask("Course title (e.g. 252-4811-00L Machine Learning)"),
        "course_type": ask("Course type", "Seminar"),
        "semester": ask("Semester (e.g. FS26)"),
    }
    animations = []
    while True:
        name = ask(f"Animation {len(animations) + 1} name (empty = {'no animations' if not animations else 'done'})")
        if not name:
            break
        file_slug = slug(name) or f"animation{len(animations) + 1}"
        if any(a["id"] == file_slug for a in animations):
            print(f"  skipped: an animation called {name!r} already exists")
            continue
        animations.append({"id": file_slug, "name": name, "file": f"{file_slug}_animations.html"})

    outputs = build.build_outputs()
    template = outputs["template_presentation.html"].decode("utf-8")
    anim_template = outputs["template_animations.html"].decode("utf-8")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "images").mkdir(exist_ok=True)
    deck = folder / f"{prefix}_presentation.html"
    deck.write_text(fill_deck(template, values, animations), encoding="utf-8", newline="\n")
    cover = folder / "images" / "eth_zurich_aerial.png"
    if not cover.exists():
        shutil.copy(build.ENGINE / "assets" / "eth_zurich_aerial.png", cover)
    for a in animations:
        (folder / a["file"]).write_text(fill_animation(anim_template, a["name"], values["presenter"]), encoding="utf-8", newline="\n")
    df.write_helper_files(folder, build.engine_version())

    print(f"\nCreated {folder.resolve()}")
    for f in [deck.name, *(a["file"] for a in animations), "images/eth_zurich_aerial.png", "CLAUDE.md", "AUTHORING.md"]:
        print(f"  {f}")
    print(f"\nNext: open {deck.name} in Chrome/Edge (add ?dev while editing), "
          f"then {df.tool('check.py')} \"{folder.resolve()}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
