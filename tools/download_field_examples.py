"""Download only pinned data and provenance; never execute upstream code."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "examples" / "field" / "raw"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "GeoQC-field-examples"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def main() -> None:
    manifest_path = DEST.parent / "download_manifest.json"
    if manifest_path.exists():
        raise SystemExit("Manifest already exists; preserve this download snapshot.")
    files = []
    repositories = []
    for label, repo, branch, folder in (
        ("oysand", "Mazvel/maswavespy", "main", "examples/Data"),
        ("chevremont", "hadrienmichel/SardineReborn", "master", "example/Chevremont"),
    ):
        commit = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/{branch}"))["sha"]
        listing = json.loads(fetch(f"https://api.github.com/repos/{repo}/contents/{folder}?ref={commit}"))
        paths = [item["path"] for item in listing if item["type"] == "file"]
        tree = json.loads(fetch(f"https://api.github.com/repos/{repo}/git/trees/{commit}"))["tree"]
        paths += [item["path"] for item in tree if item["path"].lower().startswith(("license", "readme"))]
        if label == "oysand":
            paths += ["examples/MASWavesPy_Dispersion_test1.py", "examples/MASWavesPy_Dispersion_test2.py"]
        repositories.append({"label": label, "repository": repo, "commit": commit})
        for upstream_path in paths:
            url = f"https://raw.githubusercontent.com/{repo}/{commit}/{upstream_path}"
            content = fetch(url)
            local = DEST / label / upstream_path
            local.parent.mkdir(parents=True, exist_ok=True)
            if local.exists() and local.read_bytes() != content:
                raise ValueError(f"Refusing to overwrite different existing file: {local}")
            local.write_bytes(content)
            files.append(
                {
                    "path": local.relative_to(ROOT).as_posix(),
                    "url": url,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
            print(f"Downloaded {local.name}: {len(content)} bytes", flush=True)
    manifest = {
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "repositories": repositories,
        "files": files,
        "scope": "Exploratory field diagnostics; no field acceptance or calibration.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {manifest_path.relative_to(ROOT)} ({len(files)} files)")


if __name__ == "__main__":
    sys.exit(main())
