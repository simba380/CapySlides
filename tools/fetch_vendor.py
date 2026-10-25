"""Download the pinned third-party assets listed in engine/vendor/manifest.json.

    python tools/fetch_vendor.py            download all files, (re)write engine/vendor/lock.json
    python tools/fetch_vendor.py --verify   offline: check every vendored file against lock.json

Files are stored under engine/vendor/<target>/<path>. The lock records url, sha256 and
size per file; build.py refuses to build when a vendored file does not match it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "engine" / "vendor"
MANIFEST = VENDOR / "manifest.json"
LOCK = VENDOR / "lock.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def entries(manifest: dict):
    """Yield (lock key, url, local path) for every file in the manifest."""
    for pkg in manifest["packages"]:
        for rel in pkg["files"]:
            url = manifest["cdn"].format(package=pkg["package"], version=pkg["version"], path=rel)
            key = f'{pkg["target"]}/{rel}'
            yield key, url, VENDOR / key


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(vendor_dir: Path = VENDOR, lock_path: Path = LOCK) -> list[str]:
    """Return a list of problems (empty = all vendored files match the lock)."""
    if not lock_path.exists():
        return [f"missing lock file {lock_path}"]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))["files"]
    problems = []
    for key, meta in sorted(lock.items()):
        path = vendor_dir / key
        if not path.exists():
            problems.append(f"missing: {key}")
        elif sha256(path.read_bytes()) != meta["sha256"]:
            problems.append(f"hash mismatch: {key}")
    expected = {key for key, _, _ in entries(load_manifest())}
    for key in sorted(expected - lock.keys()):
        problems.append(f"in manifest but not in lock (run fetch): {key}")
    return problems


def fetch() -> None:
    lock = {}
    for key, url, path in entries(load_manifest()):
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        lock[key] = {"url": url, "sha256": sha256(data), "bytes": len(data)}
        print(f"{len(data):>8}  {key}")
    LOCK.write_text(json.dumps({"files": lock}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"{sum(m['bytes'] for m in lock.values()):>8}  total, {len(lock)} files -> {LOCK.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="check vendored files against lock.json (offline)")
    args = ap.parse_args()
    if args.verify:
        problems = verify()
        for p in problems:
            print(p, file=sys.stderr)
        print("vendor OK" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    fetch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
