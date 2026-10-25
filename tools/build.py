"""Assemble the stand-alone templates from engine/ sources and vendored assets.

    python tools/build.py           write template/template_presentation.html,
                                    template/template_animations.html, template/images/...,
                                    and AUTHORING.md from engine/AUTHORING.src.md
    python tools/build.py --check   exit 1 if template/ differs from a fresh build

Everything a deck needs at runtime (fonts, KaTeX, engine CSS/JS) is inlined between
marker blocks (tools/_blocks.py), so the result opens offline via file://.
"""
from __future__ import annotations

import argparse
import base64
import functools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _blocks  # noqa: E402
import fetch_vendor  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
VENDOR = ENGINE / "vendor"
TEMPLATE = ROOT / "template"

DECK_FONTS = ("Inter", "Fira Code")
ANIM_FONTS = ("DM Sans", "DM Serif Display", "DM Mono")

PLACEHOLDER = "<!-- @@{}@@ -->"

# Cascade layer order for decks, declared before any layered rule (the first mention of a layer
# fixes its position). User CSS stays unlayered and therefore always wins. Must match engine/deck.css.
DECK_LAYER_ORDER = "@layer reset, vendor, engine, components;"


class BuildError(Exception):
    pass


# ── helpers ──────────────────────────────────────────────────────────────────

def text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def data_uri(path: Path) -> str:
    return "data:font/woff2;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def packages() -> dict[str, dict]:
    """Manifest packages keyed by font family ('KaTeX' for katex)."""
    manifest = fetch_vendor.load_manifest()
    return {p.get("family", "KaTeX"): p for p in manifest["packages"]}


def copyright_line(pkg: dict) -> str:
    lic = text(VENDOR / pkg["target"] / "LICENSE")
    line = next((l.strip() for l in lic.splitlines() if "Copyright" in l), "")
    return line.replace("*/", "* /")


def safe_script(js: str) -> str:
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)


def safe_style(css: str) -> str:
    if re.search(r"</style", css, re.I):
        raise BuildError("CSS must not contain '</style'")
    return css


def engine_source(name: str, version: str) -> str:
    source = text(ENGINE / name).replace("__ENGINE_VERSION__", version).strip("\n")
    if "__COMPONENT_CATALOG__" in source:
        source = source.replace("__COMPONENT_CATALOG__", json.dumps(component_catalog(), ensure_ascii=False))
    return source


TEMPLATE_RE = re.compile(r'<template (?P<attrs>[^>]*)>\n?(?P<html>.*?)</template>', re.S)
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def component_catalog() -> list[dict]:
    """engine/components.html → [{name, from, html, height?}] (the ?dev Components panel, SPEC §14)."""
    entries = []
    for m in TEMPLATE_RE.finditer(text(ENGINE / "components.html")):
        attrs = dict(ATTR_RE.findall(m["attrs"]))
        if "data-name" not in attrs or "data-from" not in attrs:
            raise BuildError(f"engine/components.html: <template {m['attrs']}> needs data-name and data-from")
        entry = {"name": attrs["data-name"], "from": attrs["data-from"], "html": m["html"].strip("\n")}
        if "data-height" in attrs:   # canvas px height for components that fill the slide height
            entry["height"] = int(attrs["data-height"])
        entries.append(entry)
    if not entries:
        raise BuildError("engine/components.html: no <template data-name=… data-from=…> entries found")
    return entries


# ── vendor CSS / JS ──────────────────────────────────────────────────────────

FACE_RE = re.compile(r"(?:/\*\s*(?P<label>[^*]*?)\s*\*/\s*)?@font-face\s*\{(?P<body>[^}]*)\}", re.S)
FONTSOURCE_URL_RE = re.compile(r"url\(\./files/(?P<file>[^)]+?\.woff2)\)")


def fontsource_css(pkg: dict) -> str:
    """Inline the vendored subsets of a fontsource package; drop all other subsets."""
    target = VENDOR / pkg["target"]
    wanted = {Path(f).name for f in pkg["files"] if f.endswith(".woff2")}
    used = set()
    faces = []
    for css_file in (f for f in pkg["files"] if f.endswith(".css")):
        for m in FACE_RE.finditer(text(target / css_file)):
            url = FONTSOURCE_URL_RE.search(m["body"])
            if not url or url["file"] not in wanted:
                continue
            used.add(url["file"])
            props = {}
            for decl in m["body"].split(";"):
                if ":" in decl:
                    key, val = decl.split(":", 1)
                    props[key.strip()] = val.strip()
            faces.append(
                f"/* {m['label'] or url['file']} */\n"
                f"@font-face{{font-family:'{pkg['family']}';font-style:{props['font-style']};"
                f"font-display:swap;font-weight:{props['font-weight']};"
                f"unicode-range:{props['unicode-range']};"
                f"src:url({data_uri(target / 'files' / url['file'])}) format('woff2')}}"
            )
    missing = wanted - used
    if missing:
        raise BuildError(f"{pkg['package']}: vendored files not referenced by its CSS: {sorted(missing)}")
    header = f"/* {pkg['family']} — {pkg['package']}@{pkg['version']}, {pkg['license']}. {copyright_line(pkg)} */"
    return header + "\n" + "\n".join(faces)


KATEX_SRC_RE = re.compile(
    r'url\(fonts/(?P<name>[^)]+?)\.woff2\) format\("woff2"\)(?:,url\(fonts/[^)]+\) format\("[^"]+"\))*'
)


