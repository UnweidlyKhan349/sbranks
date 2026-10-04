"""Niskayuna Science Bowl tournaments (niskyscibowl.com: NSI 2023, NWI 2024).

The results pages embed a published Google Sheet (pubhtml iframe); we snapshot it as xlsx
(``.../pub?output=xlsx``) into raw/<id>/results_sheet.xlsx. Layout (same template both years):

* "Round Robin": pools of 4, two pools side by side. Header row ``<team1..team4> | PPG | Points``;
  data rows ``<team> | score vs team1..team4 | PPG | Points | W: x T: y L: z``. Cell (row, col)
  is the *row* team's score against the column team. The "Order of Matchups" block on the
  same tab gives the round of each pairing (RR1: 1v2 & 3v4, RR2: 1v3 & 2v4, RR3: 1v4 & 2v3).
* "Single Elimination": 16-team bracket; team cells with the score in the next column;
  consecutive scored entries in a column are one game; "Room n"/seed labels are ignored.

Scores can be negative (negs cost the negging team 4 points under these rules).
"""
from __future__ import annotations

import re
from itertools import combinations

from ..registry import Tournament
from ..schema import TournamentWriter, num
from ..util.grid import Grid, load_grids

_SE_ROUNDS = {8: "R16", 4: "QF", 2: "SF", 1: "Final"}


def _rr_order(g: Grid) -> dict[frozenset[int], int]:
    """Parse 'RR1 | Team 1 vs Team 2 | Team 3 vs Team 4' rows -> {frozenset({1,2}): 1, ...}."""
    out: dict[frozenset[int], int] = {}
    for r, c in g.find(r"^RR\s*\d+$"):
        rnd = int(re.sub(r"\D", "", g.text(r, c)))
        for cc in range(c + 1, c + 6):
            m = re.match(r"Team (\d+) vs\.? Team (\d+)", g.text(r, cc), re.I)
            if m:
                out[frozenset((int(m.group(1)), int(m.group(2))))] = rnd
    return out


def parse_rr(g: Grid, w: TournamentWriter, check: bool = True) -> list[str]:
    order = _rr_order(g)
    teams_all: list[str] = []
    for hr, pc in g.find(r"^PPG$"):
        if num(g.cell(hr, pc)) is not None:
            continue
        # team columns: contiguous non-empty cells left of PPG
        cols = []
        c = pc - 1
        while c >= 0 and g.text(hr, c):
            cols.insert(0, c)
            c -= 1
        names = [g.text(hr, c) for c in cols]
        if all(re.match(r"^Team \d+$", n) for n in names):
            continue  # example group
        label_col = cols[0] - 1
        pool = ""
        for rr in range(hr - 1, max(hr - 5, -1), -1):
            if g.text(rr, label_col):
                pool = g.text(rr, label_col)
                break
        rows = {}
        r = hr + 1
        while r < g.nrows and len(rows) < len(names):
            n = g.text(r, label_col)
            if n in names:
                rows[n] = r
            r += 1
        missing = [n for n in names if n not in rows]
        if missing:
            w.warn(f"pool {pool}: rows missing for {missing}")
            continue
        for n in names:
            w.team(n)
            teams_all.append(n)
        for (i, a), (j, b) in combinations(enumerate(names), 2):
            sa, sb = g.num(rows[a], cols[j]), g.num(rows[b], cols[i])
            if sa is None and sb is None:
                continue
            if sa is None or sb is None:
                w.warn(f"pool {pool}: {a} vs {b} has only one score ({sa}, {sb})")
                continue
            rnd = order.get(frozenset((i + 1, j + 1)))
            w.game(a, b, sa, sb, stage="rr", round=f"RR{rnd}" if rnd else "", seq=rnd or 1,
                   notes=f"pool {pool}")
        if check:
            for i, a in enumerate(names):
                wtl = g.text(rows[a], pc + 2)
                m = re.search(r"W:\s*(\d+)\s*T:\s*(\d+)\s*L:\s*(\d+)", wtl)
                if not m:
                    continue
                mine = [0, 0, 0]
                for j, b in enumerate(names):
                    if i == j:
                        continue
                    sa, sb = g.num(rows[a], cols[j]), g.num(rows[b], cols[i])
                    if sa is None or sb is None:
                        continue
                    mine[0 if sa > sb else 1 if sa == sb else 2] += 1
                if tuple(mine) != tuple(int(x) for x in m.groups()):
                    w.warn(f"pool {pool}: {a} record {mine} != sheet {wtl}")
    return teams_all


def parse_se(g: Grid, w: TournamentWriter, known: set[str], seq0: int) -> None:
    rounds = []
    for c in range(g.ncols - 1):
        entries = [(r, g.text(r, c), g.num(r, c + 1)) for r in range(g.nrows)
                   if g.text(r, c) and num(g.cell(r, c)) is None and g.num(r, c + 1) is not None]
        if entries:
            rounds.append((c, entries))
    for k, (c, entries) in enumerate(rounds):
        if len(entries) % 2:
            w.warn(f"SE column {c}: odd number of entries")
        n_games = len(entries) // 2
        label = _SE_ROUNDS.get(n_games, f"SE{k + 1}")
        nxt = {e[1] for e in rounds[k + 1][1]} if k + 1 < len(rounds) else None
        for i in range(0, len(entries) - 1, 2):
            (_, a, sa), (_, b, sb) = entries[i], entries[i + 1]
            for x in (a, b):
                if x not in known:
                    w.warn(f"SE team {x!r} not in round robin")
            w.game(a, b, sa, sb, stage="playoff", round=label, seq=seq0 + k)
            win = a if sa > sb else b if sb > sa else None
            if nxt is not None and win is not None and win not in nxt:
                w.warn(f"SE {label}: winner {win} not found in next round")


def parse(t: Tournament, w: TournamentWriter, results_file: str = "results_sheet.xlsx",
          rr_tab: str = "Round Robin", se_tab: str = "Single Elimination",
          team_hints: dict[str, dict[str, str]] | None = None) -> None:
    grids = load_grids(t.raw(results_file))
    teams = parse_rr(grids[rr_tab], w)
    parse_se(grids[se_tab], w, set(teams), seq0=4)
    for name, h in (team_hints or {}).items():
        w.team(name, school=h.get("school", ""), state=h.get("state", ""))
