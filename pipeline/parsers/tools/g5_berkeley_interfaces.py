"""Download the per-game scoring interfaces of a Berkeley Science Bowl backend sheet.

Berkeley's scoring backend (a Google Sheet) lists one public "interface" spreadsheet per
game in its 'Round Robin Matchups' / 'DE Matchups' tabs (column 'Interface ID'). The first
tab of each interface ('Volunteer Side') is the question-by-question scoresheet: lineups for
each half, and for every question a TU / Penalty / B row with TRUE under the player slot
that buzzed (or the captain slot for bonuses) plus the question category.

Only the first tab is needed, so we save its CSV export (~8 KB) instead of the ~6 MB xlsx:

    python -m pipeline.parsers.tools.g5_berkeley_interfaces 2023-12-03-berkeley-science-bowl \
        --backend backend.xlsx

writes raw/<id>/interfaces/<interface index>.csv and raw/<id>/interfaces/index.csv.
"""
from __future__ import annotations

import argparse
import csv
import re
import time

import requests

from ... import registry
from ...util.grid import load_grids

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) sbranks-fetch/1.0"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tournament")
    ap.add_argument("--backend", default="backend.xlsx")
    ap.add_argument("--tabs", nargs="*", default=["Round Robin Matchups", "DE Matchups"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    t = registry.get(a.tournament)
    grids = load_grids(t.raw(a.backend))
    out = t.raw_dir / "interfaces"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for tab in a.tabs:
        g = grids[tab]
        hdr = g.row_texts(0)
        for r in range(1, g.nrows):
            d = dict(zip(hdr, g.row_texts(r)))
            iid = d.get("Interface ID", "")
            if not re.match(r"^[A-Za-z0-9_-]{20,}$", iid):
                continue
            idx = str(int(float(d["Interface Index"])))
            d["Interface Index"] = idx
            d["tab"] = tab
            rows.append(d)
            dest = out / f"{idx}.csv"
            if dest.exists() and not a.force:
                continue
            url = f"https://docs.google.com/spreadsheets/d/{iid}/export?format=csv"
            resp = requests.get(url, headers=UA, timeout=60)
            ok = resp.status_code == 200 and resp.headers.get("content-type", "").startswith("text/csv")
            print(idx, resp.status_code, len(resp.content) if ok else "FAILED")
            if ok:
                dest.write_bytes(resp.content)
            time.sleep(1.0)
    cols = ["Interface Index", "tab", "First Team", "Second Team", "Round #", "Type", "Division",
            "Room", "Interface ID", "Round Done", "First Team Score", "Second Team Score"]
    with open(out / "index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} interfaces listed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
