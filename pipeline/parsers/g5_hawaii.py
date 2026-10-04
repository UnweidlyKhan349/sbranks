"""Hawaii-run tournaments ('Iolani Invitational 2024/2025, Pohaku, Hawaii Science Bowl).

Common layout:
  * round-robin pool grids: header row = pool name | team 1 .. team n | 'Champs Point' ...;
    team rows = team | score vs each opponent (row team's score). One game per pair.
  * single/double elimination brackets: columns of ``team | score`` cells
    (see :func:`g5_common.bracket_games`).
'Iolani 2025 additionally has one scoresheet tab per game ('1'..'25': game number, both
teams, per-question tossup/bonus/penalty flags, final scores; no categories or players),
which give the authoritative game list and the RR round (6 games per round).
"""
from __future__ import annotations

import re
import unicodedata

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name
from ..util.grid import Grid, load_grids
from .g5_common import bracket_games, pool_grid_games


def _header_rows(g: Grid) -> list[int]:
    out = []
    for r in range(g.nrows - 1):
        if g.text(r, 0) and g.text(r, 1) and g.text(r + 1, 0) == g.text(r, 1):
            out.append(r)
    return out


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
          rr_tab: str | None = None, bracket_tab: str | None = None,
          bracket_labels: list[str] | None = None, bracket_stage: str = "playoff",
          final_columns: int = 1, name_map: dict | None = None,
          unscored_winners: dict | None = None, unscored_scores: dict | None = None,
          roster_tab: str | None = None, rr_rounds: int = 3) -> None:
    grids = load_grids(t.raw(results))
    if roster_tab:
        # 'A1 Carmel C' cells listing every registered team (pools without results)
        g = grids[roster_tab]
        for r in range(g.nrows):
            for c in range(g.ncols):
                m = re.match(r"^[A-Z]\d+\s+(.+)$", g.text(r, c))
                if m:
                    w.team(m.group(1), notes="registered (round-robin results not posted)")
    if rr_tab:
        g = grids[rr_tab]
        for pool, pairs in pool_grid_games(g, _header_rows(g), name_col=0, first_col=1, step=1,
                                           wl_offset=None, w=w):
            for p in pairs:
                w.game(p.team1, p.team2, p.score1, p.score2, stage="rr", round="", seq=1,
                       notes=f"pool {pool}; round not recorded")
    if bracket_tab:
        bracket_games(w, grids[bracket_tab], labels=bracket_labels, stage=bracket_stage,
                      seq0=rr_rounds, final_columns=final_columns, name_map=name_map,
                      unscored_winners=unscored_winners, unscored_scores=unscored_scores)


def parse_game_tabs(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
                    rr_tab: str = "Round Robin", games_per_round: int = 6, rr_games: int = 18,
                    playoff_rounds: list | None = None) -> None:
    """'Iolani 2025: one tab per game; pool grid and playoff bracket used as cross-checks."""
    grids = load_grids(t.raw(results))
    rr = grids[rr_tab]
    canon = {}
    grid_scores = {}
    for pool, pairs in pool_grid_games(rr, _header_rows(rr), name_col=0, first_col=1, step=1,
                                       wl_offset=None, w=w):
        for p in pairs:
            for nm in (p.team1, p.team2):
                canon[_fold(nm)] = nm
                w.team(nm, notes=f"pool {pool}")
            grid_scores[frozenset((p.team1, p.team2))] = {p.team1: p.score1, p.team2: p.score2}
    playoff_rounds = playoff_rounds or []   # [[label, "19-22"], ...] in play order
    tabs = sorted((k for k in grids if re.match(r"^\d+$", k)), key=int)
    for k in tabs:
        g = grids[k]
        n = int(g.num(0, 2) or int(k))
        a, b = clean_name(g.cell(2, 1)), clean_name(g.cell(2, 5))
        a, b = canon.get(_fold(a), a), canon.get(_fold(b), b)
        sa, sb = g.num(30, 2), g.num(30, 6)
        # score = tossup + bonus + penalty subtotals (penalties are negative)
        for col, s in ((1, sa), (5, sb)):
            sub = sum(g.num(28, col + i) or 0 for i in range(3))
            if s is not None and sub != s:
                w.warn(f"game {n}: subtotals {sub} != score {s}")
        if n <= rr_games:
            rnd = (n - 1) // games_per_round + 1
            gs = grid_scores.get(frozenset((a, b)))
            if gs is None:
                w.warn(f"game {n}: {a} vs {b} not in the pool grid")
            elif (gs[a], gs[b]) != (sa, sb):
                w.warn(f"game {n}: grid {gs} != scoresheet {a} {sa} - {b} {sb}")
            w.game(a, b, sa, sb, stage="rr", round=f"RR{rnd}", seq=rnd, game_id=f"G{n}")
        else:
            k_po = next((i for i, (_, spec) in enumerate(playoff_rounds) if n in _range(spec)), None)
            if k_po is None:
                w.warn(f"game {n}: not in playoff_rounds")
                continue
            w.game(a, b, sa, sb, stage="playoff", round=playoff_rounds[k_po][0],
                   seq=(rr_games // games_per_round) + k_po + 1, game_id=f"G{n}")


def _range(spec: str) -> range:
    lo, _, hi = str(spec).partition("-")
    return range(int(lo), int(hi or lo) + 1)
