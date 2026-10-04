"""MOSFET (UW-Madison online invitational) and the Collierville Invitational.

Two layouts:

``parse_2024`` (MOSFET Advanced/Regular 2024)
    * ``Group Assignments``: one block per division; per team and round (RR1-RR3) a W/L/T
      letter and the team's own score.
    * ``Round Robin Pairings``: per division and round, the two games (room, team #1, team #2).
      Games = pairings joined with each side's score from Group Assignments.
    * ``Double Elimination Bracket``: visual DE bracket with room labels (``Alm-1``) between
      the two teams; winners only.

``parse_stages`` (MOSFET 2025, Collierville 2025: "Schedule and Info" template)
    * ``RR Stage 1/2 Groups``: 4-team score matrices (a ``/`` cell marks the corner; the row
      team's points vs the column opponent) + a "Round Pairings" table mapping
      Team k / Team l to Round N (one table for all groups, or one per group).
    * ``Playoff Bracket``: single elimination, ``Rm N`` / ``Room N`` labels between the two
      teams, each team's score in the cell to its right.
"""
from __future__ import annotations

import re
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, load_grids
from .g6_common import (BracketSpec, Roster, bracket_games, de_warnings, emit_games,
                        score_matrix_pairs)


# ---------------------------------------------------------------------------------------
# 2024
def _group_assignments(g: Grid) -> dict[str, dict[str, Any]]:
    """team -> {division, rounds: {1: (wlt, score)}} from the Group Assignments tab."""
    out: dict[str, dict[str, Any]] = {}
    div = ""
    rcols: dict[int, int] = {}
    for r in range(g.nrows):
        t0 = g.text(r, 0)
        if t0.endswith("Division"):
            div = t0
            continue
        if t0 == "Team":
            rcols = {int(m.group(1)): c for c in range(g.ncols)
                     if (m := re.match(r"^RR(\d+)$", g.text(r, c)))}
            continue
        if not t0 or not rcols or t0 == "--":
            continue
        out[t0] = {"division": div, "rounds": {k: (g.text(r, c), g.cell(r, c + 1)) for k, c in rcols.items()}}
    return out


def _pairings(g: Grid) -> list[tuple[int, str, str, str]]:
    """[(round, room, team1, team2)] from the Round Robin Pairings tab."""
    out = []
    for r, c in g.find(r"^RR(\d+)\b"):
        rnd = int(re.match(r"^RR(\d+)", g.text(r, c)).group(1))
        rr = r + 1
        if g.text(rr, c + 1) == "Team #1":
            rr += 1
        while rr < g.nrows and g.text(rr, c) and not g.text(rr, c).startswith("RR"):
            out.append((rnd, g.text(rr, c), g.text(rr, c + 1), g.text(rr, c + 2)))
            rr += 1
    return out


def parse_2024(t: Tournament, w: TournamentWriter, bracket: dict[str, Any] | None = None,
               aliases: dict[str, str] | None = None) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    ga = _group_assignments(grids["Group Assignments"])
    roster = Roster(ga, aliases)
    for name in ga:
        w.team(name)
    seen = set()
    for rnd, room, a, b in _pairings(grids["Round Robin Pairings"]):
        if a in ("--", "") or b in ("--", ""):
            continue  # bye
        ta, tb = roster.resolve(a), roster.resolve(b)
        (ra, sa), (rb, sb) = ga[ta]["rounds"][rnd], ga[tb]["rounds"][rnd]
        key = (rnd, frozenset((ta, tb)))
        if key in seen:
            continue
        seen.add(key)
        sa_n, sb_n = num(sa), num(sb)
        res = {"W": "1", "L": "2", "T": "T"}.get(ra, "")
        exp_b = {"W": "L", "L": "W", "T": "T"}.get(ra)
        if exp_b != rb:
            w.warn(f"RR{rnd} {ta} ({ra}) vs {tb} ({rb}): W/L letters disagree")
        if sa_n is not None and sb_n is not None:
            by_score = "1" if sa_n > sb_n else "2" if sb_n > sa_n else "T"
            if by_score != res:
                w.warn(f"RR{rnd} {ta} {sa_n} vs {tb} {sb_n}: score disagrees with {ra}/{rb}")
        else:
            sa_n = sb_n = None
        w.game(ta, tb, sa_n, sb_n, stage="rr", round=f"RR{rnd}", seq=rnd, result=res,
               notes=f"{ga[ta]['division']}, room {room}", game_id=f"RR{rnd}-{room}")
    # every team-round with a W/L must be accounted for (byes have no opponent)
    for name, d in ga.items():
        for rnd, (res, score) in d["rounds"].items():
            if res and num(score) is not None and not any(k[0] == rnd and name in k[1] for k in seen):
                w.warn(f"{name} RR{rnd}: result {res} but no pairing found")
    if bracket:
        spec = BracketSpec.from_opts(bracket)
        games = bracket_games(grids[spec.tab], spec, roster, w)
        emit_games(w, games, stage="playoff")
        de_warnings(w, games)


