"""Shared helpers for the g2 (Prometheus / Ignis family) parsers.

* :func:`csv_grids`     load a tab-by-tab snapshot of a published Google Sheet
                        (see tools/g2_fetch_pubsheet.py) as ``{tab: Grid}``.
* :func:`bracket_games` read a Prometheus-style double-elimination bracket tab
                        (column pairs ``team | score`` per round, the two teams of a
                        game stacked in the same column with a room/division label
                        between them).
* :func:`rr_matrix`     read a Prometheus-style "each row shows a team's scores and
                        results" round-robin tab (one block per division).
* :func:`schedule_rows` read an Ignis in-person "Round | Room 1 | Room 2 ..." score sheet
                        (teams on one row, scores on the row(s) below).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schema import clean_name, num
from ..util.grid import Grid

IGNIS_CATS = "XMCEBP"   # fixed tossup category cycle of the Ignis / Olympus sets
CAT_SUBJECT = {"X": "other", "M": "math", "C": "chemistry", "E": "ess", "B": "biology",
               "P": "physics"}


def csv_grids(d: Path) -> dict[str, Grid]:
    man = json.loads((d / "manifest.json").read_text())
    out: dict[str, Grid] = {}
    for tab in man["tabs"]:
        with open(d / tab["csv"], newline="", encoding="utf-8") as fh:
            rows = [[(v if v.strip() != "" else None) for v in r] for r in csv.reader(fh)]
        while rows and all(v is None for v in rows[-1]):
            rows.pop()
        out[tab["name"]] = Grid(tab["name"], rows)
    return out


def alias(name: Any, aliases: dict[str, str] | None) -> str:
    n = clean_name(name)
    if aliases:
        return aliases.get(n, aliases.get(n.lower(), n))
    return n


# ---------------------------------------------------------------------------------------
@dataclass
class BGame:
    col: int
    round_label: str
    t1: str
    t2: str
    s1: float | None
    s2: float | None
    row1: int
    row2: int
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_SKIP = re.compile(r"^(bye|room\s*\d*|auditorium|webinar|tb:.*|\d+(st|nd|rd|th))$", re.I)


def bracket_games(g: Grid, header_row: int = 0, aliases: dict[str, str] | None = None,
                  ignore: set[str] | None = None) -> tuple[list[BGame], list[str]]:
    """Pair consecutive scored entries (``name`` cell with a numeric cell to its right) in
    each column of a bracket tab. A finals column with two numeric cells to the right of
    both entries yields two games (game 1 / game 2)."""
    warnings: list[str] = []
    games: list[BGame] = []
    ignore = {i.lower() for i in (ignore or set())}
    for c in range(g.ncols):
        label = g.text(header_row, c)
        if not label:
            continue
        entries = []
        for r in range(header_row + 1, g.nrows):
            name = g.text(r, c)
            if not name or num(name) is not None or _SKIP.match(name) or name.lower() in ignore:
                continue
            s = g.num(r, c + 1)
            if s is None:
                continue
            s2 = g.num(r, c + 2)
            entries.append((r, alias(name, aliases), s, s2))
        if len(entries) % 2:
            warnings.append(f"bracket column {c} ({label}): odd number of scored entries "
                            f"{[e[1] for e in entries]}")
        for a, b in zip(entries[0::2], entries[1::2]):
            if a[3] is not None and b[3] is not None:
                games.append(BGame(c, f"{label} G1", a[1], b[1], a[2], b[2], a[0], b[0]))
                games.append(BGame(c, f"{label} G2", a[1], b[1], a[3], b[3], a[0], b[0]))
            else:
                games.append(BGame(c, label, a[1], b[1], a[2], b[2], a[0], b[0]))
    # tied bracket games: note who advanced (a later column shows the team again)
    for gm in games:
        if gm.s1 is not None and gm.s1 == gm.s2:
            later = {g.text(r, c2) for c2 in range(gm.col + 2, g.ncols) for r in range(g.nrows)}
            adv = [t for t in (gm.t1, gm.t2) if t in {alias(x, aliases) for x in later}]
            if len(adv) == 1:
                gm.notes = (f"tied {gm.s1:g}-{gm.s2:g}; {adv[0]} advanced in the bracket "
                            f"(tiebreaker not recorded)")
    return games, warnings


# ---------------------------------------------------------------------------------------
@dataclass
class RRGame:
    division: str
    t1: str
    t2: str
    s1: float | None
    s2: float | None
    result: str
    forfeit: bool
    notes: str = ""


def _wl(v: str) -> str:
    v = v.strip().upper()
    return {"W": "W", "L": "L", "T": "T"}.get(v, "")


def rr_matrix(g: Grid, aliases: dict[str, str] | None = None
              ) -> tuple[list[RRGame], dict[str, dict[str, Any]], list[str]]:
    """Parse division blocks laid out as::

        <Division>
        Team | Opp1 |   | Opp2 |   | ... | W | T | L | ...
        TeamA|      |   | 120  | W | ...

    Returns (games, standings {team: {division, W, T, L, points}}, warnings).
    One game per pair; both cells must agree. 0-0 with a W/L is flagged as a forfeit.
    """
    warnings: list[str] = []
    games: list[RRGame] = []
    standings: dict[str, dict[str, Any]] = {}
    hdr_rows = [r for r, c in g.find(r"^Team$")]
    for hr in hdr_rows:
        tc = next(c for c in range(g.ncols) if g.text(hr, c) == "Team")
        # division name: nearest non-empty cell above in the team column
        div = ""
        for r in range(hr - 1, max(hr - 4, -1), -1):
            if g.text(r, tc):
                div = g.text(r, tc)
                break
        opp_cols: dict[int, str] = {}
        stat_cols: dict[str, int] = {}
        for c in range(tc + 1, g.ncols):
            h = g.text(hr, c)
            if not h:
                continue
            if h in ("W", "T", "L", "Points", "W/L Score", "Rank", "Average"):
                stat_cols.setdefault(h, c)
            elif not stat_cols:
                opp_cols[c] = h
        cells: dict[tuple[str, str], tuple[float | None, str]] = {}
        r = hr + 1
        while r < g.nrows and g.text(r, tc) and g.text(r, tc) != "Team":
            team = g.text(r, tc)
            if team.upper() != "BYE" and team.strip("- "):
                t = alias(team, aliases)
                st = {"division": div}
                for k, c in stat_cols.items():
                    st[k] = g.num(r, c)
                standings[t] = st
                for c, opp in opp_cols.items():
                    if opp.upper() == "BYE" or not opp.strip("- "):
                        continue
                    s = g.num(r, c)
                    res = _wl(g.text(r, c + 1))
                    if s is None and not res:
                        continue
                    cells[(t, alias(opp, aliases))] = (s, res)
            r += 1
        seen: set[frozenset[str]] = set()
        for (a, b), (sa, ra) in cells.items():
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)
            other = cells.get((b, a))
            if other is None:
                warnings.append(f"{div}: {a} vs {b} only reported on one side")
                sb, rb = None, {"W": "L", "L": "W", "T": "T"}.get(ra, "")
            else:
                sb, rb = other
            expect = {"W": "L", "L": "W", "T": "T"}.get(ra)
            if ra and rb and expect != rb:
                warnings.append(f"{div}: {a} vs {b} results disagree ({ra}/{rb})")
            result = {"W": "1", "L": "2", "T": "T"}.get(ra or {"W": "L", "L": "W", "T": "T"}.get(rb, ""), "")
            forfeit = False
            notes = ""
            if sa is None and sb is None and result in ("1", "2"):
                forfeit = True
                notes = "result reported without scores: forfeit"
            if sa is not None and sb is not None:
                implied = "1" if sa > sb else "2" if sb > sa else "T"
                if sa == 0 and sb == 0 and result in ("1", "2"):
                    forfeit = True
                    notes = "0-0 with a W/L in the source: forfeit"
                    sa = sb = None
                elif result and implied != result:
                    warnings.append(f"{div}: {a} {sa:g} - {sb:g} {b} but marked {ra}/{rb}")
                    notes = f"source marks result {ra}/{rb} despite score"
            games.append(RRGame(div, a, b, sa, sb, result, forfeit, notes))
    return games, standings, warnings


# ---------------------------------------------------------------------------------------
@dataclass
class SGame:
    round_label: str
    round_no: int | None
    room: int
    t1: str
    t2: str
    s1: float | None
    s2: float | None


def schedule_rows(g: Grid, round_col: int = 6, aliases: dict[str, str] | None = None,
                  codes: dict[str, str] | None = None) -> tuple[list[SGame], list[str], list[str]]:
    """Ignis in-person score sheet: a row with the round label in ``round_col`` followed by
    team pairs (Room 1 = cols round_col+1, round_col+2, ...), and score row(s) below it.
    A trailing single team before an empty cell is a bye. Returns (games, byes, warnings)."""
    games: list[SGame] = []
    byes: list[str] = []
    warnings: list[str] = []
    codes = codes or {}

    def team_at(r: int, c: int) -> str:
        v = g.text(r, c)
        v = codes.get(v, v)
        return alias(v, aliases)

    for r in range(g.nrows):
        lab = g.text(r, round_col)
        if not lab or lab.lower() in ("round", "#"):
            continue
        rn = num(lab)
        if rn is None and not re.match(r"final|semi|tiebreak|playoff|consol", lab, re.I):
            continue
        # teams on row r from round_col+1 until two consecutive blanks
        teams = []
        c = round_col + 1
        while c < g.ncols:
            v = g.text(r, c)
            if not v:
                if not g.text(r, c + 1):
                    break
                c += 1
                continue
            teams.append((c, team_at(r, c)))
            c += 1
        # score rows directly below (numeric under the team columns)
        score_rows = []
        rr = r + 1
        while rr < g.nrows and not g.text(rr, round_col) and any(
                g.num(rr, tc) is not None for tc, _ in teams):
            score_rows.append(rr)
            rr += 1
        if not score_rows:
            warnings.append(f"round {lab}: no score row")
            continue
        pairs = list(zip(teams[0::2], teams[1::2]))
        if len(teams) % 2:
            byes.append(teams[-1][1])
        for gi, sr in enumerate(score_rows):
            for room, ((c1, t1), (c2, t2)) in enumerate(pairs, start=1):
                s1, s2 = g.num(sr, c1), g.num(sr, c2)
                if s1 is None and s2 is None:
                    continue
                label = lab if rn is None else str(int(rn))
                if len(score_rows) > 1:
                    label = f"{label} G{gi + 1}"
                games.append(SGame(label, int(rn) if rn is not None else None, room,
                                   t1, t2, s1, s2))
    return games, byes, warnings
