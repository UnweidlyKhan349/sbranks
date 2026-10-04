""""Catstats Hub" workbooks: SMH League Cup 2025 and TJSBT 2025.

Stats tabs (one per phase x subject, e.g. "League Phase Individual Biology",
"Double Elimination Individual C"): rows "<team> first l [<team>]" or "first l [<team>]" with
gamesPlayed, tuh, buzzes, ppg, PP<n>TUH, npg, Total Negs, accuracy. Counts are recovered by
exact arithmetic (points = ppg*gp, negs = Total Negs, correct = (points + 4 negs) / 4) and
written per phase (scope rr / playoff); the build stage sums the two phases.

League Cup games come from the "Team Hub" tab (every team's league matches 1-6 and playoff
group matches 1-5 with opponent, for, against). TJSBT games come from the "RR Scores" grids
(rounds from "Schedule + Room Assignments") and the "DE Bracket" tab.
"""
from __future__ import annotations

import re
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, load_grids
from .g4_common import Roster, code_pair, find_grids, grid_pairs, read_bracket, split_tag, write_bracket
from .g4_smh import _schedule, read_stats, tab_subject


def _who(roster: Roster, codes: dict[str, str] | None = None):
    """'<Team> name [<Team>]' / 'e3 name [<Team>]' / 'name [<Team>]' -> (name, team)."""
    def who(raw: str):
        name, tag = split_tag(raw)
        team = roster.resolve(tag, required=False) if tag else None
        if team is None:
            return None
        # drop a leading team-name or code prefix from the player part
        low = name.lower()
        for cand in sorted({team, tag} | {k for k, v in roster.aliases.items() if v == team}, key=len, reverse=True):
            if cand and low.startswith(cand.lower() + " "):
                name = name[len(cand) + 1:]
                break
        else:
            name = re.sub(r"^[a-z]\d\s+", "", name, flags=re.I)
        return clean_name(name), team
    return who


