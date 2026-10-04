"""SMH tournaments (SMH Standard / Rookie 2023, SMH Invitational Cup 2024).

2023 workbooks ("RR Groups", "RR Scoring", "Bracket", "Individual <Subject> Stats"):
  * RR Groups: one column per group (seed number left of the team name) and a schedule block
    whose cells are seed pairings such as "1-2" (Google Sheets turned them into dates).
  * RR Scoring: final standings (rank = DE seed); Rookie also has the team's score in every
    round (RR1..RR7), which together with the schedule gives every game. Standard only has
    totals, so its round-robin games cannot be reconstructed.
  * Bracket: visual double-elimination bracket; seeds 9-16 start in the one-loss bracket.
  * Individual stats: "name [Team]" rows with gamesPlayed, tuh, buzzes, ppg, pts/Ntuh, npg,
    negs/Ntuh, accuracy (round robin only) -> integer counts via exact arithmetic.

2024 Invitational Cup ("Round Robin Groups", "Round Robin Scoring", "DE Seeding",
"Double Elimination Bracket", "Individual <Subject> Stats"): team codes a1..h6, score grids per
group, seed pairings in the "Tournament Schedule" tab, stats rows "f3 kevin q [f3 wayzata]"
with Points / Negs columns (round robin only).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, load_grids
from .g4_common import (Counts, Roster, derive_counts, find_grids, grid_pairs, read_bracket,
                        seed_pair, split_tag, stat_columns, write_bracket)


def tab_subject(title: str) -> str | None:
    t = re.sub(r"(?i)\b(individual|team|stats?|phase|league|playoff|round robin|double elimination)\b", " ", title)
    t = clean_name(t)
    if not t or re.fullmatch(r"(?i)rr|overall|overall indi\w*|all", t):
        return "overall"
    t = re.sub(r"(?i)^(indi\w*|individual)\s+", "", t)
    s = normalize_subject(t)
    if s:
        return s
    for full in ("biology", "chemistry", "physics", "math", "energy", "earth and space", "ess"):
        if full.startswith(t.lower()) or t.lower().startswith(full[:4]):
            return normalize_subject(full)
    return None


# ---- stats ---------------------------------------------------------------------------------
def read_stats(w: TournamentWriter, g: dict[str, Grid], tabs: list[str], who, *, scope: str,
               skip_players: str = r"^mysterious\b|^(?=.*\d)(?=.*[a-z])[a-z0-9]{8,}$",
               overall_filter: bool = False) -> dict[tuple[str, str, str], Counts]:
    """Read 'name [tag]' stat tabs. ``who(raw) -> (player, team) | None``. Rows of the same
    (player, team) are summed (some sources split a player over several name spellings).

    ``overall_filter``: drop subject-tab rows that are stale leftovers (seen in the League Cup
    playoff tabs): rows whose name is not in the overall tab of the same phase, whose games
    played differ from the overall row, or whose tossups heard per game (>6) are not a single
    subject's; exact duplicate rows are read once.
    """
    rx_skip = re.compile(skip_players, re.I)
    tot: dict[tuple[str, str, str], Counts] = {}
    ov_gp: dict[str, float] = {}
    if overall_filter:
        for tab in tabs:
            if tab_subject(tab) == "overall":
                x = g[tab]
                cols = stat_columns(x.row_texts(0))
                for r in range(1, x.nrows):
                    if x.text(r, 0) and x.num(r, cols["gp"]) is not None:
                        ov_gp[x.text(r, 0)] = x.num(r, cols["gp"])
    for tab in tabs:
        x = g[tab]
        subj = tab_subject(tab)
        if subj is None:
            raise ValueError(f"unknown subject tab {tab!r}")
        cols = stat_columns(x.row_texts(0))
        keep_rows: set[int] | None = None
        if overall_filter and subj != "overall":
            by_raw: dict[str, list[int]] = defaultdict(list)
            for r in range(1, x.nrows):
                if x.text(r, 0) and x.num(r, cols["gp"]) is not None:
                    by_raw[x.text(r, 0)].append(r)
            keep_rows = set()
            for raw, rs in by_raw.items():
                uniq: dict[tuple, int] = {}
                for r in rs:
                    uniq.setdefault(tuple(x.cell(r, c) for c in range(9)), r)
                ok = [r for r in uniq.values() if raw in ov_gp and x.num(r, cols["gp"]) == ov_gp[raw]]
                if len(ok) > 1:
                    ok = [r for r in ok if (x.num(r, cols["tuh"]) or 0) <= 6 * x.num(r, cols["gp"])]
                for r in uniq.values():
                    if r not in ok[:1]:
                        w.warn(f"{tab}: skipped stale row {raw!r} (gp {x.num(r, cols['gp']):g}, tuh {x.num(r, cols['tuh'])})")
                if len(ok) == 1:
                    keep_rows.add(ok[0])
                elif len(ok) > 1:
                    w.warn(f"{tab}: {raw!r} has {len(ok)} conflicting rows; none used")
        for r in range(1, x.nrows):
            raw = x.text(r, 0)
            if not raw or x.num(r, cols["gp"]) is None:
                continue
            if keep_rows is not None and r not in keep_rows:
                continue
            pt = who(raw)
            if pt is None:
                w.warn(f"{tab}: cannot place player {raw!r}")
                continue
            player, team = pt
            if rx_skip.search(player):
                continue
            get = lambda k: x.cell(r, cols[k]) if k in cols else None  # noqa: E731
            cn = derive_counts(get("gp"), get("tuh"), get("buzzes"), ppg=get("ppg"), npg=get("npg"),
                               points=get("points"), negs=get("negs"), acc=get("acc"),
                               rate_pts=get("rate_pts"), rate_pts_n=cols.get("rate_pts_n"),
                               rate_negs=get("rate_negs"), rate_negs_n=cols.get("rate_negs_n"))
            if cn.problem:
                w.warn(f"{tab} {raw!r}: {cn.problem}")
            key = (player, team, subj)
            if key in tot:
                a = tot[key]
                for f in ("gp", "tuh", "buzzes", "correct", "negs", "points", "zeros"):
                    va, vb = getattr(a, f), getattr(cn, f)
                    setattr(a, f, va + vb if va is not None and vb is not None else None)
            else:
                tot[key] = cn
    for (player, team, subj), cn in tot.items():
        w.player_stat(player, team, subj, scope=scope, gp=cn.gp, tuh=cn.tuh, correct=cn.correct,
                      zeros=cn.zeros, negs=cn.negs, points=cn.points)
    return tot


def stat_tabs(g: dict[str, Grid], prefix: str = "Individual") -> list[str]:
    return [k for k in g if k.startswith(prefix) and g[k].nrows > 1]


# ---- 2023 layout ---------------------------------------------------------------------------
def _standings(g: Grid) -> tuple[list[dict[str, Any]], dict[str, int]]:
    hdr = g.row_texts(0)
    ci = {h.lower(): i for i, h in enumerate(hdr) if h}
    name_c = next(i for h, i in ci.items() if h.startswith("team name"))
    rank_c = next((i for h, i in ci.items() if h.startswith("team rank")), name_c - 1)
    champ_c = next((i for h, i in ci.items() if h.startswith("champion")), None)
    grp_c = ci.get("group")
    rr_cols = {int(m.group(1)): i for h, i in ci.items() if (m := re.fullmatch(r"rr(\d+)", h))}
    rows = []
    for r in range(1, g.nrows):
        name = g.text(r, name_c)
        if not name or g.num(r, rank_c) is None:
            continue
        rows.append({"rank": int(g.num(r, rank_c)), "team": name,
                     "group": g.text(r, grp_c).lower() if grp_c is not None else "",
                     "champ": g.num(r, champ_c) if champ_c is not None else None,
                     "rounds": {k: g.num(r, c) for k, c in rr_cols.items()}})
    return rows, rr_cols


def _groups(g: Grid, group_names: set[str]) -> dict[str, list[str]]:
    """Group label cell, then team names below it with the seed number one column left."""
    out: dict[str, list[str]] = {}
    for r in range(g.nrows):
        for c in range(g.ncols):
            lab = g.text(r, c).lower()
            if lab in group_names and lab not in out:
                teams = []
                rr = r + 1
                while g.text(rr, c) and g.num(rr, c - 1) is not None:
                    teams.append(g.text(rr, c))
                    rr += 1
                out[lab] = teams
    return out


def _schedule(g: Grid, label: str = "RR") -> list[tuple[int, list[tuple[int, int]]]]:
    """Rows 'RRk' followed by seed-pair cells -> [(k, [(a, b), ...]), ...]."""
    out = []
    for r in range(g.nrows):
        for c in range(g.ncols):
            m = re.fullmatch(label + r"\s*(\d+)", g.text(r, c), re.I)
            if not m:
                continue
            pairs = []
            cc = c + 1
            while (p := seed_pair(g.cell(r, cc))) is not None:
                pairs.append(p)
                cc += 1
            if pairs:
                out.append((int(m.group(1)), pairs))
    return out


def parse_2023(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
               aliases: dict[str, str] | None = None, bracket_tab: str = "Bracket",
               bracket_cells: dict[str, str] | None = None, bracket_skip: list[str] | None = None,
               bracket_extra: list[str] | None = None, one_loss_seeds: list[int] | None = None,
               forfeit_zero: bool = True) -> None:
    g = load_grids(t.raw(results))
    stand, rr_cols = _standings(g["RR Scoring"])
    roster = Roster([s["team"] for s in stand], aliases)
    seeds = {s["rank"]: s["team"] for s in stand}
    by_team = {s["team"]: s for s in stand}

    # ---- round robin
    groups_raw = _groups(g["RR Groups"], {s["group"] for s in stand})
    sched = _schedule(g["RR Groups"])
    # games played per team (team stats tab): a team with fewer games than rounds and a 0 in
    # a round did not play that game (forfeit / no-show)
    gp_of: dict[str, float] = {}
    ts = next((g[k] for k in g if k.lower().startswith("team rr stats")), None)
    if ts is not None:
        tc = stat_columns(ts.row_texts(0))
        for r in range(1, ts.nrows):
            tm = roster.resolve(ts.text(r, 0), required=False)
            if tm and ts.num(r, tc.get("gp", 1)) is not None:
                gp_of[tm] = ts.num(r, tc.get("gp", 1))
    if rr_cols and sched:
        champ = defaultdict(float)
        for grp, members in groups_raw.items():
            teams = [roster.resolve(m, within=[s["team"] for s in stand if s["group"] == grp])
                     for m in members]
            for k, pairs in sched:
                for a, b in pairs:
                    ta, tb = teams[a - 1], teams[b - 1]
                    sa, sb = by_team[ta]["rounds"].get(k), by_team[tb]["rounds"].get(k)
                    if sa is None or sb is None:
                        w.warn(f"RR{k} {ta} vs {tb}: missing score")
                        continue
                    ff, note = False, ""
                    if forfeit_zero and sa == 0 and sb == 0:
                        ff, note = True, "0-0: not played"
                    for tm, sc in ((ta, sa), (tb, sb)):
                        n_rounds = sum(1 for v in by_team[tm]["rounds"].values() if v is not None)
                        if sc == 0 and tm in gp_of and gp_of[tm] < n_rounds:
                            ff, note = True, f"{tm} did not play (score 0; {gp_of[tm]:g} games played per team stats)"
                    w.game(ta, tb, sa, sb, stage="rr", round=f"RR{k}", seq=k,
                           game_id=f"rr{k}-{grp}-{a}{b}", forfeit=ff, notes=note)
                    if not ff:
                        champ[ta] += 2 if sa > sb else 1 if sa == sb else 0
                        champ[tb] += 2 if sb > sa else 1 if sa == sb else 0
        for s in stand:
            if s["champ"] is not None and champ.get(s["team"], 0) != s["champ"]:
                w.warn(f"standings check: {s['team']} championship points {s['champ']:g} "
                       f"!= {champ.get(s['team'], 0):g} from games")
    elif sched:
        # standings only: write the outcomes that every assignment consistent with the
        # championship points (2 win / 1 tie) agrees on, as result-only games
        n_det = n_all = 0
        for grp, members in groups_raw.items():
            names = [s["team"] for s in stand if s["group"] == grp]
            teams = [None if re.search(r"placeholder", m, re.I) else roster.resolve(m, within=names, required=False)
                     for m in members]
            games = []
            for k, pairs in sched:
                for a, b in pairs:
                    if a <= len(teams) and b <= len(teams) and teams[a - 1] and teams[b - 1]:
                        games.append((k, a, b, teams[a - 1], teams[b - 1]))
            target = {tm: by_team[tm]["champ"] for tm in teams if tm}
            real = games   # games against a placeholder slot were never played
            for tm in target:
                n = sum(1 for y in real if tm in y[3:])
                if tm in gp_of and gp_of[tm] != n:
                    w.warn(f"group {grp}: {tm} has {n} scheduled games but {gp_of[tm]:g} games played")
            sols = _outcomes(real, target)
            n_all += len(real)
            if not sols:
                w.warn(f"group {grp}: no outcome assignment matches the standings")
                continue
            for i, (k, a, b, ta, tb) in enumerate(real):
                vals = {sol[i] for sol in sols}
                if len(vals) == 1:
                    n_det += 1
                    w.game(ta, tb, stage="rr", round=f"RR{k}", seq=k, result=vals.pop(),
                           game_id=f"rr{k}-{grp}-{a}{b}",
                           notes=f"result deduced from the final standings ({len(sols)} consistent outcome sets agree); no score")
        w.warn(f"round-robin per-game scores are not in the source (standings only); "
               f"{n_det} of {n_all} results deduced from the standings")
    else:
        w.warn("round-robin per-game scores are not in the source (standings only)")

    # ---- bracket
    start = {seeds[s]: 1 for s in (one_loss_seeds or []) if s in seeds}
    games = read_bracket(g[bracket_tab], roster, seeds=seeds, cell_names=bracket_cells,
                         skip_cells=bracket_skip or [], extra=bracket_extra or [],
                         start_losses=start)
    write_bracket(w, games)

    # ---- stats (round robin)
    def who(raw: str):
        name, tag = split_tag(raw)
        team = roster.resolve(tag, required=False)
        return (name, team) if team else None

    read_stats(w, g, stat_tabs(g), who, scope="rr")


def _outcomes(games: list[tuple], target: dict[str, float]) -> list[tuple[str, ...]]:
    """All outcome vectors ('1' / '2' / 'T' per game) giving every team its target points."""
    teams = list(target)
    remaining = {t: sum(1 for g in games if t in g[3:]) for t in teams}
    pts = {t: 0.0 for t in teams}
    out: list[tuple[str, ...]] = []
    cur: list[str] = []

    def rec(i: int) -> None:
        if len(out) > 100000:
            return
        if i == len(games):
            if all(pts[t] == target[t] for t in teams):
                out.append(tuple(cur))
            return
        _, _, _, ta, tb = games[i]
        remaining[ta] -= 1
        remaining[tb] -= 1
        for res, pa, pb in (("1", 2, 0), ("2", 0, 2), ("T", 1, 1)):
            pts[ta] += pa
            pts[tb] += pb
            if all(pts[t] <= target[t] <= pts[t] + 2 * remaining[t] for t in (ta, tb)):
                cur.append(res)
                rec(i + 1)
                cur.pop()
            pts[ta] -= pa
            pts[tb] -= pb
        remaining[ta] += 1
        remaining[tb] += 1

    rec(0)
    return out


# ---- 2024 Invitational Cup -------------------------------------------------------------------
def _code_groups(g: Grid) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Cells 'a1'..'h6' with the team name to the right -> code -> name, group letter -> names."""
    codes: dict[str, str] = {}
    for r in range(g.nrows):
        for c in range(g.ncols):
            m = re.fullmatch(r"([a-z])(\d)", g.text(r, c).lower())
            if m and g.text(r, c + 1):
                codes[m.group(0)] = g.text(r, c + 1)
    groups: dict[str, list[str]] = defaultdict(list)
    for code in sorted(codes, key=lambda k: (k[0], int(k[1:]))):
        groups[code[0]].append(codes[code])
    return codes, groups


