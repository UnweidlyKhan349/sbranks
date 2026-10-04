"""MNSBT 2024 (online, high-school teams) results workbook.

* ``Round Robin``: eight pools (Hydrogen .. Sulfur); per pool a matrix ``ID | Team Name |
  H1 .. H6 | PPG | Ranking Points | RR Ranking`` with the row team's own score against each
  column opponent (``BYE`` rows are empty slots). Ranking points (2 per win) and PPG are
  cross-checked against the games.
* ``Round Robin Room Assignments``: ``H1 – H2`` per room and round -> RR round of each game.
* ``Double Elimination``: visual bracket; ``Hydrogen-1 (W1-1)`` labels between the two teams,
  each team's score in the cell to its right (read with g6_common). The two finals share one
  box (scores in two columns) and are given as explicit games.
"""
from __future__ import annotations

import re
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import load_grids
from .g6_common import BracketSpec, Roster, bracket_games, de_warnings, emit_games, score_matrix_pairs


def parse(t: Tournament, w: TournamentWriter, bracket: dict[str, Any] | None = None,
          aliases: dict[str, str] | None = None) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    g = grids["Round Robin"]

    # round of each pairing
    ra = grids["Round Robin Room Assignments"]
    round_of: dict[frozenset, int] = {}
    for c in range(ra.ncols):
        m = re.match(r"^Round (\d+)$", ra.text(0, c))
        if not m:
            continue
        for r in range(1, ra.nrows):
            mm = re.match(r"^([A-Z]\d)\s*[-–]+\s*([A-Z]\d|BYE)$", ra.text(r, c))
            if mm and mm.group(2) != "BYE":
                round_of[frozenset((mm.group(1), mm.group(2)))] = int(m.group(1))

    roster = Roster((), aliases)
    for hr, hc in g.find(r"^Team Name$"):
        pool = g.text(hr - 2, 0)
        cols = {}
        for c in range(hc + 1, g.ncols):
            if re.match(r"^[A-Z]\d$", g.text(hr, c)):
                cols[g.text(hr, c)] = c
        hdr = {g.text(hr, c): c for c in range(g.ncols)}
        rows = []
        r = hr + 1
        while r < g.nrows and re.match(r"^[A-Z]\d$", g.text(r, 0)):
            if g.text(r, hc) and g.text(r, hc).upper() != "BYE":
                rows.append(r)
            r += 1
        ids = [g.text(x, 0) for x in rows]
        names = [roster.add(g.text(x, hc)) for x in rows]
        for n in names:
            w.team(n)
        pts = {n: 0 for n in names}
        tot = {n: [0.0, 0] for n in names}
        for i, j, si, sj in score_matrix_pairs(names, lambda a, b: g.cell(rows[a], cols[ids[b]]), w, pool):
            rnd = round_of.get(frozenset((ids[i], ids[j])))
            if rnd is None:
                w.warn(f"{pool}: no round for {ids[i]} vs {ids[j]}")
            w.game(names[i], names[j], si, sj, stage="rr", round=f"RR{rnd}" if rnd else "",
                   seq=rnd or 1, notes=pool, game_id=f"RR{rnd}-{ids[i]}-{ids[j]}")
            pts[names[i]] += 2 if si > sj else 1 if si == sj else 0
            pts[names[j]] += 2 if sj > si else 1 if si == sj else 0
            for n, s in ((names[i], si), (names[j], sj)):
                tot[n][0] += s
                tot[n][1] += 1
        # cross-check the sheet's Ranking Points and PPG columns
        for x, n in zip(rows, names):
            rp = g.num(x, hdr.get("Ranking Points", -1))
            ppg = g.num(x, hdr.get("PPG", -1))
            if rp is not None and rp != pts[n]:
                w.warn(f"{pool}: {n} ranking points {rp} != computed {pts[n]}")
            if ppg is not None and tot[n][1] and abs(ppg - tot[n][0] / tot[n][1]) > 0.051:
                w.warn(f"{pool}: {n} PPG {ppg} != computed {tot[n][0] / tot[n][1]:.2f}")

    if bracket:
        spec = BracketSpec.from_opts(bracket)
        games = bracket_games(grids[spec.tab], spec, roster, w)
        emit_games(w, games, stage="playoff")
        de_warnings(w, games)
