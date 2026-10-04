"""Clements Invitational 2026: winner-only double-elimination bracket sheet (DE4 onwards).

Layout (results.xlsx, "Sheet1"): a header row names the round of each team column
("DE4" ... "DE9"). Each game is drawn as two team cells in one column with a "Room n" /
"Stage" label one column to the right, between them; the winner is written on the row just
above the label in a later column ("Bye" cells are skipped). No scores are recorded.
The earlier rounds (round robin, DE1-3) and all statistics were only on csb.clementsjets.org,
which refuses connections.
"""
from __future__ import annotations

import re

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import Grid, load_grids

_LABEL = re.compile(r"^(Room\s*\d+|Stage)$", re.I)


def _is_team(g: Grid, r: int, c: int) -> bool:
    t = g.text(r, c)
    return bool(t) and not _LABEL.match(t) and t.lower() not in ("bye", "champions", "champion") \
        and not re.match(r"^DE\s*\d+$", t)


def parse(t: Tournament, w: TournamentWriter, tab: str = "Sheet1", aliases: dict[str, str] | None = None,
          seq0: int = 10) -> None:
    g = load_grids(t.raw("results.xlsx"))[tab]
    aliases = aliases or {}
    name = lambda s: aliases.get(s, s)  # noqa: E731
    hdr = g.find_first(r"^DE\s*\d+$")
    hr = hdr[0]
    round_of = {c: g.text(hr, c) for c in range(g.ncols) if re.match(r"^DE\s*\d+$", g.text(hr, c))}
    games = []
    for r, c in g.find(_LABEL.pattern):
        tc = c - 1
        above = next((rr for rr in range(r - 1, hr, -1) if _is_team(g, rr, tc)), None)
        below = next((rr for rr in range(r + 1, g.nrows) if _is_team(g, rr, tc)), None)
        if above is None or below is None:
            w.warn(f"label at ({r},{c}): teams not found")
            continue
        a, b = name(g.text(above, tc)), name(g.text(below, tc))
        win = None
        for wr in (r - 1, r, r - 2):
            win = next((name(g.text(wr, cc)) for cc in range(c + 1, g.ncols) if _is_team(g, wr, cc)), None)
            if win:
                break
        if win not in (a, b):
            w.warn(f"{a} vs {b}: winner {win!r} not one of the teams")
            continue
        rnd = round_of.get(tc, "")
        games.append((int(re.sub(r"\D", "", rnd) or 0), rnd, a, b, win, g.text(r, c)))
    games.sort()
    for k, rnd, a, b, win, lab in games:
        w.game(a, b, stage="playoff", round=rnd, seq=seq0 + k, result="1" if win == a else "2",
               notes=f"{lab}; winner only (no scores on the bracket sheet)")
    champ = g.find_first(r"^Champions?$")
    if champ:
        r, c = champ
        cw = next((name(g.text(rr, c)) for rr in (r - 1, r + 1) if _is_team(g, rr, c)), None)
        if cw and games and cw != games[-1][4]:
            w.warn(f"champion cell {cw!r} != winner of last game {games[-1][4]!r}")
