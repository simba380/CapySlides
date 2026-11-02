"""Run a built deck in a headless Chromium browser and collect results from a probe script.

The probe is the body of an async JS function. It runs after the engine has booted and its
return value comes back as Python data. Pages are opened via file:// with all network
lookups disabled, so every run also proves the deck works offline.

Built fixtures stay in .tmp/fixtures/ for manual inspection.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _browser import ROOT, TMP, ProbeError, dump_probe, find_browser, with_probe  # noqa: E402,F401

FIXTURES_OUT = TMP / "fixtures"
TEMPLATE_IMAGES = ROOT / "template" / "images"


def run(page: str, probe_js: str, name: str, size=(1280, 800), query: str = "", budget_ms: int = 3000,
        images: bool | dict[str, bytes] = True, subdir: str | None = None, files: dict[str, str] | None = None):
    """Write `page` (+ probe) to .tmp/fixtures/<name>.html, load it headless, return the probe result.

    With images=True the template's images/ folder sits next to the page (like a real deck);
    images=False writes the page to .tmp/fixtures/noimages/ where no images folder exists; a dict
    {name: bytes} makes images/ contain exactly those files (use with `subdir`).
    `subdir` puts the page into its own folder (e.g. to add/remove image files between runs).
    `files` maps extra file names to contents written next to the page (e.g. animation files).
    The browser profile (and thus localStorage) persists across runs."""
    out = FIXTURES_OUT / (subdir or ("" if images else "noimages"))
    out.mkdir(parents=True, exist_ok=True)
    if images is True:
        shutil.copytree(TEMPLATE_IMAGES, out / "images", dirs_exist_ok=True)
    elif (out / "images").exists():
        shutil.rmtree(out / "images")
    if isinstance(images, dict):
        (out / "images").mkdir(parents=True)
        for file_name, data in images.items():
            (out / "images" / file_name).write_bytes(data)
    for file_name, content in (files or {}).items():
        (out / file_name).write_text(content, encoding="utf-8", newline="\n")
    (out / f"{name}.html").write_text(page, encoding="utf-8", newline="\n")
    probed = out / f"{name}.probe.html"
    probed.write_text(with_probe(page, probe_js), encoding="utf-8", newline="\n")
    return dump_probe(probed.as_uri() + query, name, size=size, budget_ms=budget_ms)
