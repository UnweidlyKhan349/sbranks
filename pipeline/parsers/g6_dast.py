"""DAST 2024 (online) results workbook.

* ``RR Groups``: five 4-team groups (alpha .. epsilon). Each team row has ``Game k Score``
  cells written ``own-opponent`` (e.g. ``110-72``); the opponents follow the fixed schedule
  on ``Tournament Schedule`` (RR1: 1v2, 3v4; RR2: 1v3, 2v4; RR3: 1v4, 2v3). Both teams'
  cells are checked against each other. Team cells may carry a points total
  (``TJHSST A - 210``), which is stripped.
* ``Bracket``: visual double-elimination bracket with ``Game N`` labels between the two
  teams, a score cell and the advancing team to the right (read with g6_common). The score
  strings are not consistently ordered (``40-106`` for a 106-40 win), so the winner shown in
  the bracket gets the higher score.
"""
from __future__ import annotations

import re
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import load_grids
from .g6_common import SCORE_RE, BracketSpec, Roster, bracket_games, de_warnings, emit_games

SCHEDULE = {1: [(1, 2), (3, 4)], 2: [(1, 3), (2, 4)], 3: [(1, 4), (2, 3)]}


def parse(t: Tournament, w: TournamentWriter, bracket: dict[str, Any] | None = None,
          aliases: dict[str, str] | None = None, team_list_tab: str | None = "Tournament Schedule") -> None:
    grids = load_grids(t.raw("results.xlsx"))
    g = grids["RR Groups"]
    roster = Roster((), aliases)
    if team_list_tab:  # registered team names (fuller than the RR group labels)
        tg = grids[team_list_tab]
        hr, hc = tg.find_first(r"^Teams$")
        for r in range(hr + 1, tg.nrows):
            if tg.text(r, hc):
                roster.add(tg.text(r, hc))
    groups = []
    stop = (g.find_first(r"Rankings") or (g.nrows, 0))[0]
    for r, nc in g.find(r"^(alpha|beta|gamma|delta|epsilon|zeta|eta|theta)$"):
        if r >= stop:
            continue
        gname, c = g.text(r, nc), nc + 2      # Game 1/2/3 Score columns follow W-L
        rows = []
        rr = r + 1
        while rr < g.nrows and g.num(rr, nc - 1) is not None:
            rows.append(rr)
            rr += 1
        teams = {}
        for x in rows:
            slot = int(g.num(x, nc - 1))
            raw = re.sub(r"\s*-\s*\d+$", "", g.text(x, nc))
            try:
                name = roster.add(roster.resolve(raw))
            except KeyError:
                name = roster.add(raw)
            teams[slot] = (name, x)
            w.team(name)
        groups.append((gname, c, teams))

    for gname, c, teams in groups:
        for rnd, pairs in SCHEDULE.items():
            col = c + rnd - 1
            for a, b in pairs:
                if a not in teams or b not in teams:
                    continue
                (na, ra), (nb, rb) = teams[a], teams[b]
                ma, mb = SCORE_RE.match(g.text(ra, col)), SCORE_RE.match(g.text(rb, col))
                if not ma or not mb:
                    w.warn(f"{gname} RR{rnd}: {na} vs {nb}: missing score ({g.text(ra, col)!r}/{g.text(rb, col)!r})")
                    continue
                sa, oa = float(ma.group(1)), float(ma.group(2))
                sb, ob = float(mb.group(1)), float(mb.group(2))
                if (sa, oa) != (ob, sb):
                    w.warn(f"{gname} RR{rnd}: {na} {ma.group(0)} vs {nb} {mb.group(0)} disagree")
                note = f"group {gname}" + ("; 0 points in the source" if 0 in (sa, oa) else "")
                w.game(na, nb, sa, oa, stage="rr", round=f"RR{rnd}", seq=rnd, notes=note,
                       game_id=f"RR{rnd}-{gname}-{a}v{b}")

    if bracket:
        spec = BracketSpec.from_opts(bracket)
        games = bracket_games(grids[spec.tab], spec, roster, w)
        emit_games(w, games, stage="playoff")
        de_warnings(w, games)
