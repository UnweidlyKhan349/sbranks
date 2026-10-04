"""Snapshot an Eyrie hub (eyrieshub.fly.dev) tournament: every game scoresheet + player pages.

    python -m pipeline.parsers.tools.g1_fetch_eyrie <tournament_id> [base_url]

Reads the already-fetched rrscores.html / results.html (DE bracket) / sebracket.html in
raw/<id>/, collects every /game/<n> link and saves the game pages to raw/<id>/eyrie/games/<n>.html.
Each game page embeds the per-question scoresheet as a JS literal (``let questions = [...]``)
with player ids; player pages /stats/<uid> (full name + per-category totals) are saved to
raw/<id>/eyrie/players/<uid>.html. Cached files are not re-fetched.
"""
from __future__ import annotations

import re
import sys
import time

import requests

from pipeline.config import RAW_DIR

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) sbranks-fetch/1.0"}


def _get(url: str) -> str | None:
    for i in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2 * (i + 1))
    return None


def main(tid: str, base: str = "https://eyrieshub.fly.dev") -> None:
    raw = RAW_DIR / tid
    gids: set[int] = set()
    for f in ("rrscores.html", "results.html", "sebracket.html"):
        p = raw / f
        if p.exists():
            gids |= {int(x) for x in re.findall(r'href="/game/(\d+)"', p.read_text())}
    gdir = raw / "eyrie" / "games"
    gdir.mkdir(parents=True, exist_ok=True)
    uids: set[int] = set()
    for gid in sorted(gids):
        out = gdir / f"{gid}.html"
        if not out.exists():
            html = _get(f"{base}/game/{gid}")
            time.sleep(0.3)
            if html is None:
                print("game", gid, "unavailable")
                continue
            out.write_text(html)
        uids |= {int(x) for x in re.findall(r'data-user="(\d+)"', out.read_text())}
    pdir = raw / "eyrie" / "players"
    pdir.mkdir(parents=True, exist_ok=True)
    for uid in sorted(uids):
        out = pdir / f"{uid}.html"
        if out.exists():
            continue
        html = _get(f"{base}/stats/{uid}")
        time.sleep(0.3)
        if html is None:
            print("player", uid, "unavailable")
            continue
        out.write_text(html)
    print(f"{len(gids)} games, {len(uids)} players")


if __name__ == "__main__":
    main(*sys.argv[1:])
