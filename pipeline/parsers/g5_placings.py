"""Final placings only (East Brunswick Invitational 2024 'Results' tab).

Rows: Place | Team | free-text note; the champion's note holds the final's score as
'*Final: <team A> <score> - <team B> <score>'. Every placed team is registered (with its
place in the notes); the final is the only game with a known result.
"""
from __future__ import annotations

import re

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import load_grids

FINAL_RX = re.compile(r"final:\s*(.+?)\s+(-?\d+)\s*[-–]\s*(.+?)\s+(-?\d+)\s*$", re.I)


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
          tab: str = "Results") -> None:
    g = load_grids(t.raw(results))[tab]
    teams = []
    for r in range(1, g.nrows):
        place, team = g.num(r, 0), g.text(r, 1)
        if team and place is not None:
            teams.append(team)
            w.team(team, notes=f"final place {int(place)}")
    n_final = 0
    for r in range(g.nrows):
        for c in range(g.ncols):
            m = FINAL_RX.search(g.text(r, c))
            if m:
                a, sa, b, sb = m.group(1), m.group(2), m.group(3), m.group(4)
                for x in (a, b):
                    if x not in teams:
                        w.warn(f"final team {x!r} not in placings")
                w.game(a, b, sa, sb, stage="playoff", round="Final", seq=1)
                n_final += 1
    if not n_final:
        w.warn("no final score found")
