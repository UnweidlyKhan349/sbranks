"""ESBOT 2022 / 2023 and CAST 2021 (online tournaments listed on prometheus.science).

All three keep results in a Google Sheet; CAST 2021 and ESBOT 2022 statistics are xlsx
files hosted on prometheus.science (Squarespace), ESBOT 2023 statistics are a Google Sheet.

``parse_esbot23``  results "Round Robin" (seeded divisions, two side by side; cell =
                   row team's score against the column team; schedule "RR1: 1 vs 2 ...")
                   and an irregular "Double Elimination" layout read through the explicit
                   cell list in parser_options ``de_games``; stats "INDIV-STATS"
                   ("Name [Team]", per-category correct + TUH, overall penalties).
``parse_esbot22``  same results layout (one division per block, schedule below the
                   "RR1..RR5" labels) + ``de_games`` cell list; the statistics export has no
                   usable player stats (see YAML notes).
``parse_cast``     "Prelims" pool grids ("a - b" strings) and "Round of 16/8/4/2" tabs.

``de_games`` entries: ``{round, seq, a: [row, team_col, score_col], b: [...],
winner: a|b (when no scores), forfeit, tb: {a: [row, col], b: [row, col]}, stats_game,
note}`` with 0-based grid coordinates.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, header_index, load_grids
from .g2_common import alias


# ---------------------------------------------------------------------------------------
def _seeded_divisions(g: Grid, aliases: dict[str, str], sched_mode: str, seed_offset: int = 0
                      ) -> tuple[list[dict[str, Any]], list[str]]:
    """Division blocks: '<X> Division' title; header row of opponent names; team rows with
    a seed number and the team name; score cells under the opponent columns."""
    warns: list[str] = []
    titles = [(r, c, g.text(r, c)) for r, c in g.find(r"Division$")]
    title_rows = sorted({r for r, _, _ in titles})
    # schedule tables: {first_row: {round: [(a, b), ...]}}
    scheds: list[tuple[int, dict[int, list[tuple[int, int]]]]] = []
    for r, c in g.find(r"^RR\s*\d+$"):
        rnd = int(re.sub(r"\D", "", g.text(r, c)))
        pairs = []
        if sched_mode == "right":
            cells = [g.text(r, cc) for cc in range(c + 1, g.ncols)]
        else:   # pairs stacked below the label
            cells = [g.text(rr, c) for rr in range(r + 1, min(r + 4, g.nrows))]
        for v in cells:
            m = re.match(r"^(\d+)\s*vs\.?\s*(\d+)$", v)
            if m:
                pairs.append((int(m.group(1)), int(m.group(2))))
        scheds.append((r, {rnd: pairs}))
    games = []
    for (tr, tc0, title) in titles:
        tc = tc0 + seed_offset      # seed column; team names one column to the right
        nxt = min([x for x in title_rows if x > tr] + [g.nrows])
        div = title.replace(" Division", "")
        # header: first row below the title with a team name in tc+2
        hr = next(r for r in range(tr + 1, nxt) if g.text(r, tc + 2) or g.text(r, tc + 3))
        opp_cols = {}
        for c in range(tc + 2, tc + 8):
            if g.text(hr, c):
                opp_cols[c] = g.text(hr, c)
        seeds: dict[int, str] = {}
        rows: dict[str, int] = {}
        for r in range(hr + 1, nxt):
            sd = g.num(r, tc)
            name = g.text(r, tc + 1)
            if sd is not None and name:
                seeds[int(sd)] = name
                rows[name] = r
        # pair -> round
        rnd_of: dict[frozenset[str], int] = {}
        cand = [s for s in scheds if s[0] < nxt and (sched_mode == "below" or s[0] >= tr - 2)]
        for _, d in cand:
            for rnd, pairs in d.items():
                for a, b in pairs:
                    if a in seeds and b in seeds:
                        rnd_of.setdefault(frozenset((seeds[a], seeds[b])), rnd)
        done: set[frozenset[str]] = set()
        for a, ra in rows.items():
            if a.upper() == "BYE":
                continue
            for c, b in opp_cols.items():
                if b.upper() == "BYE" or b == a or frozenset((a, b)) in done:
                    continue
                rb = rows.get(b)
                if rb is None:
                    warns.append(f"{div}: column team {b} has no row")
                    continue
                cb = next(cc for cc, x in opp_cols.items() if x == a)
                sa, sb = g.num(ra, c), g.num(rb, cb)
                if sa is None and sb is None:
                    continue
                done.add(frozenset((a, b)))
                rnd = rnd_of.get(frozenset((a, b)))
                if rnd is None:
                    warns.append(f"{div}: no round for {a} vs {b}")
                games.append({"t1": alias(a, aliases), "t2": alias(b, aliases), "s1": sa,
                              "s2": sb, "stage": "rr", "round": str(rnd or ""), "seq": rnd or 1,
                              "division": div})
    return games, warns


def _de_games(g: Grid, spec: list[dict[str, Any]], aliases: dict[str, str],
              stats_scores: dict[str, dict[str, float]] | None = None) -> list[dict[str, Any]]:
    out = []
    for e in spec:
        (ra, ca, sa_c), (rb, cb, sb_c) = e["a"], e["b"]
        t1, t2 = alias(g.text(ra, ca), aliases), alias(g.text(rb, cb), aliases)
        s1, s2 = g.num(ra, sa_c), g.num(rb, sb_c)
        notes = [e["note"]] if e.get("note") else []
        if e.get("tb"):
            tb1 = num(re.sub(r"[^\d.\-]", "", g.text(*e["tb"]["a"])))
            tb2 = num(re.sub(r"[^\d.\-]", "", g.text(*e["tb"]["b"])))
            notes.append(f"{s1:g}-{s2:g} after regulation, tiebreaker {tb1:g}-{tb2:g} "
                         f"(score includes the tiebreaker)")
            s1, s2 = s1 + tb1, s2 + tb2
        if (s1 is None or s2 is None) and e.get("stats_game") and stats_scores:
            sc = stats_scores.get(e["stats_game"], {})
            if t1 in sc and t2 in sc:
                s1, s2 = sc[t1], sc[t2]
                notes.append("score from the statistics sheet (missing on the bracket)")
        result = ""
        if s1 is None or s2 is None:
            s1 = s2 = None
            result = {"a": "1", "b": "2"}[e["winner"]]
            if not e.get("forfeit"):
                notes.append("winner from the bracket; score not reported")
        out.append({"t1": t1, "t2": t2, "s1": s1, "s2": s2, "stage": "playoff",
                    "round": e["round"], "seq": e["seq"], "result": result,
                    "forfeit": bool(e.get("forfeit")), "notes": "; ".join(notes)})
    return out


def _write_games(w: TournamentWriter, games: list[dict[str, Any]]) -> None:
    games.sort(key=lambda x: (x["seq"], x.get("division", ""), x["round"]))
    for gm in games:
        notes = gm.get("notes", "")
        if gm.get("division"):
            notes = "; ".join(x for x in (f"division {gm['division']}", notes) if x)
        gm["gid"] = w.game(gm["t1"], gm["t2"], gm["s1"], gm["s2"], stage=gm["stage"],
                           round=gm["round"], seq=gm["seq"], result=gm.get("result", ""),
                           forfeit=gm.get("forfeit", False), notes=notes)


def _rr_points_check(w: TournamentWriter, g: Grid, games: list[dict[str, Any]],
                     aliases: dict[str, str], points_label: str = "Points") -> None:
    """ESBOT 'Points' column = 2 per win + 1 per tie (round robin only)."""
    pts: dict[str, float] = defaultdict(float)
    for gm in games:
        if gm["stage"] != "rr" or gm["s1"] is None:
            continue
        if gm["s1"] > gm["s2"]:
            pts[gm["t1"]] += 2
        elif gm["s2"] > gm["s1"]:
            pts[gm["t2"]] += 2
        else:
            pts[gm["t1"]] += 1
            pts[gm["t2"]] += 1
    # locate team rows: seed col = (Points col - 9), team col = seed col + 1
    for r, c in g.find(rf"^{points_label}$"):
        sc = c - 9
        for rr in range(r + 1, min(r + 14, g.nrows)):
            name = g.text(rr, sc + 1)
            if g.num(rr, sc) is None or not name or name.upper() == "BYE":
                continue
            src = g.num(rr, c)
            t = alias(name, aliases)
            if src is not None and src != pts.get(t, 0):
                w.warn(f"standings: {t} source points {src:g}, parsed {pts.get(t, 0):g}")


# ---------------------------------------------------------------------------------------
def parse_esbot23(t: Tournament, w: TournamentWriter, de_games: list[dict[str, Any]],
                  aliases: dict[str, str] | None = None, notes: dict[str, str] | None = None,
                  schools: dict[str, str] | None = None) -> None:
    aliases = aliases or {}
    res = load_grids(t.raw("results.xlsx"))
    for team in set(schools or {}) | set(notes or {}):
        w.team(team, school=(schools or {}).get(team, ""), notes=(notes or {}).get(team, ""))
    rr = res["Round Robin"]
    games, warns = _seeded_divisions(rr, aliases, "right")
    for m in warns:
        w.warn(m)
    for gm in games:
        for k in ("s1", "s2"):
            if gm[k] is not None and gm[k] != int(gm[k]):
                gm["notes"] = f"score {gm[k]:g} as written in the source (not a whole number)"
    games += _de_games(res["Double Elimination"], de_games, aliases)
    _write_games(w, games)
    _rr_points_check(w, rr, games, aliases)

    # ---- player stats (prelims only) ------------------------------------------------------
    st = load_grids(t.raw("stats.xlsx"))["INDIV-STATS"]
    h = st.row_texts(0)
    subj = {"Biology": "biology", "Chemistry": "chemistry", "Earth": "ess",
            "Physics": "physics", "Math": "math", "Energy": "energy"}
    col = {k: header_index(h, rf"^{k}$") for k in
           list(subj) + ["Total Correct", "Penalties", "Incorrect", "Total TUH"]}
    tuh_col = {k: header_index(h, rf"^{k} TUH$") for k in subj}
    n_sub = 0
    for r in range(1, st.nrows):
        raw = st.text(r, 0)
        m = re.match(r"^(.*?)\s*\[(.+)\]\s*$", raw)
        if not m:
            continue
        name, team = clean_name(m.group(1)), alias(m.group(2), aliases)
        negs = st.num(r, col["Penalties"])
        w.player_stat(name, team, "overall", scope="rr", tuh=st.num(r, col["Total TUH"]),
                      correct=st.num(r, col["Total Correct"]), negs=negs,
                      zeros=st.num(r, col["Incorrect"]))
        if negs == 0:
            # penalties are only reported in total: subject rows are exact only when 0
            n_sub += 1
            for k, s in subj.items():
                w.player_stat(name, team, s, scope="rr", tuh=st.num(r, tuh_col[k]),
                              correct=st.num(r, col[k]), negs=0)


# ---------------------------------------------------------------------------------------
def _esbot22_stats(t: Tournament, w: TournamentWriter, games_written: list[dict[str, Any]],
                   aliases: dict[str, str]) -> None:
    """The ESBOT 2022 stats export: per game, one row per player then (at the bottom of the
    sheet) one row per team, with Score and per-category Correct / Incorrect counts. Team rows
    are the sums of their players' rows, so each game's players are split between the two
    teams by the unique subset whose sums equal the first team's row. Gives rosters,
    per-game player correct counts and per-game team tossups by category (Incorrect is not
    split into penalties / no-penalty answers, and Score includes bonuses, so no points)."""
    st = load_grids(t.raw("stats.xlsx"))["scores"]
    cats = [("Earth", "ess"), ("Chem", "chemistry"), ("Math", "math"), ("Bio", "biology"),
            ("Physics", "physics"), ("Energy", "energy")]
    h = st.row_texts(0)
    cc = {k: header_index(h, rf"^{k} Correct$") for k, _ in cats}
    ci = {k: header_index(h, rf"^{k} Incorrect$") for k, _ in cats}
    first_gid = st.text(1, 0)
    split = next(r for r in range(2, st.nrows) if st.text(r, 0) == first_gid
                 and r > 1 and any(st.text(rr, 0) != first_gid for rr in range(1, r)))
    known = {gm["t1"] for gm in games_written} | {gm["t2"] for gm in games_written}
    low = {k.lower(): v for k, v in aliases.items()}

    def team_name(n: str) -> str | None:
        n = clean_name(n)
        cand = aliases.get(n) or low.get(n.lower()) or n
        for k in known:
            if k.lower() == cand.lower():
                return k
        return None

    def vec(r: int) -> tuple:
        return tuple([st.num(r, 3) or 0] + [st.num(r, cc[k]) or 0 for k, _ in cats]
                     + [st.num(r, ci[k]) or 0 for k, _ in cats])
    players: dict[str, list[int]] = defaultdict(list)
    teams: dict[str, list[int]] = defaultdict(list)
    for r in range(1, st.nrows):
        (players if r < split else teams)[st.text(r, 0)].append(r)
    by_pair: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
    for gm in games_written:
        by_pair[frozenset((gm["t1"], gm["t2"]))].append(gm)
    used: set[str] = set()
    n_ok = 0
    pending: list[tuple[dict[str, Any], str, str, list[int]]] = []
    assigned: list[tuple[dict[str, Any], list[tuple[int, str]]]] = []

    def pname(r: int) -> str:
        return clean_name(re.sub(r"\s*\[[^\]]*\]\s*$", "", st.text(r, 2)))

    for gid, trows in teams.items():
        if len(trows) != 2:
            continue
        (ra, rb) = trows
        ta, tb = team_name(st.text(ra, 2)), team_name(st.text(rb, 2))
        if not ta or not tb or ta == tb:
            w.warn(f"stats game {gid} ({st.text(ra, 1)}): teams {st.text(ra, 2)!r}/{st.text(rb, 2)!r} not matched")
            continue
        prow = players.get(gid, [])
        va = vec(ra)
        sols = []
        for mask in range(1 << len(prow)):
            tot = [0.0] * len(va)
            for i, r in enumerate(prow):
                if mask >> i & 1:
                    for j, x in enumerate(vec(r)):
                        tot[j] += x
            if tuple(tot) == va:
                rest = [0.0] * len(va)
                for i, r in enumerate(prow):
                    if not mask >> i & 1:
                        for j, x in enumerate(vec(r)):
                            rest[j] += x
                if tuple(rest) == vec(rb):
                    sols.append(mask)
        cands = [g for g in by_pair.get(frozenset((ta, tb)), []) if g["gid"] not in used]
        if not cands:
            w.warn(f"stats game {gid} ({st.text(ra, 1)}): no {ta} vs {tb} result")
            continue
        sa, sb = st.num(ra, 3), st.num(rb, 3)
        gm = min(cands, key=lambda g: abs(((g["s1"] if g["t1"] == ta else g["s2"]) or 0) - (sa or 0))
                 + abs(((g["s2"] if g["t1"] == ta else g["s1"]) or 0) - (sb or 0)))
        used.add(gm["gid"])
        for tm, r in ((ta, ra), (tb, rb)):
            for k, subj in cats:
                w.team_game_subject(gm["gid"], tm, subj, tossups_correct=st.num(r, cc[k]))
        if len(sols) != 1:
            # players with no buzz are interchangeable: accept when only all-zero rows differ
            nz = [i for i, r in enumerate(prow) if any(vec(r))]
            proj = {tuple(m >> i & 1 for i in nz) for m in sols}
            if len(proj) != 1:
                pending.append((gm, ta, tb, prow))
                continue
            prow = [prow[i] for i in nz]
            mask = sum(1 << k for k, i in enumerate(nz) if sols[0] >> i & 1)
        else:
            mask = sols[0]
        n_ok += 1
        assigned.append((gm, [(r, ta if mask >> i & 1 else tb) for i, r in enumerate(prow)]))
    # games whose team rows are not exact sums of the listed players: place a player only
    # when the name is on exactly one of the two rosters established above
    roster: dict[str, set[str]] = defaultdict(set)
    for _, pl in assigned:
        for r, tm in pl:
            roster[tm].add(pname(r).lower())
    n_part = 0
    for gm, ta, tb, prow in pending:
        pl = []
        for r in prow:
            on = [tm for tm in (ta, tb) if pname(r).lower() in roster[tm]]
            if len(on) == 1:
                pl.append((r, on[0]))
        if pl:
            n_part += 1
            assigned.append((gm, pl))
    spelling: dict[tuple[str, str], str] = {}     # 'ray' and 'Ray' on one team: one player
    for gm, pl in assigned:
        for r, tm in pl:
            name = spelling.setdefault((tm, pname(r).lower()), pname(r))
            w.team(tm, players=[name])
            correct = {subj: st.num(r, cc[k]) or 0 for k, subj in cats}
            w.player_game_stat(gm["gid"], name, tm, "overall", correct=sum(correct.values()))
            for subj, c in correct.items():
                if c:
                    w.player_game_stat(gm["gid"], name, tm, subj, correct=c)
    w.warn(f"info: {n_ok} stats games split into teams exactly, {n_part} more by roster names")


def parse_esbot22(t: Tournament, w: TournamentWriter, de_games: list[dict[str, Any]],
                  aliases: dict[str, str] | None = None,
                  stats_aliases: dict[str, str] | None = None,
                  notes: dict[str, str] | None = None) -> None:
    aliases = aliases or {}
    res = load_grids(t.raw("results.xlsx"))
    rr = res["Round Robin"]
    games, warns = _seeded_divisions(rr, aliases, "below", seed_offset=-1)
    for m in warns:
        w.warn(m)
    for team, note in (notes or {}).items():
        w.team(team, notes=note)
    # team score rows of the statistics export (used for one bracket game without a score)
    st = load_grids(t.raw("stats.xlsx"))["scores"]
    team_rows: dict[str, dict[str, float]] = defaultdict(dict)
    for r in range(1, st.nrows):
        name = st.text(r, 2)
        team = alias(name, aliases)
        team_rows[st.text(r, 0)][team] = st.num(r, 3)
    games += _de_games(res["Double Elims"], de_games, aliases, team_rows)
    _write_games(w, games)
    _esbot22_stats(t, w, games, {**aliases, **(stats_aliases or {})})
    # 'Points' column (col 8 of each block) = 2 per win
    pts: dict[str, float] = defaultdict(float)
    for gm in games:
        if gm["stage"] == "rr" and gm["s1"] is not None:
            win = gm["t1"] if gm["s1"] > gm["s2"] else gm["t2"] if gm["s2"] > gm["s1"] else None
            if win:
                pts[win] += 2
            else:
                pts[gm["t1"]] += 1
                pts[gm["t2"]] += 1
    for r in range(rr.nrows):
        if rr.num(r, 1) is not None and rr.text(r, 2) and rr.text(r, 2).upper() != "BYE" \
                and rr.num(r, 8) is not None:
            tm = alias(rr.text(r, 2), aliases)
            if rr.num(r, 8) != pts.get(tm, 0):
                w.warn(f"standings: {tm} source points {rr.num(r, 8):g}, parsed {pts.get(tm, 0):g}")


# ---------------------------------------------------------------------------------------
def _ab(v: str) -> tuple[float, float] | None:
    m = re.match(r"^\s*(-?\d+)\s*-\s*(-?\d+)\s*$", v or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def parse_cast(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
               schools: dict[str, str] | None = None) -> None:
    aliases = aliases or {}
    res = load_grids(t.raw("results.xlsx"))
    for team, school in (schools or {}).items():
        w.team(team, school=school)
    pre = res["Prelims"]
    games: list[dict[str, Any]] = []
    for r, c in pre.find(r"^RECORD$"):
        pool = pre.text(r, 0)
        cols = {cc: pre.text(r, cc) for cc in range(1, c) if pre.text(r, cc)}
        rows = {}
        rr = r + 1
        while rr < pre.nrows and pre.text(rr, 0):
            rows[pre.text(rr, 0)] = rr
            rr += 1
        done = set()
        for a, ra in rows.items():
            for cc, b in cols.items():
                if a == b or frozenset((a, b)) in done:
                    continue
                v = _ab(pre.text(ra, cc))
                if not v:
                    continue
                done.add(frozenset((a, b)))
                back = _ab(pre.text(rows[b], next(k for k, x in cols.items() if x == a)))
                if back and back != (v[1], v[0]):
                    w.warn(f"{pool}: {a} vs {b} cells disagree ({v} / {back})")
                games.append({"t1": alias(a, aliases), "t2": alias(b, aliases), "s1": v[0],
                              "s2": v[1], "stage": "rr", "round": "", "seq": 1,
                              "division": pool})
        # record cross-check
        for a, ra in rows.items():
            rec = _ab(pre.text(ra, c))
            ta = alias(a, aliases)
            mine = [0, 0]
            for gm in games:
                if gm.get("division") == pool and ta in (gm["t1"], gm["t2"]):
                    me, other = (gm["s1"], gm["s2"]) if gm["t1"] == ta else (gm["s2"], gm["s1"])
                    mine[0 if me > other else 1] += 1
            if rec and tuple(mine) != rec:
                w.warn(f"{pool}: {a} record {rec}, parsed {tuple(mine)}")
    # knockout tabs: team / 'vs' + label + "a - b" / team
    order = ["Round of 16", "Round of 8", "Round of 4", "Round of 2"]
    labels = {"Round of 16": "Octofinals", "Round of 8": "Quarterfinals",
              "Round of 4": "Semifinals", "Round of 2": "Final"}
    advanced: dict[str, set[str]] = {}
    for k, tab in enumerate(order):
        g = res[tab]
        teams_in = set()
        pairs = []
        for r in range(g.nrows):
            if g.text(r, 0).lower() == "vs":
                a, b = g.text(r - 1, 0), g.text(r + 1, 0)
                pairs.append((a, b, _ab(g.text(r, 2))))
                teams_in |= {a, b}
        advanced[tab] = teams_in
        for a, b, sc in pairs:
            gm = {"t1": alias(a, aliases), "t2": alias(b, aliases), "stage": "playoff",
                  "round": labels[tab], "seq": 2 + k, "s1": None, "s2": None}
            if sc:
                gm["s1"], gm["s2"] = sc
            else:
                nxt = order[k + 1] if k + 1 < len(order) else None
                if nxt is None:
                    w.warn(f"{tab}: {a} vs {b} has no score and no later round; omitted")
                    continue
                gm["_pending_next"] = nxt
            gm["_ab"] = (a, b)
            games.append(gm)
    for gm in games:
        nxt = gm.pop("_pending_next", None)
        a, b = gm.pop("_ab", (None, None))
        if nxt:
            win = [x for x in (a, b) if x in advanced[nxt]]
            if len(win) != 1:
                w.warn(f"{gm['round']}: cannot tell the winner of {a} vs {b}")
                gm["omit"] = True
                continue
            gm["result"] = "1" if win[0] == a else "2"
            gm["notes"] = f"winner from the {nxt} tab; score not reported"
    _write_games(w, [g for g in games if not g.get("omit")])
