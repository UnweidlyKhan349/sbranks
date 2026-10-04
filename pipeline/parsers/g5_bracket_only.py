"""Bracket-only results (Berkeley Science Bowl April 2023 'BSB DE Bracket').

The round-robin tabs of that workbook only hold #REF! errors, so the double-elimination
bracket is all that survives. See :func:`g5_common.bracket_games` for the layout rules
(columns of ``team | score`` cells, result-only games for unscored advancements).
"""
from __future__ import annotations

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import load_grids
from .g5_common import bracket_games


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
          tab: str = "DE Bracket", unscored_winners: dict | None = None,
          final_columns: int = 2) -> None:
    g = load_grids(t.raw(results))[tab]
    bracket_games(w, g, final_columns=final_columns, unscored_winners=unscored_winners,
                  skip_rx=r"^\[?bye\d*\]?$|^L\d+$|^\d+\s*→|→$|^BSB")
