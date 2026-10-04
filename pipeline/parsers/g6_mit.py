"""MIT Science Bowl Invitational results workbooks (2021-2025).

Layout family:
* ``Round Robin``: one block per division, row team vs column opponent filled with
  2 (row team won) / 1 (tie) / 0 (row team lost). No scores. 2021 uses
  ``SCHOOL | TEAM ID | vs. 1 ...``; 2022+ ``ID | Team Name | A1 A2 ...``.
* ``Wildcard`` (2024, 2025): same grid format for the teams that missed the DE bracket
  (stage ``consolation``), plus (2024) a single Wildcard Final.
* Double-elimination bracket tabs: visual layouts, read with :mod:`g6_common` bracket specs
  (anchors or explicit cell-referenced games) given in parser_options.

The round-robin grids do not say which round each game was played in, so RR games carry no
round label (seq 1); bracket games get seq 10 + DE round number.
"""
from __future__ import annotations

from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import load_grids
from .g6_common import (BracketSpec, Roster, bracket_games, check_labels, code_grid_blocks,
                        code_pairs, de_warnings, emit_games)


def _rr(w: TournamentWriter, g, roster: Roster | None, stage: str, seq: int, prefix: str,
        totals_col: str = "Total") -> list[str]:
    names = []
    for b in code_grid_blocks(g):
        teams = [roster.resolve(t) if roster else t for t in b.teams]
        names.extend(teams)
        for t in teams:
            w.team(t)
        pts = {t: 0.0 for t in teams}
        for i, j, res, star, note in code_pairs(b, w):
            w.game(teams[i], teams[j], stage=stage, round="", seq=seq, result=res, forfeit=star,
                   notes=(f"{b.title}; " + note).strip("; ") if note else b.title,
                   game_id=f"{prefix}{len(w.rows['games']) + 1}")
            if star:  # starred (forfeited) games are not counted in the sheet's totals
                continue
            pts[teams[i]] += 2 if res == "1" else 1 if res == "T" else 0
            pts[teams[j]] += 2 if res == "2" else 1 if res == "T" else 0
        _check_totals(w, g, b, teams, pts)
    return names


def _check_totals(w, g, b, teams, pts) -> None:
    """Compare computed 2/1/0 points with the sheet's TOTAL column (cross-check)."""
    for hr, hc in g.find(r"^(Team Name|SCHOOL)$"):
        if g.text(hr, hc) and g.text(hr + 1, hc) == b.teams[0]:
            tc = next((c for c in range(hc, g.ncols) if g.text(hr, c).lower() == "total"), None)
            if tc is None:
                return
            for k, t in enumerate(b.teams):
                v = g.num(hr + 1 + k, tc)
                if v is not None and abs(v - pts[teams[k]]) > 1e-9:
                    w.warn(f"{b.title}: {t} total {v} != computed {pts[teams[k]]}")
            return


def parse(t: Tournament, w: TournamentWriter, rr_tab: str = "Round Robin",
          wildcard_tab: str | None = None, wildcard_seq: int = 11,
          brackets: list[dict[str, Any]] | None = None, aliases: dict[str, str] | None = None,
          label_check: bool = False, max_losses: int = 2) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    main = _rr(w, grids[rr_tab], None, "rr", 1, "rr")
    roster = Roster(main, aliases)
    if wildcard_tab:
        _rr(w, grids[wildcard_tab], roster, "consolation", wildcard_seq, "wc")

    de_games, all_games, tabs = [], [], []
    for bd in brackets or []:
        spec = BracketSpec.from_opts(bd)
        games = bracket_games(grids[spec.tab], spec, roster, w)
        emit_games(w, games, stage=spec.stage)
        all_games.extend(games)
        tabs.append(spec.tab)
        if spec.stage == "playoff":
            de_games.extend(games)
    if label_check:  # 'Winner of W5: X' / 'One-loss W1: Y' labels vs reconstructed games
        for tab in dict.fromkeys(tabs):
            check_labels(all_games, grids[tab], roster, w)
    if de_games:
        de_warnings(w, de_games, max_losses)
