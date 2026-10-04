"""Shared helpers for the g5 group parsers (big in-person invitationals).

* :func:`pool_grid_games` - round-robin score grids where the row is the team and the
  column is the opponent (one game per pair, both cells checked).
* :func:`bracket_column_games` - visual bracket sheets where each round is a column of
  ``team | score`` cells; consecutive entries in a column are the two sides of one game.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid

BYE_RX = re.compile(r"^\[?\s*bye\s*\]?$", re.I)


def is_bye(name: str) -> bool:
    return bool(BYE_RX.match(clean_name(name))) or clean_name(name) == ""


@dataclass
class PairResult:
    team1: str
    team2: str
    score1: float | None
    score2: float | None
    result: str = ""
    notes: str = ""


def pool_grid_games(g: Grid, header_rows: list[int], *, name_col: int = 1, first_col: int = 2,
                    step: int = 2, wl_offset: int | None = 1, w: TournamentWriter | None = None,
                    stop_rx: str = r"^$") -> list[tuple[str, list[PairResult]]]:
    """Read pool blocks of a row-vs-column score grid.

    ``header_rows`` are the rows holding the pool name (col 0) and opponent names; the team
    rows follow until a blank row. Team i's score against team j is in row i, column
    ``first_col + step*j`` (opponent order == row order). Returns [(pool, [PairResult])].
    """
    out = []
    for hr in header_rows:
        pool = g.text(hr, 0)
        rows = []
        r = hr + 1
        while r < g.nrows and g.text(r, name_col) and not re.match(stop_rx, g.text(r, name_col)):
            rows.append(r)
            r += 1
        names = [g.text(r, name_col) for r in rows]
        pairs = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if is_bye(names[i]) or is_bye(names[j]):
                    continue
                s_ij = g.num(rows[i], first_col + step * j)
                s_ji = g.num(rows[j], first_col + step * i)
                if s_ij is None and s_ji is None:
                    if w:
                        w.warn(f"{pool}: no score for {names[i]} vs {names[j]}")
                    continue
                if (s_ij is None) != (s_ji is None):
                    if w:
                        w.warn(f"{pool}: one-sided score {names[i]} {s_ij} vs {names[j]} {s_ji}")
                    continue
                res = ""
                if wl_offset is not None:
                    a = g.text(rows[i], first_col + step * j + wl_offset).upper()[:1]
                    b = g.text(rows[j], first_col + step * i + wl_offset).upper()[:1]
                    exp = "W" if s_ij > s_ji else "L" if s_ij < s_ji else "T"
                    if a and a != exp and w:
                        w.warn(f"{pool}: {names[i]} {s_ij}-{s_ji} {names[j]} marked {a}")
                    if b and b != {"W": "L", "L": "W", "T": "T"}[exp] and w:
                        w.warn(f"{pool}: {names[j]} {s_ji}-{s_ij} {names[i]} marked {b}")
                pairs.append(PairResult(names[i], names[j], s_ij, s_ji, res))
        out.append((pool, pairs))
    return out


@dataclass
class BracketEntry:
    row: int
    col: int
    name: str
    scores: list[float]


def bracket_entries(g: Grid, *, skip_rx: str = r"^$", min_row: int = 0,
                    max_row: int | None = None) -> dict[int, list[BracketEntry]]:
    """Find ``name | score [| score2]`` cells, grouped by column (left to right)."""
    skip = re.compile(skip_rx, re.I)
    cols: dict[int, list[BracketEntry]] = {}
    for r in range(min_row, g.nrows if max_row is None else min(max_row, g.nrows)):
        for c in range(g.ncols):
            v = g.cell(r, c)
            if v is None or isinstance(v, (int, float)):
                continue
            name = clean_name(v)
            if not name or num(name) is not None or skip.search(name):
                continue
            s = g.num(r, c + 1)
            if s is None:
                continue
            scores = [s]
            s2 = g.num(r, c + 2)
            if s2 is not None and not g.text(r, c + 3):
                scores.append(s2)
            cols.setdefault(c, []).append(BracketEntry(r, c, name, scores))
    return dict(sorted(cols.items()))


def bracket_column_games(g: Grid, *, skip_rx: str = r"^\[?bye\]?$|^\[select",
                         min_row: int = 0, max_row: int | None = None,
                         name_map: Callable[[str], str] | None = None,
                         max_gap: int | None = None) -> list[tuple[int, list[tuple[BracketEntry, BracketEntry]]]]:
    """Pair consecutive entries in each bracket column. Returns [(round_index, pairs)]."""
    out = []
    for k, (c, ents) in enumerate(bracket_entries(g, skip_rx=skip_rx, min_row=min_row,
                                                   max_row=max_row).items(), start=1):
        if len(ents) % 2:
            raise ValueError(f"bracket column {c}: odd number of entries "
                             f"{[(e.row, e.name) for e in ents]}")
        pairs = []
        for a, b in zip(ents[0::2], ents[1::2]):
            if max_gap is not None and b.row - a.row > max_gap:
                raise ValueError(f"bracket column {c}: entries {a.row} {a.name} / {b.row} {b.name} too far apart")
            if name_map:
                a.name, b.name = name_map(a.name), name_map(b.name)
            pairs.append((a, b))
        out.append((k, pairs))
    return out


def schedule_rounds(g: Grid, *, first_row: int = 2, round_col: int = 0, first_col: int = 1,
                    width: int = 3, n_pools: int | None = None,
                    round_rx: str = r"round\s*(\d+)") -> dict[frozenset, int]:
    """Map {frozenset(team1, team2): round} from a 'Round k | T1 | T2 | Room | T1 | T2 | ...'
    schedule (stops at the first blank row)."""
    rx = re.compile(round_rx, re.I)
    out: dict[frozenset, int] = {}
    rnd = None
    for r in range(first_row, g.nrows):
        texts = g.row_texts(r)
        if not any(texts):
            break
        m = rx.search(g.text(r, round_col))
        if m:
            rnd = int(m.group(1))
        c = first_col
        p = 0
        while c + 1 < g.ncols and (n_pools is None or p < n_pools):
            a, b = g.text(r, c), g.text(r, c + 1)
            if a and b and not is_bye(a) and not is_bye(b) and rnd is not None:
                out[frozenset((a, b))] = rnd
            c += width
            p += 1
    return out
