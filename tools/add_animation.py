"""Add an animation to an existing presentation project.

    python tools/add_animation.py presentations/MyTalk "Model Scaling"

Creates <Name>_animations.html (a copy of the current starter animation, with the panel system) in
the project folder and registers it in DECK.animations of the deck, after the existing entries.
Only that list in the deck's config changes (a backup <deck>.bak is written). The name is asked
if omitted. If the folder holds several decks, pass the deck file instead of the folder.

To show the animation as a slide, add
    <section data-type="animation" data-anim="<id>" data-title="…"></section>
"""
from __future__ import annotations

import argparse
import ast
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _blocks  # noqa: E402
import _deckfolder as df  # noqa: E402
import build  # noqa: E402
from new import ask, fill_animation, js, slug  # noqa: E402

CONFIG_RE = re.compile(r'<script id="deck-config">')
DECK_RE = re.compile(r"\bconst\s+DECK\s*=\s*\{")
KEY_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*:")


class ConfigError(Exception):
    pass


def code_chars(text: str, start: int, end: int):
    """(index, char, quoted) for every character of text[start:end] outside JS comments; quoted is
    True inside string literals (quotes included)."""
    i = start
    while i < end:
        c = text[i]
        if c in "'\"`":
            j = i + 1
            while j < end and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            yield from ((k, text[k], True) for k in range(i, min(j + 1, end)))
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = end if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = end if j < 0 else j + 2
        else:
            yield i, c, False
            i += 1


def scan(text: str, open_at: int, end: int) -> tuple[int, int, dict[str, int]]:
    """For the bracket at open_at: index of its closing bracket, of the last code character before
    that, and where each top-level `key:` of an object literal ends."""
    depth, last, keys = 0, open_at, {}
    for i, c, quoted in code_chars(text, open_at, end):
        if quoted:
            pass
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i, last, keys
        elif depth == 1 and (k := KEY_RE.match(text, i)) and not re.match(r"[\w$]", text[i - 1]):
            keys.setdefault(k.group(1), k.end())
        if not c.isspace():
            last = i
    raise ConfigError("the DECK config has unbalanced brackets")


def indent_at(text: str, i: int) -> str:
    line = text[text.rfind("\n", 0, i) + 1:]
    return line[:len(line) - len(line.lstrip(" \t"))]


def insert_before_close(text: str, close: int, last: int, lines: list[str], indent: str, nl: str) -> str:
    """Insert lines (at indent) as the last items before the bracket at close; add a missing comma."""
    line_start = text.rfind("\n", 0, close) + 1
    block = "".join(f"{indent}{line}{nl}" for line in lines)
    if text[line_start:close].strip():   # the bracket shares its line with other code: `[…]`, `{ a: 1 }`
        text = text[:close] + nl + block + indent_at(text, close) + text[close:]
    else:
        text = text[:line_start] + block + text[line_start:]
    if text[last] not in "[{,":
        text = text[:last + 1] + "," + text[last + 1:]
    return text


