"""DASONI 2022 (Standard / Competitive) and DASONI 2023 (Standard / Competitive).

2022 results workbook (shared by both divisions): "<Div> RR" lists each team's result (W/L/D)
and score in RR1..RR3, grouped by pool ("Braik Divison", ...); "<Div> RR Schedule" gives the
pairings per pool and round with abbreviated names; "<Div> DE Bracket" is a visual
double-elimination bracket (seeds 9-16 start in the loser's bracket).

2023 Standard: "Standard RR Results" lists every game per round (team, score, team, score);
"Standard DE" is the bracket (its final has no score or winner).
2023 Competitive: "Competitive RR Results" has each team's W/L and score per round, and
"Competitive RR Pairings" the pairings for four time slots (each team plays three of them;
'-' / 'NS' = no opponent). A team's n-th result belongs to its n-th scheduled slot; every
game is checked for complementary results. The DE tab only shows who advanced (no scores).

The stats workbooks ("Metrics Guide" template) list players by first name without a team
column, and the team tabs do not reconcile with the player rows, so player stats are not
extracted.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, load_grids
from .g4_common import Roster, a1, read_bracket, write_bracket


# ---- helpers -------------------------------------------------------------------------------
def _pools_2022(g: Grid) -> dict[str, list[dict[str, Any]]]:
    """'<X> Divison' blocks: team rows with (result, score) per RR column."""
    out: dict[str, list[dict[str, Any]]] = {}
    r = 0
    while r < g.nrows:
        title = g.text(r, 0)
        if re.search(r"divi?s(i)?on$", title, re.I) and g.text(r + 1, 0).lower() == "team":
            hdr = g.row_texts(r + 1)
            rcols = {int(m.group(1)): i for i, h in enumerate(hdr) if (m := re.fullmatch(r"RR(\d+)", h))}
            teams = []
            rr = r + 2
            while rr < g.nrows and g.text(rr, 0):
                teams.append({"team": g.text(rr, 0),
                              "res": {k: g.text(rr, c).upper() for k, c in rcols.items()},
                              "score": {k: g.num(rr, c + 1) for k, c in rcols.items()}})
                rr += 1
            out[title.lower().replace("divison", "division")] = teams
            r = rr
        r += 1
    return out


def _schedule_2022(g: Grid) -> dict[str, dict[int, list[tuple[str, str]]]]:
    """Pool blocks: title cell, then 'RRk (...)' rows; game rows have the teams in the two
    columns under 'Team #1' / 'Team #2'."""
    out: dict[str, dict[int, list[tuple[str, str]]]] = {}
    for r in range(g.nrows):
        for c in range(g.ncols):
            title = g.text(r, c)
            if not re.search(r"divi?s(i)?on$", title, re.I):
                continue
            key = title.lower().replace("divison", "division")
            rounds: dict[int, list[tuple[str, str]]] = {}
            rr = r + 1
            k = None
            while rr < g.nrows:
                t = g.text(rr, c)
                m = re.match(r"RR\s*(\d+)", t)
                if m:
                    k = int(m.group(1))
                    rounds[k] = []
                elif re.search(r"divi?s(i)?on$", t, re.I):
                    break
                elif k is not None and g.text(rr, c + 2) and g.text(rr, c + 3) \
                        and g.text(rr, c + 2).lower() != "team #1":
                    rounds[k].append((g.text(rr, c + 2), g.text(rr, c + 3)))
                elif k is not None and not any(g.text(rr, cc) for cc in range(c, c + 4)) \
                        and not any(g.text(rr + 1, cc) for cc in range(c, c + 4)):
                    break
                rr += 1
            out[key] = rounds
    return out


def _check_pair(w: TournamentWriter, label: str, ta: str, ra: str, sa: Any, tb: str, rb: str, sb: Any) -> bool:
    ok = ((ra, rb) in (("W", "L"), ("L", "W")) and sa is not None and sb is not None
          and (sa > sb) == (ra == "W")) or (ra == rb == "D" and sa == sb) or (ra == rb == "T" and sa == sb)
    if not ok:
        w.warn(f"{label} {ta} {ra} {sa} vs {tb} {rb} {sb}: results do not agree; game skipped")
    return ok


def _seeds_2022(g: Grid) -> dict[int, str]:
    pos = g.find_first(r"^Seeding$")
    out: dict[int, str] = {}
    if pos is None:
        return out
    r0 = pos[0] + 1
    hdr = g.row_texts(r0)
    sc = hdr.index("Seed")
    for r in range(r0 + 1, g.nrows):
        if g.text(r, 0) and g.num(r, sc) is not None:
            out[int(g.num(r, sc))] = g.text(r, 0)
    return out


def _progression(w: TournamentWriter, g: Grid, roster: Roster, specs: list[str], seq_base: int) -> None:
    """Result-only bracket games: 'Round|CELL_A|CELL_B|CELL_WINNER' (A1 refs)."""
    order: list[str] = []
    for spec in specs:
        rnd, ca, cb, cw = [x.strip() for x in spec.split("|")]
        if rnd not in order:
            order.append(rnd)
        ta, tb = roster.resolve(g.text(*a1(ca))), roster.resolve(g.text(*a1(cb)))
        tw = roster.resolve(g.text(*a1(cw)))
        if tw not in (ta, tb):
            raise ValueError(f"{spec}: winner {tw} is not one of {ta}, {tb}")
        w.game(ta, tb, stage="playoff", round=rnd, seq=seq_base + order.index(rnd),
               result="1" if tw == ta else "2", game_id=f"de-{ca}",
               notes=f"winner from the bracket ({cw}); no score recorded")


# ---- 2022 ----------------------------------------------------------------------------------
def parse_2022(t: Tournament, w: TournamentWriter, division: str, results: str = "results.xlsx",
               aliases: dict[str, str] | None = None, round_labels: dict | None = None,
               bracket_cells: dict[str, str] | None = None, one_loss_seeds: list[int] | None = None) -> None:
    g = load_grids(t.raw(results))
    rr = g[f"{division} RR"]
    pools = _pools_2022(rr)
    roster = Roster([x["team"] for v in pools.values() for x in v], aliases)
    sched = _schedule_2022(g[f"{division} RR Schedule"])
    by_team = {x["team"]: x for v in pools.values() for x in v}
    used: set[tuple[str, int]] = set()
    for pool, members in pools.items():
        names = [x["team"] for x in members]
        for k, pairs in sorted(sched.get(pool, {}).items()):
            for a, b in pairs:
                ta, tb = roster.resolve(a, within=names), roster.resolve(b, within=names)
                xa, xb = by_team[ta], by_team[tb]
                ra, rb, sa, sb = xa["res"].get(k), xb["res"].get(k), xa["score"].get(k), xb["score"].get(k)
                if not _check_pair(w, f"RR{k}", ta, ra, sa, tb, rb, sb):
                    continue
                for x in (ta, tb):
                    if (x, k) in used:
                        raise ValueError(f"{x} scheduled twice in RR{k}")
                    used.add((x, k))
                w.game(ta, tb, sa, sb, stage="rr", round=f"RR{k}", seq=k,
                       game_id=f"rr{k}-{re.sub(r'[^a-z]', '', pool)[:8]}-{len(used)}")
    for x in by_team:
        for k in by_team[x]["res"]:
            if by_team[x]["res"][k] and (x, k) not in used:
                w.warn(f"{x} RR{k} result {by_team[x]['res'][k]} {by_team[x]['score'][k]} has no scheduled opponent")

    seeds = {s: roster.resolve(n) for s, n in _seeds_2022(rr).items()}
    start = {seeds[s]: 1 for s in (one_loss_seeds or []) if s in seeds}
    games = read_bracket(g[f"{division} DE Bracket"], roster, cell_names=bracket_cells,
                         round_labels=round_labels, start_losses=start,
                         teams=list(seeds.values()) or None)
    write_bracket(w, games)


# ---- 2023 Standard -------------------------------------------------------------------------
def parse_2023_standard(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
                        aliases: dict[str, str] | None = None, round_labels: dict | None = None,
                        bracket_cells: dict[str, str] | None = None,
                        bracket_skip: list[str] | None = None) -> None:
    g = load_grids(t.raw(results))
    x = g["Standard RR Results"]
    # standings block: team name in a column right of the game lists, with W/L columns
    # the standings block is the right-most 'RR1' header; game lists are left of its name column
    hdr_r, hdr_c = max(x.find(r"^RR1$"), key=lambda rc: rc[1])
    name_c = hdr_c - 1
    stand = []
    for r in range(hdr_r + 1, x.nrows):
        if x.text(r, name_c):
            stand.append({"team": x.text(r, name_c), "rank": x.num(r, hdr_c + 8),
                          "points": x.num(r, hdr_c + 6)})
    roster = Roster([s["team"] for s in stand], aliases)
    pts = defaultdict(float)
    for r0, c0 in x.find(r"^RR(\d+)$"):
        if c0 >= name_c:
            continue
        k = int(x.text(r0, c0)[2:])
        r = r0 + 1
        while r < x.nrows and x.text(r, c0) and not re.fullmatch(r"RR\d+", x.text(r, c0)):
            ta, tb = roster.resolve(x.text(r, c0)), roster.resolve(x.text(r, c0 + 2))
            sa, sb = x.num(r, c0 + 1), x.num(r, c0 + 3)
            w.game(ta, tb, sa, sb, stage="rr", round=f"RR{k}", seq=k, game_id=f"rr{k}-{r}-{c0}")
            pts[ta] += 2 if sa > sb else 1 if sa == sb else 0
            pts[tb] += 2 if sb > sa else 1 if sa == sb else 0
            r += 1
    for s in stand:
        if s["points"] is not None and pts[roster.resolve(s["team"])] != s["points"]:
            w.warn(f"standings check: {s['team']} {s['points']:g} points vs {pts[s['team']]:g} from games")
    qualified = [roster.resolve(s["team"]) for s in stand if s["rank"] is not None]
    games = read_bracket(g["Standard DE"], roster, cell_names=bracket_cells, round_labels=round_labels,
                         teams=qualified, skip_cells=bracket_skip or [])
    write_bracket(w, games)
    w.warn("DE final (Interlake vs Enloe B) has no score or winner in the source; not recorded")


# ---- 2023 Competitive ----------------------------------------------------------------------
def parse_2023_competitive(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
                           aliases: dict[str, str] | None = None,
                           de_games: list[str] | None = None) -> None:
    g = load_grids(t.raw(results))
    x = g["Competitive RR Results"]
    hdr_r, hdr_c = next((r, c) for r, c in x.find(r"^RR1$"))
    name_c = hdr_c - 1
    rcols = {int(m.group(1)): c for c in range(x.ncols) if (m := re.fullmatch(r"RR(\d+)", x.text(hdr_r, c)))}
    res: dict[str, dict[int, tuple[str, float | None]]] = {}
    for r in range(hdr_r + 1, x.nrows):
        n = x.text(r, name_c)
        if n:
            res[n] = {k: (x.text(r, c).upper(), x.num(r, c + 1)) for k, c in rcols.items()}
    roster = Roster(res, aliases)
    no_show = {n for n, v in res.items() if all(s == 0 and rr == "L" for rr, s in v.values())}

    p = g["Competitive RR Pairings"]
    slots: list[list[tuple[str, str]]] = []
    for c in range(p.ncols):
        if re.search(r"\d+\s*-\s*\d+.*(PST|PT|ET)", p.text(1, c)):
            games = []
            r = 2
            while r < p.nrows and p.num(r, c - 1) is not None:
                games.append((p.text(r, c), p.text(r, c + 1)))
                r += 1
            slots.append(games)
    # each team's appearances in slot order
    appear: dict[str, list[tuple[int, int, str | None]]] = defaultdict(list)
    for si, games in enumerate(slots):
        for gi, (a, b) in enumerate(games):
            ta = roster.resolve(a, required=False) if a not in ("-", "") else None
            tb = roster.resolve(b, required=False) if b not in ("-", "", "NS") else None
            if ta:
                appear[ta].append((si, gi, tb))
            if tb:
                appear[tb].append((si, gi, ta))
    played: dict[tuple[int, int], dict[str, int]] = defaultdict(dict)
    for team, apps in appear.items():
        n_res = len(res[team])
        if team in no_show:
            continue
        if len(apps) != n_res:
            w.warn(f"{team}: {len(apps)} scheduled slots for {n_res} results; RR games not assigned")
            continue
        for k, (si, gi, opp) in enumerate(apps, start=1):
            played[(si, gi)][team] = k
            if opp is None:
                rr, sc = res[team][k]
                w.warn(f"{team} RR{k} ({rr} {sc}) had no opponent in slot {si + 1}; not recorded")
    for (si, gi), teams in sorted(played.items()):
        if len(teams) != 2:
            continue
        (ta, ka), (tb, kb) = sorted(teams.items(), key=lambda kv: kv[0])
        ra, sa = res[ta][ka]
        rb, sb = res[tb][kb]
        if not _check_pair(w, f"slot {si + 1}", ta, ra, sa, tb, rb, sb):
            continue
        w.game(ta, tb, sa, sb, stage="rr", round=f"slot {si + 1}", seq=si + 1,
               game_id=f"rr-s{si + 1}-{gi + 1}",
               notes=f"RR{ka} for {ta}, RR{kb} for {tb}" if ka != kb else "")
    if de_games:
        _progression(w, g["Competitive DE"], roster, de_games, seq_base=100)
