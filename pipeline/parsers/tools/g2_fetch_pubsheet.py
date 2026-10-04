"""Snapshot a *published* Google Sheet (docs.google.com/spreadsheets/d/e/<pubid>/pubhtml)
tab by tab, for published sheets whose whole-document xlsx export (``pub?output=xlsx``)
returns HTTP 400.

Writes into raw/<tournament_id>/<out_subdir>/:
    manifest.json        {"pubhtml": url, "tabs": [{"name", "gid", "csv", "html"}]}
    <gid>.csv            pub?gid=<gid>&single=true&output=csv
    <gid>.html           pubhtml/sheet?headers=false&gid=<gid> (keeps merged cells/colours)

Usage:
    python -m pipeline.parsers.tools.g2_fetch_pubsheet <tournament_id> <out_subdir> <pubhtml_url>
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

from ...config import RAW_DIR

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) sbranks-fetch/1.0"}


def main(tid: str, sub: str, url: str) -> None:
    base = url.split("?")[0]
    if base.endswith("/pubhtml"):
        base = base[: -len("/pubhtml")]
    out = RAW_DIR / tid / sub
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(UA)
    page = s.get(base + "/pubhtml", timeout=60).text
    tabs = re.findall(r'items\.push\(\{name: "((?:[^"\\]|\\.)*)", pageUrl: "[^"]*", gid: "(\d+)"', page)
    if not tabs:
        raise SystemExit("no tabs found")
    manifest = {"pubhtml": base + "/pubhtml", "tabs": []}
    for name, gid in tabs:
        name = json.loads(f'"{name}"')
        r = s.get(f"{base}/pub?gid={gid}&single=true&output=csv", timeout=60)
        r.raise_for_status()
        (out / f"{gid}.csv").write_bytes(r.content)
        time.sleep(1)
        h = s.get(f"{base}/pubhtml/sheet?headers=false&gid={gid}", timeout=60)
        h.raise_for_status()
        (out / f"{gid}.html").write_bytes(h.content)
        time.sleep(1)
        manifest["tabs"].append({"name": name, "gid": gid, "csv": f"{gid}.csv", "html": f"{gid}.html"})
        print(f"{name}: {len(r.content)} bytes csv, {len(h.content)} bytes html")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:4])
