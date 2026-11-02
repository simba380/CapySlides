"""Headless Chromium helper shared by tools/check.py, tools/showcase.py and the test suite.

A probe is the body of an async JS function; it runs after the deck engine has booted and its
return value comes back as Python data. Pages are opened via file:// with all network lookups
disabled, so every run also proves the deck works offline.
"""
from __future__ import annotations

import functools
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"

CANDIDATES = (
    os.environ.get("DECK_TEST_BROWSER", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
)

PROBE_WRAPPER = """<script id="deck-probe">
window.__deckErrors = [];   // uncaught errors anywhere in the page (also during the engine's boot)
addEventListener('error', e => window.__deckErrors.push(String(e.message || e)));
addEventListener('unhandledrejection', e => window.__deckErrors.push('unhandled rejection: ' + String(e.reason)));
(async () => {
  if (document.readyState === 'loading') await new Promise(r => addEventListener('DOMContentLoaded', r));
  await new Promise(r => setTimeout(r, 0));
  const out = document.createElement('pre');
  out.id = 'probe';
  try {
    const result = await (async () => { %s })();
    out.textContent = JSON.stringify({ ok: true, result });
  } catch (e) {
    out.textContent = JSON.stringify({ ok: false, error: String(e && e.stack || e) });
  }
  document.body.appendChild(out);
})();
</script>"""


class ProbeError(AssertionError):
    pass


def _works(exe: str) -> bool:
    """A browser counts only if headless --dump-dom really produces output (an install in the
    middle of an update can exit silently)."""
    probe_dir = TMP / f"browser-check-{Path(exe).stem}"   # profiles are not shareable across browsers
    try:
        proc = subprocess.run(
            [exe, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={probe_dir}",
             "--dump-dom", "data:text/html,<p>deck-ok</p>"],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        return "deck-ok" in proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


@functools.lru_cache(maxsize=1)
def find_browser() -> str | None:
    for c in CANDIDATES:
        if not c:
            continue
        exe = c if Path(c).is_file() else shutil.which(c)
        if exe and _works(exe):
            return exe
    return None


def with_probe(page: str, probe_js: str) -> str:
    return page.replace("</body>", PROBE_WRAPPER % probe_js + "\n</body>")


def _headless(size, budget_ms: int) -> list[str]:
    """The browser command line shared by probes and screenshots: headless, offline, fixed window."""
    browser = find_browser()
    if not browser:
        raise RuntimeError("no working Chromium-based browser found (Edge/Chrome; or set DECK_TEST_BROWSER)")
    return [
        browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={TMP / ('browser-profile-' + Path(browser).stem)}",
        "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--window-size={size[0]},{size[1]}",
        f"--virtual-time-budget={budget_ms}",
    ]


def dump_probe(url: str, label: str, size=(1280, 800), budget_ms: int = 3000):
    """Open `url` (a page that contains a probe) headless and return the probe result."""
    cmd = _headless(size, budget_ms) + ["--dump-dom", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    m = re.search(r'<pre id="probe">(.*?)</pre>', proc.stdout, re.S)
    if not m:
        raise ProbeError(f"no probe output for {label}; stderr tail:\n{proc.stderr[-2000:]}")
    data = json.loads(html.unescape(m.group(1)))
    if not data["ok"]:
        raise ProbeError(f"probe failed in {label}:\n{data['error']}")
    return data["result"]


def screenshot(url: str, path: Path, size=(1280, 800), budget_ms: int = 8000) -> None:
    """Save what `url` shows headless (offline) as an image; the suffix picks the format (.png, .jpg)."""
    path.unlink(missing_ok=True)
    cmd = _headless(size, budget_ms) + ["--hide-scrollbars", f"--screenshot={path.resolve()}", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if not path.is_file() or not path.stat().st_size:
        raise ProbeError(f"no screenshot of {url}; stderr tail:\n{proc.stderr[-2000:]}")


def probe_file(deck: Path, probe_js: str, query: str = "", budget_ms: int = 40000):
    """Run a probe on an existing deck file in place: a temporary copy is written next to it (so
    images/ and animation files resolve as usual) and removed afterwards."""
    temp = deck.with_name(f".deck-check-{deck.stem}.html")
    temp.write_text(with_probe(deck.read_text(encoding="utf-8"), probe_js), encoding="utf-8", newline="\n")
    try:
        return dump_probe(temp.resolve().as_uri() + query, deck.name, budget_ms=budget_ms)
    finally:
        temp.unlink(missing_ok=True)
