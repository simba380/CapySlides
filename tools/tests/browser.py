"""Run a built deck in a headless Chromium browser and collect results from a probe script.

The probe is the body of an async JS function. It runs after the engine has booted and its
return value comes back as Python data. Pages are opened via file:// with all network
lookups disabled, so every run also proves the deck works offline.

Built fixtures stay in .tmp/fixtures/ for manual inspection.
"""
from __future__ import annotations

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


def find_browser() -> str | None:
    for c in CANDIDATES:
        if not c:
            continue
        if Path(c).is_file():
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


class ProbeError(AssertionError):
    pass


def run(page: str, probe_js: str, name: str, size=(1280, 800), query: str = "", budget_ms: int = 3000):
    """Write `page` (+ probe) to .tmp/fixtures/<name>.html, load it headless, return the probe result."""
    browser = find_browser()
    if not browser:
        raise RuntimeError("no Chromium-based browser found (set DECK_TEST_BROWSER)")
    FIXTURES_OUT.mkdir(parents=True, exist_ok=True)
    (FIXTURES_OUT / f"{name}.html").write_text(page, encoding="utf-8", newline="\n")
    probed = FIXTURES_OUT / f"{name}.probe.html"
    probed.write_text(page.replace("</body>", PROBE_WRAPPER % probe_js + "\n</body>"), encoding="utf-8", newline="\n")

    cmd = [
        browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={TMP / 'browser-profile'}",
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
