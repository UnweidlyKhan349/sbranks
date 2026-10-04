"""Cross-check parsed ISOBowl output against the rendered stats page (raw/<id>/isobowl/stats_page.txt).

    python -m pipeline.parsers.tools.g1_check_isobowl <tournament_id> ...

Compares team W/L/PF/PA/COR/INC/NEG and the multiset of individual rows
(team, GP, TUH, PTS, COR, INC, NEG) - names differ on purpose (we pick real names).
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict

from pipeline.config import RAW_DIR
from pipeline.schema import load_parsed, num


def _tables(txt: str):
    teams, players = {}, []
    section = None
    for line in txt.splitlines():
        if line.startswith("=== "):
            section = "team" if "initial" in line else "ind"
            continue
        parts = line.split("\t")
        if section == "team" and len(parts) == 11 and parts[1].strip().isdigit():
            nm = parts[0].strip()
            teams[nm] = tuple(int(float(x)) for x in (parts[1], parts[2], parts[3], parts[4], parts[5], parts[8], parts[9], parts[10]))
        if section == "ind" and len(parts) == 9 and parts[2].strip().isdigit():
            players.append((parts[0].strip(), parts[1].strip(), *(int(float(x)) for x in (parts[2], parts[3], parts[4], parts[6], parts[7], parts[8]))))
    return teams, players


def check(tid: str) -> None:
    teams, players = _tables((RAW_DIR / tid / "isobowl" / "stats_page.txt").read_text())
    d = load_parsed(tid)
    rec = defaultdict(lambda: [0, 0, 0, 0, 0])
    for g in d["games"]:
        s1, s2 = num(g["score1"]), num(g["score2"])
        for t, a, b in ((g["team1"], s1, s2), (g["team2"], s2, s1)):
            r = rec[t]; r[0] += 1; r[1] += a > b; r[2] += a < b; r[3] += a; r[4] += b
    tot = defaultdict(lambda: [0, 0, 0])
    for r in d["player_stats"]:
        if r["subject"] == "overall":
            t = tot[r["team"]]
            t[0] += int(num(r["correct"])); t[1] += int(num(r["zeros"])); t[2] += int(num(r["negs"]))
    bad = 0
    for nm, (gp, wn, ls, pf, pa, cor, inc, neg) in teams.items():
        mine = (*[int(x) for x in rec[nm]], *tot[nm])
        if mine != (gp, wn, ls, pf, pa, cor, inc, neg):
            bad += 1
            print(f"  TEAM {nm}: page {(gp, wn, ls, pf, pa, cor, inc, neg)} parsed {mine}")
    page = Counter(p[1:] for p in players)
    mine = Counter()
    names = {}
    for r in d["player_stats"]:
        if r["subject"] == "overall":
            k = (r["team"], *(int(num(r[x])) for x in ("gp", "tuh", "points", "correct", "zeros", "negs")))
            mine[k] += 1; names[k] = r["player"]
    for k in (page - mine):
        print("  PAGE ONLY", [p[0] for p in players if p[1:] == k], k)
    for k in (mine - page):
        print("  PARSED ONLY", names[k], k)
    print(f"{tid}: {len(teams)} teams on page ({bad} differ), {len(players)} page player rows, "
          f"{sum((page - mine).values())} page-only, {sum((mine - page).values())} parsed-only")


if __name__ == "__main__":
    for tid in sys.argv[1:]:
        check(tid)
