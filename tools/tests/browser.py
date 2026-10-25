"""Run a built deck in a headless Chromium browser and collect results from a probe script.

The probe is the body of an async JS function. It runs after the engine has booted and its
return value comes back as Python data. Pages are opened via file:// with all network
lookups disabled, so every run also proves the deck works offline.

Built fixtures stay in .tmp/fixtures/ for manual inspection.
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

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp"
FIXTURES_OUT = TMP / "fixtures"

CANDIDATES = (
    os.environ.get("DECK_TEST_BROWSER", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
)

PROBE_WRAPPER = """<script id="test-probe">
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


class ProbeError(AssertionError):
    pass


TEMPLATE_IMAGES = ROOT / "template" / "images"


def run(page: str, probe_js: str, name: str, size=(1280, 800), query: str = "", budget_ms: int = 3000,
        images: bool = True, subdir: str | None = None, files: dict[str, str] | None = None):
    """Write `page` (+ probe) to .tmp/fixtures/<name>.html, load it headless, return the probe result.

    With images=True the template's images/ folder sits next to the page (like a real deck);
    images=False writes the page to .tmp/fixtures/noimages/ where no images folder exists.
    `subdir` puts the page into its own folder (e.g. to add/remove image files between runs).
    `files` maps extra file names to contents written next to the page (e.g. animation files).
    The browser profile (and thus localStorage) persists across runs."""
    browser = find_browser()
    if not browser:
        raise RuntimeError("no Chromium-based browser found (set DECK_TEST_BROWSER)")
    out = FIXTURES_OUT / (subdir or ("" if images else "noimages"))
    out.mkdir(parents=True, exist_ok=True)
    if images:
        shutil.copytree(TEMPLATE_IMAGES, out / "images", dirs_exist_ok=True)
    elif (out / "images").exists():
        shutil.rmtree(out / "images")
    for file_name, content in (files or {}).items():
        (out / file_name).write_text(content, encoding="utf-8", newline="\n")
    (out / f"{name}.html").write_text(page, encoding="utf-8", newline="\n")
    probed = out / f"{name}.probe.html"
    probed.write_text(page.replace("</body>", PROBE_WRAPPER % probe_js + "\n</body>"), encoding="utf-8", newline="\n")

    cmd = [
        browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={TMP / ('browser-profile-' + Path(browser).stem)}",
        "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--window-size={size[0]},{size[1]}",
        f"--virtual-time-budget={budget_ms}",
        "--dump-dom", probed.as_uri() + query,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
    m = re.search(r'<pre id="probe">(.*?)</pre>', proc.stdout, re.S)
    if not m:
        raise ProbeError(f"no probe output for {name}; stderr tail:\n{proc.stderr[-2000:]}")
    data = json.loads(html.unescape(m.group(1)))
    if not data["ok"]:
        raise ProbeError(f"probe failed in {name}:\n{data['error']}")
    return data["result"]