def katex_css(pkg: dict) -> str:
    dist = VENDOR / pkg["target"] / "dist"
    css = KATEX_SRC_RE.sub(
        lambda m: f'url({data_uri(dist / "fonts" / (m["name"] + ".woff2"))}) format("woff2")',
        text(dist / "katex.min.css"),
    )
    if "url(fonts/" in css:
        raise BuildError("katex.min.css: unrewritten font url left")
    header = f"/* KaTeX — katex@{pkg['version']}, MIT. {copyright_line(pkg)} */"
    return header + "\n" + css.strip("\n")


def katex_js(pkg: dict) -> str:
    dist = VENDOR / pkg["target"] / "dist"
    licence = text(VENDOR / pkg["target"] / "LICENSE").strip().replace("*/", "* /")
    return safe_script(
        f"/*! KaTeX katex@{pkg['version']} + contrib/auto-render\n{licence}\n*/\n"
        + text(dist / "katex.min.js").strip("\n") + "\n"
        + text(dist / "contrib" / "auto-render.min.js").strip("\n")
    )


# ── blocks ───────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=4)
def deck_engine_block(version: str) -> str:
    pkgs = packages()
    body = "\n".join([
        '<style id="deck-vendor-css">',
        DECK_LAYER_ORDER,
        "@layer vendor {",
        safe_style("\n".join(fontsource_css(pkgs[f]) for f in DECK_FONTS)),
        safe_style(katex_css(pkgs["KaTeX"])),
        "}",
        "</style>",
        '<style id="deck-engine-css">',
        safe_style(engine_source("deck.css", version)),
        safe_style(engine_source("components.css", version)),
        "</style>",
        '<script id="deck-vendor-js">',
        katex_js(pkgs["KaTeX"]),
        "</script>",
        '<script id="deck-engine-js">',
        safe_script(engine_source("deck.js", version)),
        "</script>",
    ])
    return _blocks.wrap(_blocks.DECK_ENGINE, version, body)


def anim_vendor_block(version: str) -> str:
    # Unlayered on purpose: animation pages bring their own unlayered CSS (often a `* {margin:0}`
    # reset), which would override every layered KaTeX rule regardless of specificity.
    pkgs = packages()
    body = "\n".join([
        '<style id="anim-vendor-css">',
        safe_style("\n".join(fontsource_css(pkgs[f]) for f in ANIM_FONTS)),
        safe_style(katex_css(pkgs["KaTeX"])),
        "</style>",
        '<script id="anim-vendor-js">',
        katex_js(pkgs["KaTeX"]),
        "</script>",
    ])
    return _blocks.wrap(_blocks.ANIM_VENDOR, version, body)


def anim_contract_block(version: str) -> str:
    body = "\n".join([
        '<script id="anim-contract-js">',
        safe_script(engine_source("anim-contract.js", version)),
        "</script>",
    ])
    return _blocks.wrap(_blocks.ANIM_CONTRACT, version, body)


def fill(shell: str, blocks: dict[str, str]) -> str:
    for key, block in blocks.items():
        ph = PLACEHOLDER.format(key)
        if shell.count(ph) != 1:
            raise BuildError(f"shell must contain {ph} exactly once")
        shell = shell.replace(ph, block)
    return shell


# ── build ────────────────────────────────────────────────────────────────────

def engine_version() -> str:
    return text(ENGINE / "VERSION").strip()


def build_deck(shell: str, version: str) -> str:
    """Fill a deck shell (user zone + <!-- @@DECK_ENGINE@@ --> placeholder) with the engine block."""
    return fill(shell.replace("\r\n", "\n"), {"DECK_ENGINE": deck_engine_block(version)})


def build_outputs() -> dict[str, bytes]:
    """Return {path relative to template/: content} for a fresh build."""
    problems = fetch_vendor.verify()
    if problems:
        raise BuildError("vendor files do not match lock.json:\n  " + "\n  ".join(problems))
    version = engine_version()
    deck = build_deck(text(ENGINE / "shell" / "presentation.html"), version)
    anim = fill(text(ENGINE / "shell" / "animations.html"), {
        "ANIM_VENDOR": anim_vendor_block(version),
        "ANIM_CONTRACT": anim_contract_block(version),
    })
    return {
        "template_presentation.html": deck.encode("utf-8"),
        "template_animations.html": anim.encode("utf-8"),
        "images/eth_zurich_aerial.png": (ENGINE / "assets" / "eth_zurich_aerial.png").read_bytes(),
    }


def authoring_text(version: str) -> str:
    """AUTHORING.md: engine/AUTHORING.src.md with the engine version and every catalog snippet."""
    parts = [f"### {c['name']}\n*From: {c['from']}*\n\n```html\n{c['html']}\n```\n" for c in component_catalog()]
    return (text(ENGINE / "AUTHORING.src.md").replace("@@ENGINE_VERSION@@", version)
            .replace("@@COMPONENTS@@", "\n".join(parts).strip()))


def write(outputs: dict[str, bytes], out_dir: Path) -> None:
    for rel, data in outputs.items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{len(data) / 1024:>8.0f} KB  {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


def stale(outputs: dict[str, bytes], out_dir: Path) -> list[str]:
    return [rel for rel, data in outputs.items()
            if not (out_dir / rel).exists() or (out_dir / rel).read_bytes() != data]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify template/ is up to date; write nothing")
    args = ap.parse_args()
    try:
        outputs = build_outputs()
        guide = {"AUTHORING.md": authoring_text(engine_version()).encode("utf-8")}
    except BuildError as e:
        print(f"build failed: {e}", file=sys.stderr)
        return 1
    if args.check:
        files = [f"template/{rel}" for rel in stale(outputs, TEMPLATE)]
        files += stale(guide, ROOT)
        for rel in files:
            print(f"stale: {rel}", file=sys.stderr)
        print("template up to date" if not files else "run: python tools/build.py")
        return 1 if files else 0
    write(outputs, TEMPLATE)
    write(guide, ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
