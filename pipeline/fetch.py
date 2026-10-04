"""Download every tournament's raw sources into raw/<tournament_id>/.

Source kinds (``sources:`` entries in a tournament YAML):

    gsheet        {sheet_id, file}            Google Sheet exported as .xlsx (public sheets only)
    scibowl_live  {slug}                      All CSV datasets of every report on scibowl.live
    isobowl       {slug}                      ISOBowl tournament JSON + per-question score logs
    url           {url, file}                 Plain HTTP GET (HTML pages, xlsx files, ...)
    browser_url   {url, file}                 GET through headless Chromium (sites that block
                                              scripted clients, e.g. science.osti.gov)
    drive_file    {file_id, file}             Public Google Drive file
    manual        {file}                      Hand-made file already present in raw/<id>/

Run:  python -m pipeline.fetch [--only ID ...] [--force]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

from . import registry
from .config import ROOT

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) sbranks-fetch/1.0"}
SESSION = requests.Session()
SESSION.headers.update(UA)


def _get(url: str, *, tries: int = 4, timeout: int = 60) -> requests.Response:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r
        except Exception as e:  # noqa: BLE001 - retry any network failure
            last = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def fetch_gsheet(src: dict[str, Any], dest: Path) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{src['sheet_id']}/export?format=xlsx"
    r = _get(url)
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or "spreadsheetml" not in ctype:
        return f"unavailable (HTTP {r.status_code})"
    _write(dest / src.get("file", "sheet.xlsx"), r.content)
    return f"ok {len(r.content)} bytes"


def fetch_scibowl_live(src: dict[str, Any], dest: Path) -> str:
    slug = src["slug"]
    base = f"https://www.scibowl.live/stats/{slug}"
    out = dest / "scibowl_live"
    reports = [{"key": "combined", "manifest_path": "manifest.json"}]
    r = _get(f"{base}/reports.json")
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
        _write(out / "reports.json", r.content)
        reports = r.json().get("reports", reports)
    n = 0
    for rep in reports:
        mpath = rep["manifest_path"]
        r = _get(f"{base}/{mpath}")
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("application/json"):
            continue
        rep_dir = out / (rep["key"] if rep["key"] != "combined" else "combined")
        _write(rep_dir / "manifest.json", r.content)
        manifest = r.json()
        prefix = mpath.rsplit("/", 1)[0] + "/" if "/" in mpath else ""
        for name, rel in (manifest.get("datasets") or {}).items():
            rr = _get(f"{base}/{prefix}{rel}")
            if rr.status_code == 200:
                _write(rep_dir / Path(rel).name, rr.content)
                n += 1
    return f"ok {n} datasets" if n else "unavailable"


def fetch_isobowl(src: dict[str, Any], dest: Path) -> str:
    slug = src["slug"]
    out = dest / "isobowl"
    n = 0
    for name, path in [("tournament.json", f"/api/tournaments/{slug}"),
                       ("scorelogs.json", f"/api/tournaments/{slug}/scorelogs")]:
        r = _get(f"https://isobowl.com{path}")
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
            _write(out / name, r.content)
            n += 1
    return f"ok {n} files" if n else "unavailable"


def fetch_url(src: dict[str, Any], dest: Path) -> str:
    r = _get(src["url"])
    if r.status_code != 200:
        return f"unavailable (HTTP {r.status_code})"
    _write(dest / src["file"], r.content)
    return f"ok {len(r.content)} bytes"


def fetch_drive_file(src: dict[str, Any], dest: Path) -> str:
    url = f"https://drive.google.com/uc?export=download&id={src['file_id']}"
    r = _get(url)
    if r.status_code != 200 or r.headers.get("content-type", "").startswith("text/html"):
        return f"unavailable (HTTP {r.status_code}, {r.headers.get('content-type')})"
    _write(dest / src["file"], r.content)
    return f"ok {len(r.content)} bytes"


_BROWSER_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const [url, out, warm] = process.argv.slice(2);
  const b = await chromium.launch();
  const ctx = await b.newContext({ ignoreHTTPSErrors: true });
  const p = await ctx.newPage();
  if (warm) { await p.goto(warm, { waitUntil: 'domcontentloaded', timeout: 60000 }); }
  const r = await ctx.request.get(url, { timeout: 60000 });
  require('fs').writeFileSync(out, await r.body());
  console.log(r.status());
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def fetch_browser_url(src: dict[str, Any], dest: Path) -> str:
    """Fetch through Chromium's network stack (passes bot checks that block requests)."""
    out = dest / src["file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    script = ROOT / ".cache" / "browser_fetch.js"
    script.parent.mkdir(exist_ok=True)
    script.write_text(_BROWSER_JS)
    npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    warm = src.get("warm_url") or ""
    p = subprocess.run(["node", str(script), src["url"], str(out), warm], capture_output=True,
                       text=True, env={**__import__("os").environ, "NODE_PATH": npm_root},
                       timeout=180)
    status = p.stdout.strip()
    if p.returncode != 0 or status != "200":
        if out.exists():
            out.unlink()
        return f"unavailable (status {status or p.stderr.strip()[:200]})"
    return f"ok {out.stat().st_size} bytes"


FETCHERS = {
    "gsheet": fetch_gsheet,
    "scibowl_live": fetch_scibowl_live,
    "isobowl": fetch_isobowl,
    "url": fetch_url,
    "browser_url": fetch_browser_url,
    "drive_file": fetch_drive_file,
}


def _target_exists(src: dict[str, Any], dest: Path) -> bool:
    kind = src["kind"]
    if kind == "scibowl_live":
        return (dest / "scibowl_live").exists()
    if kind == "isobowl":
        return (dest / "isobowl" / "tournament.json").exists()
    f = src.get("file")
    return bool(f) and (dest / f).exists()


def fetch_tournament(t: registry.Tournament, force: bool = False) -> list[str]:
    log = []
    for src in t.sources:
        kind = src.get("kind")
        fn = FETCHERS.get(kind)
        if fn is None:
            log.append(f"{kind}: skipped (manual)")
            continue
        if not force and _target_exists(src, t.raw_dir):
            log.append(f"{kind} {src.get('file') or src.get('slug')}: cached")
            continue
        try:
            log.append(f"{kind} {src.get('file') or src.get('slug')}: {fn(src, t.raw_dir)}")
        except Exception as e:  # noqa: BLE001
            log.append(f"{kind}: ERROR {e}")
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", help="tournament ids")
    ap.add_argument("--force", action="store_true", help="re-download cached files")
    ap.add_argument("--all", action="store_true", help="include excluded tournaments")
    a = ap.parse_args(argv)
    ts = registry.all_tournaments(include_excluded=a.all or bool(a.only))
    if a.only:
        ts = [t for t in ts if t.id in set(a.only)]
    report = {}
    for t in ts:
        report[t.id] = fetch_tournament(t, force=a.force)
        print(t.id, "|", "; ".join(report[t.id]), flush=True)
    (ROOT / ".cache").mkdir(exist_ok=True)
    (ROOT / ".cache" / "fetch_report.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
