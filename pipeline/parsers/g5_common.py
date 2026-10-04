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
                    max_row: int | None = None, second_score: bool = True) -> dict[int, list[BracketEntry]]:
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
            s2 = g.num(r, c + 2) if second_score else None
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


def bracket_games(w: TournamentWriter, g: Grid, *, labels: list[str] | None = None,
                  stage: str = "playoff", seq0: int = 0, final_columns: int = 1,
                  skip_rx: str = r"^\[?bye\d*\]?$|^L\d+$|^W\d+$|^\d+\s*→|→$|^Game \d+$",
                  name_map: dict[str, str] | None = None,
                  unscored_winners: dict[str, str] | None = None,
                  unscored_scores: dict[str, list[float]] | None = None,
                  third_place_rx: str = r"3rd place", champion_rx: str = r"champ|winner",
                  big: float = 1e90, second_score: bool = False) -> None:
    """Games of a visual bracket: each round is a column of ``team | score`` cells and
    consecutive entries of a column are one game.

    Columns are labelled with ``labels`` (left to right) when given, else DE1, DE2, ... and
    the last ``final_columns`` columns 'Final', 'Final 2'. Team cells without a score (the
    bracket advanced the team but no score was typed) form result-only games: the winner is
    the one of the two that appears again in a later column, or ``unscored_winners``
    {"A|B": winner}; ``unscored_scores`` {"A|B": [score A, score B]} supplies scores known
    from elsewhere. A pair separated by a cell matching ``third_place_rx`` is labelled
    '3rd Place'. Entries with |score| >= ``big`` are byes and are skipped.
    """
    nm = name_map or {}
    fix = lambda s: nm.get(s, s)  # noqa: E731
    cols = bracket_entries(g, skip_rx=skip_rx, second_score=second_score)
    for ents in cols.values():
        for e in ents:
            e.name = fix(e.name)
    teams = {e.name for ents in cols.values() for e in ents} | set(nm.values()) | set(w._teams)
    champ_cols = {c for c in range(g.ncols)
                  if any(re.match(r"^(champions?|winners?)\b", g.text(r, c), re.I) for r in range(2))}
    unscored: dict[int, list[tuple[int, str]]] = {}
    for r in range(g.nrows):
        for c in range(g.ncols):
            name = fix(g.text(r, c))
            if name in teams and g.num(r, c + 1) is None and g.num(r, c) is None:
                if c in champ_cols or re.search(champion_rx, g.text(r, c - 1) + " " + g.text(r - 1, c), re.I):
                    continue  # the champion's name, not a game
                if re.search(r"void", g.text(r, c + 1), re.I):
                    w.warn(f"bracket: voided game entry {name} (row {r})")
                    continue
                unscored.setdefault(c, []).append((r, name))
    all_cols = sorted(set(cols) | set(unscored))
    n = len(all_cols)

    def later(name: str, c: int) -> bool:
        return any(e.name == name for cc, ents in cols.items() if cc > c for e in ents) or \
            any(x == name for cc, lst in unscored.items() if cc > c for _, x in lst)

    def label(k: int, c: int, r0: int, r1: int) -> str:
        for rr in range(r0, r1 + 1):
            for cc in (c, c + 1):
                if re.search(third_place_rx, g.text(rr, cc), re.I):
                    return "3rd Place"
        if labels:
            return labels[k - 1] if k - 1 < len(labels) else f"R{k}"
        if k > n - final_columns:
            j = k - (n - final_columns)
            return "Final" if j == 1 else f"Final {j}"
        return f"DE{k}"

    for k, c in enumerate(all_cols, start=1):
        ents = [e for e in cols.get(c, []) if abs(e.scores[0]) < big]
        if len(ents) % 2:
            raise ValueError(f"bracket column {c}: odd scored entries {[(e.row, e.name) for e in ents]}")
        for a, b in zip(ents[0::2], ents[1::2]):
            w.game(a.name, b.name, a.scores[0], b.scores[0], stage=stage,
                   round=label(k, c, a.row, b.row), seq=seq0 + k)
        lst = unscored.get(c, [])
        if len(lst) % 2:
            w.warn(f"bracket column {c}: odd unscored entries {lst}")
            continue
        for (ra, a), (rb, b) in zip(lst[0::2], lst[1::2]):
            key, rkey = f"{a}|{b}", f"{b}|{a}"
            sc = (unscored_scores or {}).get(key) or \
                list(reversed((unscored_scores or {}).get(rkey) or [])) or None
            if sc:
                w.game(a, b, sc[0], sc[1], stage=stage, round=label(k, c, ra, rb), seq=seq0 + k,
                       notes="score not in the bracket sheet; from the source's scoreboard")
                continue
            winner = (unscored_winners or {}).get(key) or (unscored_winners or {}).get(rkey)
            if not winner:
                la, lb = later(a, c), later(b, c)
                if la != lb:
                    winner = a if la else b
            if winner not in (a, b):
                w.warn(f"bracket column {c}: unscored game {a} vs {b}, winner unknown")
                continue
            w.game(a, b, stage=stage, round=label(k, c, ra, rb), seq=seq0 + k,
                   result="1" if winner == a else "2",
                   notes="no score entered; winner from bracket advancement")
