"""Prometheus Science "Ignis" / "Olympus" tournaments (prometheus.science), 2022-23.

All of them embed two published Google Sheets (results + statistics) in the
prometheus.science results/statistics pages; the parsers read the ``pub?output=xlsx``
snapshots ``results_sheet.xlsx`` / ``stats_sheet.xlsx``.

Ignis/Olympus sets: 24 tossups per game in a fixed category cycle X-Risk, Math, Chemistry,
Earth & Space, Biology, Physics (X-Risk -> subject "other"; there is no Energy category).
Scoring: tossup 4, bonus 10, an interrupt penalty (-4 in the stats) gives the opponent 4
and costs the negging team nothing on the scoreboard.

``parse_inperson`` (Foothill, LASA, Middleton, Shen)
    results: "Main"/"Round Robin" score sheet (round row: team pairs per room, score row
    below) + optional "Double Elimination" bracket tab.
    stats: "Stats" (player totals), "Full" (per round block of 30 rows: per team bonus and
    running score for each question), "Sorted" (per player, per question 4 / -4 marks, same
    30-row blocks; bottom rows = totals incl. GP and TUH).

``parse_online`` (Ignis Virtual West / East, Olympus)
    results: "Round Robin" division matrices, "RR Schedule", "Double Elimination" bracket.
    stats: "Raw" buzz log (game, team, buzzer's Google id, score 14/4/0/-4, question,
    category), "Games" (round numbers; West/East only), "Users" (Google id -> full name),
    "Full" (player totals, first names only).

team_game_subjects: tossup_points = 4 * correct tossups + 4 * interrupt penalties by the
opponent in that category, bonus_points = 10 * bonuses, points = tossup + bonus; the
subject points of a team sum to its final score.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, header_index, load_grids
from .g2_common import (CAT_SUBJECT, IGNIS_CATS, alias, bracket_games, rr_matrix,
                        schedule_rows)

STAT_SUBJ = [("X", "other"), ("M", "math"), ("C", "chemistry"), ("E", "ess"),
             ("B", "biology"), ("P", "physics")]


def _q_row(block: int, q: int) -> int:
    """Row of question q (1..24) of 30-row block ``block`` (Full / Sorted / All tabs)."""
    return 30 * block + 3 + (q - 1) + (1 if q > 12 else 0)


def _cat(q: int) -> str:
    return IGNIS_CATS[(q - 1) % 6]


def _add_games(w: TournamentWriter, games: list[dict[str, Any]]) -> None:
    for gm in games:
        gm["gid"] = w.game(gm["t1"], gm["t2"], gm.get("s1"), gm.get("s2"), stage=gm["stage"],
                           round=gm["round"], seq=gm["seq"], result=gm.get("result", ""),
                           forfeit=gm.get("forfeit", False), notes=gm.get("notes", ""))


def _check_records(w: TournamentWriter, games: list[dict[str, Any]],
                   records: dict[str, tuple[float | None, float | None]], what: str,
                   stages: tuple[str, ...] | None = None) -> None:
    rec: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for gm in games:
        if stages and gm["stage"] not in stages:
            continue
        s1, s2 = gm.get("s1"), gm.get("s2")
        res = gm.get("result") or ("1" if s1 > s2 else "2" if s2 > s1 else "T")
        if res == "1":
            rec[gm["t1"]][0] += 1
            rec[gm["t2"]][1] += 1
        elif res == "2":
            rec[gm["t2"]][0] += 1
            rec[gm["t1"]][1] += 1
    for team, (wins, losses) in records.items():
        got = rec.get(team, [0, 0])
        if wins is not None and (got[0], got[1]) != (wins, losses):
            w.warn(f"{what}: {team} source W-L {wins:g}-{losses:g}, parsed {got[0]}-{got[1]}")


# =======================================================================================
# In-person Ignis
# =======================================================================================
def _stats_blocks(full: Grid) -> list[dict[str, Any]]:
    """Per 30-row block of the 'Full' tab: list of games (team cols, final scores)."""
    out = []
    for b in range((full.nrows + 29) // 30):
        cols = [c for c in range(full.ncols) if full.text(30 * b + 1, c) == "Bonus"]
        teams = [(full.text(30 * b, c), c) for c in cols]
        games = []
        for (ta, ca), (tb, cb) in zip(teams[0::2], teams[1::2]):
            fa, fb = full.num(_q_row(b, 24), ca + 1), full.num(_q_row(b, 24), cb + 1)
            if not ta or not tb or (fa is None and fb is None):
                continue
            games.append({"block": b, "teams": [(ta, ca), (tb, cb)], "final": (fa, fb)})
        out.append(games)
    return out


def _sorted_players(srt: Grid) -> tuple[list[tuple[int, str]], dict[str, dict[int, float]]]:
    orow = next(r for r in range(srt.nrows) if srt.text(r, 0) == "Overall")
    players = [(c, srt.text(1, c)) for c in range(1, srt.ncols) if srt.text(1, c)]
    totals: dict[str, dict[int, float]] = {}
    for r in range(orow + 1, srt.nrows):
        lab = srt.text(r, 0)
        if lab:
            totals[lab] = {c: srt.num(r, c) for c, _ in players}
    return players, totals


def parse_inperson(t: Tournament, w: TournamentWriter, rr_tab: str = "Main",
                   de_tab: str | None = None, codes: bool = False,
                   aliases: dict[str, str] | None = None,
                   schools: dict[str, str] | None = None,
                   fixes: list[dict[str, Any]] | None = None) -> None:
    res = load_grids(t.raw("results_sheet.xlsx"))
    st = load_grids(t.raw("stats_sheet.xlsx"))
    aliases = aliases or {}

    for team, school in (schools or {}).items():
        w.team(team, school=school)

    # ---- results: score sheet (+ standings tables for the cross-check) ------------------
    rr = res[rr_tab]
    code_map: dict[str, str] = {}
    tables: list[dict[str, Any]] = []      # standings tables: {records, groups, rounds}
    for r in range(rr.nrows):
        if rr.text(r, 2) == "Team" and rr.text(r, 3) == "W":
            tables.append({"records": {}, "group": {}, "row": r})
            continue
        if tables and rr.text(r, 2) and rr.num(r, 3) is not None:
            team = alias(rr.text(r, 2), aliases)
            tables[-1]["records"][team] = (rr.num(r, 3), rr.num(r, 4))
            code = rr.text(r, 1)
            if re.match(r"^[A-Z]\d+$", code):
                tables[-1]["group"][team] = code[0]
                if codes:
                    code_map[code] = rr.text(r, 2)
    sgames, byes, warns = schedule_rows(rr, 6, aliases, code_map)
    for m in warns:
        w.warn(m)
    games: list[dict[str, Any]] = []
    max_rr = max((g.round_no or 0) for g in sgames)
    nfin = 0
    for g in sgames:
        if g.round_no is not None:
            stage, seq, rnd = "rr", g.round_no, g.round_label
        else:
            nfin += 1
            stage, seq, rnd = "playoff", max_rr + nfin, g.round_label
        games.append({"t1": g.t1, "t2": g.t2, "s1": g.s1, "s2": g.s2, "stage": stage,
                      "round": rnd, "seq": seq})
    if de_tab:
        bgames, bw = bracket_games(res[de_tab], 0, aliases)
        for m in bw:
            w.warn(m)
        cols = sorted({g.col for g in bgames})
        for g in bgames:
            k = cols.index(g.col)
            games.append({"t1": g.t1, "t2": g.t2, "s1": g.s1, "s2": g.s2, "stage": "playoff",
                          "round": f"DE {g.round_label.title()}", "seq": max_rr + 1 + k,
                          "notes": g.notes})
    for fx in fixes or []:
        for gm in games:
            if gm["round"] == str(fx["round"]) and {gm["t1"], gm["t2"]} == {fx["t1"], fx["t2"]}:
                old = (gm["s1"], gm["s2"]) if gm["t1"] == fx["t1"] else (gm["s2"], gm["s1"])
                gm["s1"], gm["s2"] = (fx["s1"], fx["s2"]) if gm["t1"] == fx["t1"] else (fx["s2"], fx["s1"])
                gm["notes"] = f"{fx['note']} (score sheet had {fx['t1']} {old[0]:g} - {old[1]:g})"
                break
        else:
            w.warn(f"fix not applied: {fx}")

    # ---- stats sheet: one 30-row block per round, in play order --------------------------
    full, srt = st["Full"], st["Sorted"]
    blocks = _stats_blocks(full)
    used: set[tuple[int, int]] = set()
    games.sort(key=lambda g: g["seq"])
    for gm in games:
        b = gm["seq"] - 1
        hit = None
        for i, sg in enumerate(blocks[b] if b < len(blocks) else []):
            if {alias(sg["teams"][0][0], aliases), alias(sg["teams"][1][0], aliases)} == {gm["t1"], gm["t2"]}:
                hit = (b, i)
        if hit is None:
            w.warn(f"round {gm['round']} {gm['t1']} vs {gm['t2']}: not in the statistics sheet")
            continue
        used.add(hit)
        sg = blocks[hit[0]][hit[1]]
        gm["stats"] = sg
        fa, fb = sg["final"] if alias(sg["teams"][0][0], aliases) == gm["t1"] else sg["final"][::-1]
        if (fa, fb) != (gm["s1"], gm["s2"]):
            w.warn(f"round {gm['round']} {gm['t1']} vs {gm['t2']}: results {gm['s1']:g}-{gm['s2']:g}, "
                   f"stats sheet {fa}-{fb}")
    for b, bl in enumerate(blocks):
        for i, sg in enumerate(bl):
            if (b, i) in used:
                continue
            ta, tb = (alias(x[0], aliases) for x in sg["teams"])
            fa, fb = sg["final"]
            w.warn(f"stats-only game (block {b + 1}): {ta} {fa} - {fb} {tb}")
            games.append({"t1": ta, "t2": tb, "s1": fa, "s2": fb, "stage": "consolation",
                          "round": f"Consolation (round {b + 1})", "seq": b + 1, "stats": sg,
                          "notes": "game recorded only in the statistics sheet"})
    games.sort(key=lambda g: g["seq"])
    groups = {tm: grp for tb in tables for tm, grp in tb["group"].items()} if len(tables) == 1 else {}
    for gm in games:
        g1, g2 = groups.get(gm["t1"]), groups.get(gm["t2"])
        if gm["stage"] == "rr" and g1 and g2 and g1 != g2:
            gm["notes"] = (gm.get("notes", "") + "; " if gm.get("notes") else "") + \
                "cross-pool game (not counted in the pool standings)"
    _add_games(w, games)

    # standings cross-check: per table, same-group games up to the table's last round
    rr_games = [g for g in games if g["stage"] == "rr"]
    for k, tb in enumerate(tables):
        nxt = tables[k + 1]["row"] if k + 1 < len(tables) else rr.nrows
        rounds = [int(rr.num(r, 6)) for r in range(tb["row"], nxt) if rr.num(r, 6) is not None]
        if tb["group"]:
            sel = [g for g in rr_games if g["seq"] <= max(rounds or [99])
                   and tb["group"].get(g["t1"]) and tb["group"].get(g["t1"]) == tb["group"].get(g["t2"])]
        else:
            sel = [g for g in games if g["stage"] != "consolation"]
        _check_records(w, sel, tb["records"], f"standings table {k + 1}")

    # ---- per-game subject points from the 'Full' tab (bonus + running score) ---------------
    for gm in games:
        sg = gm.get("stats")
        if not sg:
            continue
        b = sg["block"]
        per: dict[str, dict[str, Counter]] = {}
        for tname, tc in sg["teams"]:
            d = {"tp": Counter(), "bp": Counter(), "tu": Counter()}
            prev = 0.0
            for q in range(1, 25):
                r = _q_row(b, q)
                cat = _cat(q)
                sc = full.num(r, tc + 1)
                sc = prev if sc is None else sc
                bon = full.num(r, tc) or 0
                tp = sc - prev - bon
                if full.text(r, tc) != "" and tp >= 4:
                    d["tu"][cat] += 1
                elif full.text(r, tc) != "" or tp < 0:
                    w.warn(f"round {gm['round']} {tname} Q{q}: bonus cell {full.text(r, tc)!r} "
                           f"with score change {sc - prev:g}")
                d["bp"][cat] += bon
                d["tp"][cat] += tp
                prev = sc
            per[alias(tname, aliases)] = d
        (n1, d1), (n2, d2) = per.items()
        for tn, d, o in ((n1, d1, d2), (n2, d2, d1)):
            for cat in IGNIS_CATS:
                opp_negs = (o["tp"][cat] - 4 * o["tu"][cat]) / 4
                w.team_game_subject(gm["gid"], tn, CAT_SUBJECT[cat], d["tp"][cat] + d["bp"][cat],
                                    tossup_points=d["tp"][cat], bonus_points=d["bp"][cat],
                                    tossups_correct=d["tu"][cat], negs=opp_negs)
                if d["tp"][cat] - 4 * d["tu"][cat] < 0 or (d["tp"][cat] - 4 * d["tu"][cat]) % 4:
                    w.warn(f"round {gm['round']} {tn} {cat}: odd tossup points {d['tp'][cat]:g}")

    # ---- player totals ('Stats' tab) ----------------------------------------------------------
    stats = st["Stats"]
    h = stats.row_texts(0)
    keys = ["TU", "Neg"] + [f"{x} {f}" for x, _ in STAT_SUBJ for f in ("TU", "Neg")]
    ci = {k: header_index(h, rf"^{re.escape(k)}$") for k in ["Team", "GP", "TUH", "Points"] + keys}
    srows = []
    for r in range(1, stats.nrows):
        name = stats.text(r, 0)
        if not name:
            continue
        team = alias(stats.text(r, ci["Team"]), aliases)
        vals = {k: stats.num(r, c) for k, c in ci.items() if c is not None and k != "Team"}
        srows.append((name, team, vals))

    # Sorted tab columns (per-question 4 / -4 marks) -> Stats rows: same name (and team when
    # the Sorted tab shows it), ties and renamed players resolved by identical totals.
    players, totals = _sorted_players(srt)
    pteam = {c: alias(srt.text(0, c), aliases) for c, _ in players}
    cvec = {c: tuple((totals.get(k, {}).get(c) or 0) for k in keys) for c, _ in players}
    col_player: dict[int, tuple[str, str]] = {}
    pending = []
    for name, team, vals in srows:
        v = tuple((vals.get(k) or 0) for k in keys)
        cands = [c for c, p in players if p == name and pteam[c] in ("", team)]
        if len(cands) > 1:
            cands = [c for c in cands if cvec[c] == v] or cands
        if len(cands) == 1:
            col_player[cands[0]] = (name, team)
        else:
            pending.append((name, team, v))
    for name, team, v in pending:
        cands = [c for c, _ in players if c not in col_player and cvec[c] == v and pteam[c] in ("", team)]
        if not cands:   # renamed in the Stats tab, e.g. 'Sai K' -> 'Sai'
            cands = [c for c, p in players if c not in col_player and pteam[c] == team
                     and p.split()[0] == name.split()[0]]
        if len(cands) == 1:
            col_player[cands[0]] = (name, team)
        else:
            w.warn(f"player {name} ({team}): no per-question column in the Sorted tab")
    for c, (name, team) in col_player.items():
        if cvec[c] != tuple((dict(zip(keys, [0] * len(keys))) | {k: v for k, v in
                             next(x[2] for x in srows if x[0] == name and x[1] == team).items()
                             if k in keys and v is not None}).get(k) or 0 for k in keys):
            w.warn(f"player {name} ({team}): per-question marks differ from the Stats totals")

    tuh_row = totals.get("TUH", {})
    pcol = {v: c for c, v in col_player.items()}
    for name, team, vals in srows:
        c = pcol.get((name, team))
        tuh = vals.get("TUH")
        if tuh is None and c is not None and cvec[c] == tuple((vals.get(k) or 0) for k in keys):
            tuh = tuh_row.get(c)
        w.player_stat(name, team, "overall", gp=vals.get("GP"), tuh=tuh, correct=vals.get("TU"),
                      negs=vals.get("Neg"), points=vals.get("Points"))
        for x, subj in STAT_SUBJ:
            w.player_stat(name, team, subj, gp=vals.get("GP"), correct=vals.get(f"{x} TU"),
                          negs=vals.get(f"{x} Neg"))

    # ---- per-game player buzzes ('Sorted' tab) ---------------------------------------------
    team_cols: dict[str, list[int]] = defaultdict(list)
    for c, (name, team) in col_player.items():
        team_cols[team].append(c)
    for gm in games:
        sg = gm.get("stats")
        if not sg:
            continue
        b = sg["block"]
        for tname, _ in sg["teams"]:
            tn = alias(tname, aliases)
            for c in team_cols.get(tn, []):
                cnt: Counter = Counter()
                for q in range(1, 25):
                    v = srt.num(_q_row(b, q), c)
                    if v == 4:
                        cnt[_cat(q) + "+"] += 1
                    elif v == -4:
                        cnt[_cat(q) + "-"] += 1
                if not cnt:
                    continue
                name, team = col_player[c]
                w.player_game_stat(gm["gid"], name, team, "overall",
                                   correct=sum(cnt[x + "+"] for x in IGNIS_CATS),
                                   negs=sum(cnt[x + "-"] for x in IGNIS_CATS))
                for cat in IGNIS_CATS:
                    if cnt[cat + "+"] or cnt[cat + "-"]:
                        w.player_game_stat(gm["gid"], name, team, CAT_SUBJECT[cat],
                                           correct=cnt[cat + "+"], negs=cnt[cat + "-"])


# =======================================================================================
# Online Ignis Virtual / Olympus
# =======================================================================================
def _schedule_rounds(g: Grid, aliases: dict[str, str]) -> dict[frozenset[str], int]:
    """Division slot table + 'Round k: a vs b' schedule tables -> {pair: round}."""
    divs: dict[str, list[str]] = {}
    for r in range(g.nrows):
        if g.text(r, 0) and g.text(r, 1) and num(g.text(r, 1)) is None:
            divs[g.text(r, 0)] = [g.text(r, c) for c in range(1, 7)]
    tables: dict[int | None, dict[int, list[tuple[int, int]]]] = defaultdict(dict)
    size: int | None = None
    for r in range(g.nrows):
        for c in range(g.ncols):
            m = re.search(r"divisions with (\d+) teams", g.text(r, c), re.I)
            if m:
                size = int(m.group(1))
            m = re.match(r"^Round (\d+)$", g.text(r, c))
            if m:
                pairs = []
                for cc in range(c + 1, g.ncols):
                    pm = re.match(r"^(\d+) vs (\d+)$", g.text(r, cc))
                    if pm:
                        pairs.append((int(pm.group(1)), int(pm.group(2))))
                tables[size][int(m.group(1))] = pairs
    out: dict[frozenset[str], int] = {}
    for div, slots in divs.items():
        n = sum(1 for s in slots if s and s.upper() != "BYE" and s != "--")
        tab = tables.get(n) or tables.get(None) or (next(iter(tables.values())) if len(tables) == 1 else None)
        if not tab:
            continue
        for rnd, pairs in tab.items():
            for a, b in pairs:
                ta, tb = slots[a - 1], slots[b - 1]
                if not ta or not tb or "BYE" in (ta.upper(), tb.upper()) or "--" in (ta, tb):
                    continue
                out[frozenset((alias(ta, aliases), alias(tb, aliases)))] = rnd
    return out


def parse_online(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
                 schools: dict[str, str] | None = None,
                 states: dict[str, str] | None = None) -> None:
    res = load_grids(t.raw("results_sheet.xlsx"))
    st = load_grids(t.raw("stats_sheet.xlsx"))
    aliases = aliases or {}
    for team, school in (schools or {}).items():
        w.team(team, school=school, state=(states or {}).get(team, ""))

    # ---- RR results -------------------------------------------------------------------
    rgames, standings, warns = rr_matrix(res["Round Robin"], aliases)
    for m in warns:
        w.warn(m)
    my_teams = set(standings)
    for tm in sorted(my_teams):
        w.team(tm)

    # ---- stats: raw buzz log ---------------------------------------------------------------
    raw = st["Raw"]
    rh = raw.row_texts(0)
    rc = {k: header_index(rh, rf"^({k})$") for k in
          ("gameRecordId", "score", "whoBuzzedGID", "teamId", "Team|teamName", "isTeamA",
           "isEmpty", "questionNum", "Cat")}
    raw_games: dict[str, dict[str, Any]] = {}
    for r in range(1, raw.nrows):
        gid = raw.text(r, rc["gameRecordId"])
        team = alias(raw.text(r, rc["Team|teamName"]), aliases)
        if team not in my_teams:
            continue
        rg = raw_games.setdefault(gid, {"teams": {}, "rows": []})
        is_a = raw.text(r, rc["isTeamA"]).lower() == "true"
        rg["teams"][team] = is_a
        who = raw.text(r, rc["whoBuzzedGID"])
        rg["rows"].append({"team": team, "score": raw.num(r, rc["score"]) or 0,
                           "who": "" if who.upper() == "NULL" else who,
                           "q": int(raw.num(r, rc["questionNum"]) or 0),
                           "cat": raw.text(r, rc["Cat"])})
    prelim_ids: set[str] = set()
    if "PrelimRaw" in st:
        pr = st["PrelimRaw"]
        pc = header_index(pr.row_texts(0), r"^gameRecordId$")
        prelim_ids = {pr.text(r, pc) for r in range(1, pr.nrows)}
    round_of: dict[str, int] = {}
    if "Games" in st:
        gg = st["Games"]
        for r in range(1, gg.nrows):
            if gg.num(r, 1) is not None:
                round_of[gg.text(r, 0)] = int(gg.num(r, 1))

    for gid, rg in raw_games.items():
        own: Counter = Counter()
        negs: Counter = Counter()
        for row in rg["rows"]:
            own[row["team"]] += max(row["score"], 0)
            if row["score"] < 0:
                negs[row["team"]] += 1
        teams = sorted(rg["teams"], key=lambda x: not rg["teams"][x])
        if len(teams) == 1:     # opponent's side not logged (e.g. Olympus games vs MSMS)
            rg["single"] = teams[0]
            rg["final"] = {teams[0]: own[teams[0]]}
            continue
        if len(teams) != 2:
            w.warn(f"stats game {gid}: teams {teams}")
            rg["final"] = None
            continue
        a, b = teams
        rg["pair"] = (a, b)
        rg["final"] = {a: own[a] + 4 * negs[b], b: own[b] + 4 * negs[a]}

    # ---- assemble games ------------------------------------------------------------------
    sched = _schedule_rounds(res["RR Schedule"], aliases) if "RR Schedule" in res else {}
    games: list[dict[str, Any]] = []
    for g in rgames:
        games.append({"t1": g.t1, "t2": g.t2, "s1": g.s1, "s2": g.s2, "stage": "rr",
                      "result": g.result, "forfeit": g.forfeit, "notes": g.notes,
                      "division": g.division})
    # link RR games with stats games (prelim ids, or round <= 5 in the Games tab)
    by_pair: dict[frozenset[str], list[str]] = defaultdict(list)
    logged = {tm for rg in raw_games.values() if "pair" in rg for tm in rg["pair"]}
    singles: dict[str, list[str]] = defaultdict(list)
    for gid in sorted(raw_games, key=lambda x: float(x)):
        rg = raw_games[gid]
        if rg.get("final") and "pair" in rg:
            by_pair[frozenset(rg["pair"])].append(gid)
        elif rg.get("single"):
            singles[rg["single"]].append(gid)
    used: set[str] = set()
    for gm in games:
        cands = [x for x in by_pair.get(frozenset((gm["t1"], gm["t2"])), [])
                 if x not in used and (not prelim_ids or x in prelim_ids)]
        if not cands:
            for me, other in ((gm["t1"], gm["t2"]), (gm["t2"], gm["t1"])):
                if other not in logged:
                    cands = [x for x in singles.get(me, []) if x not in used]
                    if len(cands) == 1:
                        raw_games[cands[0]]["pair"] = (me, other)
                        raw_games[cands[0]]["final"][other] = None
                        break
                    cands = []
        if cands:
            gm["raw"] = cands[0]
            used.add(cands[0])
        rnd = round_of.get(gm.get("raw", ""))
        if rnd is None:
            rnd = sched.get(frozenset((gm["t1"], gm["t2"])))
        if rnd is None:
            w.warn(f"no round number for RR game {gm['t1']} vs {gm['t2']}")
        gm["round"] = str(rnd) if rnd else ""
        gm["seq"] = rnd or 1
    max_rr = max(g["seq"] for g in games)

    bgames, bw = bracket_games(res["Double Elimination"], 0, aliases)
    for m in bw:
        w.warn(m)
    cols = sorted({g.col for g in bgames})
    de = []
    for g in bgames:
        k = cols.index(g.col)
        de.append({"t1": g.t1, "t2": g.t2, "s1": g.s1, "s2": g.s2, "stage": "playoff",
                   "round": f"DE {g.round_label.title()}", "seq": max_rr + 1 + k,
                   "notes": g.notes})
    de.sort(key=lambda g: (g["seq"], g["round"]))
    for gm in de:
        cands = [x for x in by_pair.get(frozenset((gm["t1"], gm["t2"])), []) if x not in used]
        if cands:
            gm["raw"] = cands[0]
            used.add(cands[0])
    games.extend(de)
    for gm in games:
        rg = raw_games.get(gm.get("raw", ""))
        if rg is None:
            if not gm.get("forfeit"):
                w.warn(f"{gm['round']} {gm['t1']} vs {gm['t2']}: no buzz log in the stats sheet")
            continue
        f1, f2 = rg["final"][gm["t1"]], rg["final"][gm["t2"]]
        if (f1 if f1 is not None else gm["s1"], f2 if f2 is not None else gm["s2"]) != (gm["s1"], gm["s2"]):
            w.warn(f"{gm['round']} {gm['t1']} vs {gm['t2']}: results {gm['s1']}-{gm['s2']}, "
                   f"buzz log {f1}-{f2}")
    for gid in raw_games:
        if gid not in used and raw_games[gid].get("final") and "pair" in raw_games[gid]:
            rg = raw_games[gid]
            w.warn(f"stats game {gid} {rg['pair']} {rg['final']} not matched to a result")
    games.sort(key=lambda g: (g["seq"], g.get("division", ""), g["round"]))
    _add_games(w, games)
    rec = {tm: (s.get("W"), s.get("L")) for tm, s in standings.items()}
    _check_records(w, games, rec, "RR standings", stages=("rr",))

    # ---- players --------------------------------------------------------------------------
    users = st["Users"]
    uh = users.row_texts(0)
    uc = {"gid": header_index(uh, r"^googleId$"), "full": header_index(uh, r"^fullName$"),
          "first": header_index(uh, r"^firstName$"), "team": header_index(uh, r"^Team$")}
    disp_col = uc["first"]
    if disp_col is None:      # West/East: display name in the last column, first in col 2
        disp_col = max(c for c in range(users.ncols) if users.text(1, c))
    u_by_gid: dict[str, dict[str, str]] = {}
    for r in range(1, users.nrows):
        gid = users.text(r, uc["gid"])
        if not gid:
            continue
        u_by_gid[gid] = {
            "full": re.sub(r"^\[[^\]]*\]\s*", "", users.text(r, uc["full"])),
            "disp": users.text(r, disp_col),
            "first": users.text(r, 2) if uc["first"] is None else users.text(r, uc["first"]),
            "team": alias(users.text(r, uc["team"]), aliases)}

    def tidy(pname: str, team: str) -> str:
        """Strip team tags players typed into their account name ('Connor Z[Noho B]',
        'Kaiwen - Enloe B')."""
        pname = re.sub(r"\s*\[[^\]]*\]\s*$", "", pname)
        pname = re.sub(rf"\s*-\s*{re.escape(team)}\s*$", "", pname, flags=re.I)
        return clean_name(pname)

    for gid, u in u_by_gid.items():
        u["full"] = tidy(u["full"], u["team"])
    # per player totals and per-game buzzes from the raw log
    ptot: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for gm in games:
        rg = raw_games.get(gm.get("raw", ""))
        if rg is None:
            continue
        opp = {gm["t1"]: gm["t2"], gm["t2"]: gm["t1"]}
        tu: dict[str, Counter] = defaultdict(Counter)
        ng: dict[str, Counter] = defaultdict(Counter)
        bon: dict[str, Counter] = defaultdict(Counter)
        pg: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for row in rg["rows"]:
            cat, team, s = row["cat"], row["team"], row["score"]
            if s > 0:
                tu[team][cat] += 1
                bon[team][cat] += s - 4
            elif s < 0:
                ng[team][cat] += 1
            if row["who"]:
                key = (row["who"], team)
                if s > 0:
                    pg[key][cat + "+"] += 1
                elif s < 0:
                    pg[key][cat + "-"] += 1
                else:
                    pg[key][cat + "0"] += 1
        for team in (gm["t1"], gm["t2"]):
            if rg["final"].get(team) is None:
                continue
            tot = 0.0
            for cat in IGNIS_CATS:
                tp = 4 * tu[team][cat] + 4 * ng[opp[team]][cat]
                bp = bon[team][cat]
                tot += tp + bp
                w.team_game_subject(gm["gid"], team, CAT_SUBJECT[cat], tp + bp, tossup_points=tp,
                                    bonus_points=bp, tossups_correct=tu[team][cat],
                                    negs=ng[team][cat])
        for (who, team), cnt in pg.items():
            u = u_by_gid.get(who) or {}
            name = u.get("full") or u.get("disp") or who
            ptot[(who, team)].update(cnt)
            w.player_game_stat(gm["gid"], name, team, "overall",
                               correct=sum(cnt[c + "+"] for c in IGNIS_CATS),
                               negs=sum(cnt[c + "-"] for c in IGNIS_CATS))
            for cat in IGNIS_CATS:
                if cnt[cat + "+"] or cnt[cat + "-"]:
                    w.player_game_stat(gm["gid"], name, team, CAT_SUBJECT[cat],
                                       correct=cnt[cat + "+"], negs=cnt[cat + "-"])

    # published totals ('Full' + '<Subject> Full' tabs); first names -> Google ids
    full = st["Full"]
    fh = full.row_texts(0)
    fc = {k: header_index(fh, rf"^{re.escape(k)}$") for k in
          ("Name", "Team", "GP", "TUH", "TU", "X", "Neg", "Points")}
    subj_tabs = {"X": "X-Risk Full", "M": "Math Full", "C": "Chemistry Full",
                 "E": "EarthSpace Full", "B": "Biology Full", "P": "Physics Full"}
    subj_rows: dict[str, dict[tuple[str, str], list[dict[str, float | None]]]] = {}
    for cat, tab in subj_tabs.items():
        sg = st[tab]
        sh = sg.row_texts(0)
        scol = {k: header_index(sh, rf"^{re.escape(k)}$") for k in
                ("Name", "Team", "GP", "TUH", "TU", "X", "Neg", "Points")}
        d: dict[tuple[str, str], list[dict[str, float | None]]] = defaultdict(list)
        for r in range(1, sg.nrows):
            key = (sg.text(r, scol["Name"]), alias(sg.text(r, scol["Team"]), aliases))
            d[key].append({k: sg.num(r, c) for k, c in scol.items() if k not in ("Name", "Team")})
        subj_rows[cat] = d

    by_team_disp: dict[tuple[str, str], list[str]] = defaultdict(list)
    for gid, u in u_by_gid.items():
        by_team_disp[(u["team"], u["disp"])].append(gid)
        if u["first"] and u["first"] != u["disp"]:
            by_team_disp[(u["team"], u["first"])].append(gid)
    claimed: set[str] = set()
    for r in range(1, full.nrows):
        name = full.text(r, fc["Name"])
        team = alias(full.text(r, fc["Team"]), aliases)
        if not name or team not in my_teams:
            continue
        v = {k: full.num(r, c) for k, c in fc.items() if k not in ("Name", "Team")}
        cands = [g for g in dict.fromkeys(by_team_disp.get((team, name), [])) if g not in claimed]
        if len(cands) > 1:
            exact = [g for g in cands
                     if sum(ptot[(g, team)][c + "+"] for c in IGNIS_CATS) == (v["TU"] or 0)
                     and sum(ptot[(g, team)][c + "-"] for c in IGNIS_CATS) == (v["Neg"] or 0)]
            cands = exact or cands
        gid = cands[0] if cands else None
        if gid:
            claimed.add(gid)
            pname = u_by_gid[gid]["full"] or u_by_gid[gid]["disp"] or name
            pt = ptot.get((gid, team))
            if pt is not None:
                got = (sum(pt[c + "+"] for c in IGNIS_CATS), sum(pt[c + "-"] for c in IGNIS_CATS))
                if got != ((v["TU"] or 0), (v["Neg"] or 0)):
                    w.warn(f"{pname} ({team}): published TU/Neg {v['TU']}/{v['Neg']}, "
                           f"buzz log {got[0]}/{got[1]}")
        else:
            pname = name
            w.warn(f"{name} ({team}): no Google account match, kept first name")
        w.player_stat(pname, team, "overall", gp=v["GP"], tuh=v["TUH"], correct=v["TU"],
                      zeros=v["X"], negs=v["Neg"], points=v["Points"])
        for cat, subj in STAT_SUBJ:
            rows = subj_rows[cat].get((name, team), [])
            if len(rows) > 1 and gid:
                pt = ptot.get((gid, team), Counter())
                rows = [x for x in rows if (x["TU"] or 0) == pt[cat + "+"]
                        and (x["Neg"] or 0) == pt[cat + "-"]] or rows
            if not rows:
                continue
            x = rows[0]
            w.player_stat(pname, team, subj, gp=x["GP"], tuh=x["TUH"], correct=x["TU"],
                          zeros=x["X"], negs=x["Neg"], points=x["Points"])