# ---------------------------------------------------------------------------------------
# 2025 "Schedule and Info" template
def _matrices(g: Grid) -> list[dict[str, Any]]:
    """Each '/' corner cell -> {group, teams (row names), cols (header names), scores}."""
    out = []
    for r, c in g.find(r"^/$"):
        # the corner '/' has a team name to its right and below (diagonal '/' cells do not)
        right, below = g.text(r, c + 1), g.text(r + 1, c)
        if not right or num(right) is not None or not below or num(below) is not None or below == "/":
            continue
        heads = []
        cc = c + 1
        while cc < g.ncols and g.text(r, cc) and g.text(r, cc).lower() not in ("totals", "total"):
            heads.append(g.text(r, cc))
            cc += 1
        rows = []
        rr = r + 1
        while rr < g.nrows and g.text(rr, c) and len(rows) < len(heads):
            rows.append(rr)
            rr += 1
        group = g.text(r - 1, c) or g.text(r - 1, c - 1)
        teams = [g.text(x, c) for x in rows]
        out.append({"group": group, "teams": teams, "heads": heads,
                    "cell": (lambda i, j, rows=rows, c=c: g.cell(rows[i], c + 1 + j)),
                    "slots": [g.text(x, c - 1) for x in rows], "where": f"{g.title}"})
    return out


def _round_table(g: Grid) -> dict[str | None, dict[frozenset, str]]:
    """Round Pairings: {group or None: {frozenset({'Team 1','Team 2'}): 'Round 1'}}."""
    out: dict[str | None, dict[frozenset, str]] = {}
    acols: list[tuple[int, int]] = []    # (row of [A] header, col)
    for r, c in g.find(r"^\[A\]$"):
        acols.append((r, c))
    for r, c in g.find(r"^Round \d+$"):
        hdr = [(hr, ac) for hr, ac in acols if hr < r]
        if not hdr:
            continue
        hr = max(h for h, _ in hdr)
        for _, ac in [x for x in hdr if x[0] == hr]:
            a, b = g.text(r, ac), g.text(r, ac + 1)
            if not (re.match(r"^Team \d$", a) and re.match(r"^Team \d$", b)):
                continue
            # group name: nearest non-empty cell left of/at ac in the row above [A]
            # ('Apatite Room 1' -> Apatite; '[Division Name] - Room 1' -> all groups)
            grp = None
            for gc in range(ac, -1, -1):
                v = g.text(hr - 1, gc)
                if v:
                    grp = None if v.startswith("[") else re.sub(r"\s+Room \d+$", "", v)
                    break
            out.setdefault(grp, {})[frozenset((a, b))] = g.text(r, c)
    return out


def parse_stages(t: Tournament, w: TournamentWriter, stage_tabs: list[str],
                 bracket: dict[str, Any] | None = None, aliases: dict[str, str] | None = None,
                 drop_re: str = r"^- \(|^DROPPED$", strip_re: str = r"\s*\(moved.*\)$",
                 forfeit_teams: list[str] | None = None, teams_tab: str | None = None) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    roster = Roster((), aliases)
    forfeit_teams = set(forfeit_teams or [])
    rx_drop = re.compile(drop_re)
    clean = lambda s: re.sub(strip_re, "", clean_name(s))  # noqa: E731

    if teams_tab:
        for r in range(1, grids[teams_tab].nrows):
            n = grids[teams_tab].text(r, 0)
            if n:
                w.team(roster.add(n))

    # canonical names: matrix row labels, in order
    mats = []
    for tab in stage_tabs:
        for m in _matrices(grids[tab]):
            m["tab"] = tab
            mats.append(m)
            for n in m["teams"]:
                n = clean(n)
                if n and not rx_drop.search(n):
                    try:
                        roster.resolve(n)
                    except KeyError:
                        roster.add(n)

    seq_of: dict[str, int] = {}
    for tab in stage_tabs:
        tbl = _round_table(grids[tab])
        for m in [x for x in mats if x["tab"] == tab]:
            slot_rounds = tbl.get(m["group"]) or tbl.get(None) or {}
            teams = [clean(n) for n in m["teams"]]
            canon = [None if (not n or rx_drop.search(n)) else roster.resolve(n) for n in teams]
            heads = [None if rx_drop.search(clean(h)) else roster.resolve(clean(h)) for h in m["heads"]]
            if heads != canon:
                w.warn(f"{tab} {m['group']}: header order {heads} != row order {canon}")
            for i, j, si, sj in score_matrix_pairs(teams, m["cell"], w, f"{tab} {m['group']}"):
                a, b = canon[i], canon[j]
                if a is None or b is None:
                    continue
                rnd = slot_rounds.get(frozenset((m["slots"][i], m["slots"][j])), "")
                seq = int(rnd.split()[-1]) if rnd else 0
                if rnd:
                    seq_of[rnd] = seq
                note = f"{m['group']}"
                if a in forfeit_teams or b in forfeit_teams:
                    gone = a if a in forfeit_teams else b
                    note += f"; {gone} withdrew (source shows {si:g}-{sj:g})"
                    w.game(a, b, stage="rr", round=rnd, seq=seq or 1,
                           result="2" if a == gone else "1", forfeit=True, notes=note)
                    continue
                w.game(a, b, si, sj, stage="rr", round=rnd, seq=seq or 1, notes=note)

    if bracket:
        spec = BracketSpec.from_opts(bracket)
        games = bracket_games(grids[spec.tab], spec, roster, w)
        emit_games(w, games, stage="playoff")
        de_warnings(w, [gm for gm in games if "3rd" not in gm.round], max_losses=1)