def parse_cup(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
              aliases: dict[str, str] | None = None, bracket_tab: str = "Double Elimination Bracket",
              bracket_cells: dict[str, str] | None = None, bracket_skip: list[str] | None = None,
              bracket_extra: list[str] | None = None, one_loss_seeds: list[int] | None = None,
              bracket_notes: dict[str, str] | None = None) -> None:
    g = load_grids(t.raw(results))
    codes, groups = _code_groups(g["Round Robin Groups"])
    roster = Roster(codes.values(), aliases)
    sd = g["DE Seeding"]
    seeds = {int(sd.num(r, 1)): roster.resolve(sd.text(r, 2)) for r in range(1, sd.nrows)
             if sd.num(r, 1) is not None and sd.text(r, 2)}

    # schedule: rows RRk with seed pairs (by group position)
    sched = _schedule(g["Tournament Schedule"])
    round_of: dict[frozenset, int] = {}
    for k, pairs in sched:
        for a, b in pairs:
            round_of[frozenset((a, b))] = k

    grids = find_grids(g["Round Robin Scoring"])
    if len(grids) != len(groups):
        w.warn(f"found {len(grids)} score grids for {len(groups)} groups")
    for sg in grids:
        # match the grid to its group by resolving the row labels within the group lists
        grp = None
        for letter, names in groups.items():
            if all(roster.resolve(lab, within=names, required=False) for lab in sg.labels):
                grp = letter
                break
        if grp is None:
            raise ValueError(f"grid at {sg.r},{sg.c}: no matching group for {sg.labels}")
        teams = [roster.resolve(lab, within=groups[grp]) for lab in sg.labels]
        if teams != groups[grp]:
            raise ValueError(f"group {grp}: grid order {teams} != group order {groups[grp]}")
        for i, j, a, b in grid_pairs(sg):
            k = round_of.get(frozenset((i + 1, j + 1)))
            w.game(teams[i], teams[j], num(a), num(b), stage="rr", round=f"RR{k}" if k else "",
                   seq=k or 0, game_id=f"rr-{grp}{i + 1}{j + 1}")

    start = {seeds[s]: 1 for s in (one_loss_seeds or []) if s in seeds}
    games = read_bracket(g[bracket_tab], roster, seeds=seeds, cell_names=bracket_cells,
                         skip_cells=bracket_skip or [], extra=bracket_extra or [],
                         start_losses=start)
    write_bracket(w, games, notes=bracket_notes)

    def who(raw: str):
        name, tag = split_tag(raw)
        m = re.match(r"([a-h]\d)\b", tag.lower())
        if not m or m.group(1) not in codes:
            return None
        name = re.sub(r"^[a-h]\d\s+", "", name, flags=re.I)
        return name, roster.resolve(codes[m.group(1)])

    read_stats(w, g, stat_tabs(g, "Individual"), who, scope="rr")