def register(deck: str, entry: dict[str, str]) -> str:
    """The deck text with entry appended to DECK.animations (created if the key is missing)."""
    m = CONFIG_RE.search(deck)
    if not m:
        raise ConfigError('no <script id="deck-config"> found')
    script_end = deck.find("</script>", m.end())
    d = DECK_RE.search(deck, m.end(), script_end)
    if not d:
        raise ConfigError("no `const DECK = {` found in the config script")
    nl = "\r\n" if "\r\n" in deck else "\n"
    obj_close, obj_last, keys = scan(deck, d.end() - 1, script_end)
    literal = f"{{ id: {js(entry['id'])}, name: {js(entry['name'])}, file: {js(entry['file'])} }},"
    if "animations" not in keys:
        if re.search(r"""['"]animations['"]\s*:""", deck[d.end():obj_close]):
            raise ConfigError("DECK uses a quoted 'animations' key; add the entry by hand")
        indent = indent_at(deck, d.start()) + "  "
        return insert_before_close(deck, obj_close, obj_last, ["animations: [", "  " + literal, "],"], indent, nl)
    arr = keys["animations"] + len(deck[keys["animations"]:]) - len(deck[keys["animations"]:].lstrip())
    if deck[arr] != "[":
        raise ConfigError("DECK.animations is not a plain list `[ … ]`; add the entry by hand")
    arr_close, arr_last, _ = scan(deck, arr, obj_close)
    existing = "".join(c for _, c, _ in code_chars(deck, arr, arr_close))
    quoted = lambda value: r"""['"]""" + re.escape(value) + r"""['"]"""
    if re.search(r"\bid\s*:\s*" + quoted(entry["id"]), existing) or re.search(quoted(entry["file"]), existing):
        raise ConfigError(f"DECK.animations already has an entry for {entry['id']!r}")
    return insert_before_close(deck, arr_close, arr_last, [literal], indent_at(deck, arr) + "  ", nl)


def presenter_of(deck: str) -> str:
    m = CONFIG_RE.search(deck)
    config = deck[m.end():deck.find("</script>", m.end())] if m else ""
    m = re.search(r"""\bpresenter\s*:\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""", config)
    try:
        return ast.literal_eval(m.group(1)) if m else ""
    except (ValueError, SyntaxError):
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path, help="presentation folder (or its *_presentation.html)")
    ap.add_argument("name", nargs="?", help="animation name shown in the picker (asked if omitted)")
    args = ap.parse_args(argv)

    decks = df.find_decks(args.path)
    if len(decks) != 1 or not decks[0].is_file():
        found = ", ".join(p.name for p in decks) or "none"
        print(f"error: expected exactly one *_presentation.html in {args.path} (found: {found}); pass the deck file", file=sys.stderr)
        return 2
    deck_path = decks[0]
    name = (args.name or ask("Animation name")).strip()
    ident = slug(name)
    if not ident:
        print(f"error: invalid animation name {name!r} (needs letters or digits)", file=sys.stderr)
        return 2
    entry = {"id": ident, "name": name, "file": f"{ident}_animations.html"}
    anim_path = deck_path.parent / entry["file"]
    if anim_path.exists():
        print(f"error: {anim_path} already exists", file=sys.stderr)
        return 2

    deck = deck_path.read_bytes().decode("utf-8")
    deck_version, repo = df.block_version(deck, _blocks.DECK_ENGINE), df.repo_version()
    if deck_version and df.version_tuple(deck_version) > df.version_tuple(repo):
        print(f"error: the deck's engine v{deck_version} is newer than this repository's v{repo}; update the repository first", file=sys.stderr)
        return 1
    try:
        new_deck = register(deck, entry)
    except ConfigError as e:
        print(f"error: {deck_path.name}: {e}", file=sys.stderr)
        return 1

    template = build.build_outputs()["template_animations.html"].decode("utf-8")
    anim_path.write_text(fill_animation(template, name, presenter_of(deck)), encoding="utf-8", newline="\n")
    deck_path.with_name(deck_path.name + ".bak").write_bytes(deck.encode("utf-8"))
    deck_path.write_bytes(new_deck.encode("utf-8"))

    print(f"Created  {anim_path.resolve()}")
    print(f"Updated  {deck_path.name}: DECK.animations += {{ id: '{ident}', name: {js(name)} }}  (backup: {deck_path.name}.bak)")
    if deck_version and deck_version != repo:
        print(f"Note: the deck uses engine v{deck_version}, the new animation v{repo}; run {df.tool('update.py')} \"{deck_path.parent.resolve()}\"")
    print(f"\nShow it as a slide:  <section data-type=\"animation\" data-anim=\"{ident}\" data-title=\"{html.escape(name)}\"></section>")
    print(f"Then check:          {df.tool('check.py')} \"{deck_path.parent.resolve()}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