# ---- SMH League Cup 2025 -------------------------------------------------------------------
def parse_league_cup(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
                     aliases: dict[str, str] | None = None) -> None:
    g = load_grids(t.raw(results))
    lt = g["League Phase Table"]
    codes = {lt.text(r, 2): lt.text(r, 3) for r in range(lt.nrows) if re.fullmatch(r"[a-z]-\d", lt.text(r, 2))}
    roster = Roster(codes.values(), aliases)
    for code, name in codes.items():
        w.team(name)

    # league matches: "League Phase k" blocks of row pairs, five games per row pair
    # (team at col c, score at col c+2)
    sb = g["League Scoreboard"]
    games: dict[tuple[str, frozenset], tuple[str, str, float, float]] = {}
    labels = [(r, int(m.group(1))) for r in range(sb.nrows)
              if (m := re.fullmatch(r"League Phase (\d+)", sb.text(r, 2)))]
    for bi, (r0, k) in enumerate(labels):
        r1 = labels[bi + 1][0] if bi + 1 < len(labels) else sb.nrows
        rows = [r for r in range(r0 + 1, r1) if sb.text(r, 2)]
        if len(rows) % 2:
            raise ValueError(f"League Phase {k}: odd number of team rows")
        for i in range(0, len(rows), 2):
            ra, rb = rows[i], rows[i + 1]
            for c in range(sb.ncols):
                if sb.text(ra, c) and sb.num(ra, c) is None and sb.num(ra, c + 2) is not None:
                    ta, tb = roster.resolve(sb.text(ra, c)), roster.resolve(sb.text(rb, c))
                    games[(f"League {k}", frozenset((ta, tb)))] = (ta, tb, sb.num(ra, c + 2), sb.num(rb, c + 2))

    # playoff groups: score grids + schedule of group positions
    pg = g["Playoff Groups"]
    pgroups: dict[str, list[str]] = {}
    for r in range(pg.nrows):
        for c in range(pg.ncols):
            lab = pg.text(r, c)
            if lab and lab.islower() and pg.num(r + 1, c - 1) == 1:
                names, rr = [], r + 1
                while pg.text(rr, c) and pg.num(rr, c - 1) is not None:
                    names.append(roster.resolve(pg.text(rr, c)))
                    rr += 1
                pgroups[lab] = names
    round_of = {frozenset(p): k for k, pairs in _schedule(g["Tournament Schedule"], "PO") for p in pairs}
    for sg in find_grids(g["Playoff Scoring"]):
        teams = [roster.resolve(x) for x in sg.labels]
        grp = next((k for k, v in pgroups.items() if v == teams), None)
        if grp is None:
            raise ValueError(f"playoff grid {sg.labels}: no matching group")
        for i, j, a, b in grid_pairs(sg):
            k = round_of.get(frozenset((i + 1, j + 1)))
            games[(f"Playoff {k}", frozenset((teams[i], teams[j])))] = (teams[i], teams[j], num(a), num(b))

    # cross-check against the per-team "Team Hub" summaries (they contain a few copy errors)
    hub = g["Team Hub"]
    for r in range(hub.nrows):
        for c in range(hub.ncols):
            code = hub.text(r, c)
            if not (re.fullmatch(r"[a-z]-\d", code) and code in codes):
                continue
            team = roster.resolve(codes[code])
            rr = r + 1
            while rr < hub.nrows and not re.fullmatch(r"[a-z]-\d", hub.text(rr, c)):
                m = re.fullmatch(r"(Match|Playoff)\s+(\d+)", hub.text(rr, c))
                opp_raw = hub.text(rr, c + 1)
                if m and opp_raw and opp_raw.lower() != "bye":
                    opp = roster.resolve(opp_raw)
                    key = (f"{'League' if m.group(1) == 'Match' else 'Playoff'} {m.group(2)}", frozenset((team, opp)))
                    f, a = hub.num(rr, c + 3), hub.num(rr, c + 4)
                    if key not in games:
                        w.warn(f"Team Hub {team} {key[0]} vs {opp}: game not in the scoreboard/grids")
                    else:
                        t1, t2, s1, s2 = games[key]
                        mine = (s1, s2) if t1 == team else (s2, s1)
                        if mine != (f, a):
                            w.warn(f"Team Hub {team} {key[0]} vs {opp}: {f}-{a}, scoreboard/grid has {mine[0]:g}-{mine[1]:g} (kept)")
                rr += 1

    for (rnd, _), (t1, t2, s1, s2) in sorted(games.items(), key=lambda kv: (kv[0][0].startswith("Playoff"), int(kv[0][0].split()[1]), kv[1][0])):
        k = int(rnd.split()[1])
        playoff = rnd.startswith("Playoff")
        ff = s1 == 0 and s2 == 0
        w.game(t1, t2, s1, s2, stage="playoff" if playoff else "rr", round=rnd,
               seq=(6 + k) if playoff else k, forfeit=ff,
               notes="0-0: not played (recorded as a tie in the standings)" if ff else "")

    who = _who(roster)
    league = [k for k in g if k.startswith("League Phase") and re.search(r"Individ|Overall Indi", k)]
    playoff = [k for k in g if k.startswith("Playoff Phase") and re.search(r"Individ|Overall Indi", k)]
    read_stats(w, g, league, who, scope="rr", overall_filter=True)
    read_stats(w, g, playoff, who, scope="playoff", overall_filter=True)


# ---- TJSBT 2025 ------------------------------------------------------------------------------
def parse_tjsbt(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
                stats: str = "stats.xlsx", rename: dict[str, str] | None = None,
                aliases: dict[str, str] | None = None, tab_subjects: dict[str, str] | None = None,
                bracket_cells: dict[str, str] | None = None,
                skip_games: dict[str, str] | None = None) -> None:
    rename = rename or {}
    g = load_grids(t.raw(results))
    grp = g["Round Robin Groups"]
    # group table: header 'Group A'.. in one row, seeds 1..6 below
    hdr = next(r for r in range(grp.nrows) if any(re.fullmatch(r"Group [A-Z]", grp.text(r, c)) for c in range(grp.ncols)))
    groups: dict[str, list[str]] = {}
    for c in range(grp.ncols):
        m = re.fullmatch(r"Group ([A-Z])", grp.text(hdr, c))
        if m:
            names = []
            r = hdr + 1
            while grp.text(r, c):
                names.append(rename.get(grp.text(r, c), grp.text(r, c)))
                r += 1
            groups[m.group(1)] = names
    roster = Roster([n for v in groups.values() for n in v if n.upper() != "BYE"],
                    {**{k: v for k, v in rename.items()}, **(aliases or {})})

    # schedule: 'A1 — A2' cells under 'RR k' headers
    sch = g["Schedule + Room Assignments"]
    round_of: dict[tuple[str, frozenset], int] = {}
    for r in range(sch.nrows):
        for c in range(sch.ncols):
            p = code_pair(sch.cell(r, c))
            if p:
                k = next((int(m.group(1)) for rr in range(r, -1, -1)
                          if (m := re.fullmatch(r"RR\s*(\d+)", sch.text(rr, c)))), None)
                letter = p[0][0]
                round_of[(letter, frozenset((int(p[0][1:]), int(p[1][1:]))))] = k

    grids = find_grids(g["RR Scores"])
    score_grids: dict[str, Any] = {}
    wl_grids: dict[str, Any] = {}
    for sg in grids:
        letter = None
        for L, names in groups.items():
            if len(names) == len(sg.labels) and all(
                    lab.upper() == "BYE" == n.upper() or roster.resolve(lab, within=[n], required=False)
                    for lab, n in zip(sg.labels, names)):
                letter = L
                break
        if letter is None:
            raise ValueError(f"grid at {sg.r},{sg.c} {sg.labels}: no group")
        vals = [num(v) for row in sg.cells for v in row if num(v) is not None]
        is_wl = vals and all(v in (0, 0.5, 1) for v in vals)
        (wl_grids if is_wl else score_grids).setdefault(letter, sg)
    for letter, sg in sorted(score_grids.items()):
        names = groups[letter]
        wl = wl_grids.get(letter)
        for i, j, a, b in grid_pairs(sg):
            ti, tj = roster.resolve(names[i]), roster.resolve(names[j])
            k = round_of.get((letter, frozenset((i + 1, j + 1))))
            sa, sb = num(a), num(b)
            gid = f"rr-{letter}{i + 1}{j + 1}"
            if skip_games and gid in skip_games:
                w.warn(f"{gid} {ti} vs {tj} skipped: {skip_games[gid]}")
                continue
            if sa is None or sb is None:
                w.warn(f"{gid} {ti} vs {tj}: missing score")
                continue
            if sa != int(sa) or sb != int(sb):
                # not played: the sheet fills both teams' average scores; the W/L grid has the result
                res = ""
                if wl is not None:
                    wi = num(wl.cells[i][j])
                    res = "1" if wi == 1 else "2" if wi == 0 else "T" if wi == 0.5 else ""
                w.game(ti, tj, stage="rr", round=f"RR{k}" if k else "", seq=k or 0, result=res,
                       forfeit=True, game_id=gid,
                       notes=f"not played; the sheet fills team averages ({sa:g}-{sb:g}) and credits the result")
                continue
            w.game(ti, tj, sa, sb, stage="rr", round=f"RR{k}" if k else "", seq=k or 0, game_id=gid)

    sd = g["DE Seeding"]
    games = read_bracket(g["DE Bracket"], roster, cell_names=bracket_cells)
    write_bracket(w, games, seq_base=10)

    gs = load_grids(t.raw(stats))
    who = _who(roster)
    subj_over = tab_subjects or {}
    rr_tabs = [k for k in gs if k.startswith("Round Robin Individual")]
    de_tabs = [k for k in gs if k.startswith("Double Elimination") and ("Indi" in k)] + \
              [k for k in subj_over if k in gs]
    _read_tabs(w, gs, rr_tabs, who, "rr", subj_over)
    _read_tabs(w, gs, de_tabs, who, "playoff", subj_over)


def _read_tabs(w, gs, tabs, who, scope, subj_over):
    # read_stats derives the subject from the tab title; rename the odd ones via a shallow copy
    renamed = {}
    order = []
    for k in tabs:
        if k in subj_over:
            title = f"Individual {subj_over[k]}"
            renamed[title] = gs[k]
            order.append(title)
        else:
            renamed[k] = gs[k]
            order.append(k)
    read_stats(w, renamed, order, who, scope=scope)
