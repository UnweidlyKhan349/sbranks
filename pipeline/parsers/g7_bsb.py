"""g7: online invitationals built on the "BSB / Texas Science Bowl" sheet family.

* Texas Invitational 2025 (pool grids + G-numbered DE bracket + MODAQ-style stats tabs
  ``# Games Played | # Tossups | # Buzzes | PPG | NPG | Accuracy | Name``),
* Texas Science Bowl 2026 (two Swiss groups + DE bracket + ``Player | Games | TUH | PPG | NPG``),
* Hunter Invitational 2025 (pool grids + 8-team DE + ``RR Indiv Stats`` with subject points),
* BASH 2025 (pool grids + 32-team DE + ``name | gamesPlayed | tuh | buzzes | ppg | npg | accuracy``).
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import Grid, load_grids
from .g7_common import (Pair, Teams, bracket_check, bracket_entries, bracket_pairs,
                        bracket_team_name, column_labels, emit_bracket, exact_points,
                        grid_pairs, rates_to_counts, split_code_name)


# ---------------------------------------------------------------------------------------
# shared pieces
# ---------------------------------------------------------------------------------------
def code_grid_blocks(g: Grid, teams: Teams, header_rx: str = r"^Team$", max_width: int = 10
                     ) -> list[tuple[list[tuple[int, str]], list[tuple[int, str]]]]:
    """Pool blocks: a 'Team' header cell, opponent codes to its right, team codes below."""
    blocks = []
    for hr, hc in g.find(header_rx):
        cols = []
        for c in range(hc + 1, hc + 1 + max_width):
            t = g.text(hr, c)
            if not t:
                continue
            tm = teams.resolve(t)
            if tm is None:
                break
            cols.append((c, tm))
        rows = []
        r = hr + 1
        while r < g.nrows and teams.resolve(g.text(r, hc)):
            rows.append((r, teams.resolve(g.text(r, hc))))
            r += 1
        if cols and rows:
            blocks.append((rows, cols))
    return blocks


def vs_schedule(g: Grid, teams: Teams, round_header_rx: str = r"^Game\s*(\d+)$") -> dict[frozenset, int]:
    """'A1 vs A4' cells under 'Game k' column headers -> {pair: k}."""
    out: dict[frozenset, int] = {}
    for r, c in g.find(r"^\S+\s+vs\.?\s+\S+$"):
        a, b = re.split(r"\s+vs\.?\s+", g.text(r, c), flags=re.I)
        ta, tb = teams.resolve(a), teams.resolve(b)
        if not ta or not tb:
            continue
        for rr in range(r - 1, -1, -1):
            m = re.match(round_header_rx, g.text(rr, c), re.I)
            if m:
                out[frozenset((ta, tb))] = int(m.group(1))
                break
    return out


def emit_rr(w: TournamentWriter, pairs: list[Pair], rounds: dict[frozenset, int] | None,
            forfeit_teams: set[str] = frozenset(), label: str = "RR") -> None:
    rounds = rounds or {}
    for p in sorted(pairs, key=lambda p: (rounds.get(frozenset((p.team1, p.team2)), 99), p.team1)):
        rnd = rounds.get(frozenset((p.team1, p.team2)))
        if rnd is None:
            w.warn(f"{label}: no round for {p.team1} vs {p.team2}")
        ff = p.forfeit or bool({p.team1, p.team2} & forfeit_teams)
        if ff:
            res = "1" if (p.score1 or 0) > (p.score2 or 0) else "2"
            w.game(p.team1, p.team2, stage="rr", round=rnd or "", seq=rnd or 1, result=res,
                   forfeit=True, notes=f"forfeit (sheet shows {p.score1:g}-{p.score2:g})"
                   if p.score1 is not None and p.score2 is not None else "forfeit")
        else:
            w.game(p.team1, p.team2, p.score1, p.score2, stage="rr", round=rnd or "",
                   seq=rnd or 1, result=p.result, notes=p.notes)


def de_round_labels(g: Grid, header_row: int, cols) -> dict[int, str]:
    """Bracket column -> 'DE<k>' using the order of the header cells (times / DE#)."""
    cols = list(cols)
    lab = column_labels(g, [header_row], cols)
    first = min(cols) if cols else 0
    heads = sorted({c for c in range(first, g.ncols) if g.text(header_row, c)})
    out = {}
    for c in cols:
        hs = [h for h in heads if h <= c]
        out[c] = f"DE{len(hs)}" if hs else lab.get(c, "")
    return out


def modaq_rows(g: Grid, cols: dict[str, int]):
    """Yield dicts of the MODAQ-export columns for every data row."""
    for r in range(1, g.nrows):
        name = g.text(r, cols["name"])
        if not name:
            continue
        yield {k: (g.text(r, c) if k == "name" else g.num(r, c)) for k, c in cols.items()}


def put_modaq(w: TournamentWriter, player: str, team: str, subj: str, scope: str, d: dict,
              subject_tuh: bool = True) -> None:
    put_modaq_rows(w, player, team, subj, scope, [d], subject_tuh)


def put_modaq_rows(w: TournamentWriter, player: str, team: str, subj: str, scope: str,
                   ds: list[dict], subject_tuh: bool = True) -> None:
    """Write one stat row from one or more MODAQ rows of the same player (summed)."""
    gp = sum(d.get("gp") or 0 for d in ds) or None
    tuh = None
    if subj == "overall" or subject_tuh:
        tuhs = [d.get("tuh") for d in ds]
        tuh = sum(tuhs) if None not in tuhs else None
    cnts = [rates_to_counts(d.get("gp"), d.get("buzzes"), d.get("ppg"), d.get("npg"), d.get("acc"))
            for d in ds]
    if all(cnts):
        tot = {k: sum(c[k] for c in cnts) for k in ("correct", "zeros", "negs", "points")}
        w.player_stat(player, team, subj, scope=scope, gp=gp, tuh=tuh, **tot)
        return
    pts = [exact_points(d.get("ppg"), d.get("gp")) for d in ds]
    bad = [d for d, c in zip(ds, cnts) if not c]
    w.warn(f"{player} [{team}] {subj} {scope}: counts not exact for "
           + "; ".join(f"gp={d.get('gp')} buzzes={d.get('buzzes')} ppg={d.get('ppg')} "
                       f"npg={d.get('npg')} acc={d.get('acc')}" for d in bad) + "; kept points/ppg")
    if None not in pts:
        w.player_stat(player, team, subj, scope=scope, gp=gp, tuh=tuh, points=sum(pts))
    elif len(ds) == 1:
        w.player_stat(player, team, subj, scope=scope, gp=gp, tuh=tuh, ppg=ds[0].get("ppg"))
    else:
        w.warn(f"{player} [{team}] {subj} {scope}: cannot combine split rows; skipped")


def emit_modaq(w: TournamentWriter, rows: list[tuple[str, str, str, str, dict]],
               subject_tuh: bool = True, check_gp: bool = True) -> None:
    """rows = [(player, team, subject, scope, d)]. Duplicate player rows (MODAQ splits a player
    whose id changed) are summed; rows whose games exceed the team's games are dropped."""
    games = team_game_counts(w)
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for player, team, subj, scope, d in rows:
        grouped[(player, team, subj, scope)].append(d)
    bad = set()
    for (player, team, subj, scope), ds in grouped.items():
        gp = sum(d.get("gp") or 0 for d in ds)
        n = games.get((team, scope))
        if check_gp and n is not None and gp > n:
            bad.add((player, team, scope))
    for k in sorted(bad):
        w.warn(f"{k[0]} [{k[1]}] {k[2]}: games played exceed the team's {games[(k[1], k[2])]} "
               f"games in that stage; this player's {k[2]} rows dropped")
    for (player, team, subj, scope), ds in grouped.items():
        if (player, team, scope) in bad:
            continue
        put_modaq_rows(w, player, team, subj, scope, ds, subject_tuh)


def team_game_counts(w: TournamentWriter) -> dict[tuple[str, str], int]:
    """{(team, scope): games} from the games written so far (forfeits excluded)."""
    out: dict[tuple[str, str], int] = defaultdict(int)
    for g in w.rows["games"]:
        if g["forfeit"]:
            continue
        scope = "rr" if g["stage"] == "rr" else "playoff"
        for t in (g["team1"], g["team2"]):
            out[(t, scope)] += 1
            out[(t, "all")] += 1
    return dict(out)


# ---------------------------------------------------------------------------------------
# Texas Invitational 2025
# ---------------------------------------------------------------------------------------
def parse_texas_2025(t: Tournament, w: TournamentWriter, forfeit_codes: list[str] = (),
                     subject_tuh: bool = True) -> None:
    res = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    tl = res["Team List"]
    for r in range(tl.nrows):
        code, name = tl.text(r, 1), tl.text(r, 2)
        if re.match(r"^[A-Z]\d$", code) and name:
            teams.add_code(code, name)
            w.team(name)
    ff = {teams.codes[c] for c in forfeit_codes}

    rounds = vs_schedule(res["RR Games"], teams)
    for rows, cols in code_grid_blocks(res["RR Tables"], teams):
        emit_rr(w, grid_pairs(res["RR Tables"], rows, cols, w=w, label="RR Tables"), rounds, ff)

    g = res["Bracket"]
    ents = bracket_entries(g, teams, cols=(0, 21))
    games = bracket_pairs(ents, w=w)
    bracket_check(games, w)
    emit_bracket(w, games, round_of=de_round_labels(g, 0, ents.keys()), seq0=10)

    st = load_grids(t.raw("stats.xlsx"))
    cols = {"gp": 0, "tuh": 1, "buzzes": 2, "ppg": 3, "npg": 4, "acc": 5, "name": 6}
    rows = []
    for tab, gr in st.items():
        m = re.match(r"^(RR|DE)\s+(.+)$", tab)
        if not m:
            continue
        scope = "rr" if m.group(1) == "RR" else "playoff"
        subj = normalize_subject(m.group(2))
        if not subj:
            w.warn(f"stats tab {tab!r}: unknown subject")
            continue
        for d in modaq_rows(gr, cols):
            code, player = split_code_name(d["name"])
            team = teams.codes.get(code)
            if not team:
                w.warn(f"{tab}: no team for {d['name']!r}; skipped")
                continue
            rows.append((player, team, subj, scope, d))
    emit_modaq(w, rows, subject_tuh)


# ---------------------------------------------------------------------------------------
# Texas Science Bowl 2026 (Swiss)
# ---------------------------------------------------------------------------------------
def parse_texas_2026(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
                     swiss_tabs: list[str] = ("Jester Swiss", "Kins Swiss")) -> None:
    res = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    swiss_games = []
    for tab in swiss_tabs:
        g = res[tab]
        rnd = 0
        prev_blank = True
        for r in range(1, g.nrows):
            a, b = g.text(r, 0), g.text(r, 3)
            s1, s2 = g.num(r, 1), g.num(r, 2)
            if not a and not b:
                prev_blank = True
                continue
            if prev_blank:
                rnd += 1
                prev_blank = False
            if not a or not b:
                w.warn(f"{tab} r{r}: incomplete pairing {a!r} vs {b!r}")
                continue
            swiss_games.append((tab, rnd, teams.add(a), teams.add(b), s1, s2))
    groups = res["Swiss Groups"]
    for r in range(1, groups.nrows):
        for c in (0, 1):
            n = groups.text(r, c)
            if n and not teams.resolve(n):
                stripped = re.sub(r"\s+(HS|High School)$", "", n)
                if teams.resolve(stripped):
                    teams.alias(n, stripped)
                else:
                    w.warn(f"Swiss Groups team {n!r} not in Swiss rounds")
    for a, n in (aliases or {}).items():
        teams.alias(a, n)
    for n in teams.names:
        w.team(n)
    for tab, rnd, a, b, s1, s2 in swiss_games:
        if s1 is None or s2 is None:
            w.warn(f"{tab} round {rnd}: {a} vs {b} has no score")
            continue
        w.game(a, b, s1, s2, stage="rr", round=f"Swiss {rnd}", seq=rnd,
               notes=f"{tab.split()[0]} Swiss group")

    g = res["DE Bracket"]
    ents = bracket_entries(g, teams, cols=(1, 21))
    games = bracket_pairs(ents, w=w)
    bracket_check(games, w)
    emit_bracket(w, games, round_of=de_round_labels(g, 1, ents.keys()), seq0=10)

    st = load_grids(t.raw("stats.xlsx"))
    acc: dict[tuple[str, str, str], list[tuple]] = defaultdict(list)
    for tab in ("overall", "math", "physics", "chemistry", "earth and space", "biology"):
        gr = st[tab]
        subj = normalize_subject(tab)
        for r in range(1, gr.nrows):
            raw = gr.text(r, 0)
            if not raw:
                continue
            nm, tm = bracket_team_name(raw)
            team = teams.resolve(tm)
            if not team:
                w.warn(f"{tab}: no team for {raw!r}; skipped")
                continue
            player = nm[len(tm):].strip() if nm.startswith(tm) else nm
            acc[(player, team, subj)].append(tuple(gr.num(r, c) for c in range(1, 5)))
    games = team_game_counts(w)
    for (player, team, subj), parts in acc.items():
        # MODAQ sometimes splits one player into two rows (new player id); sum them
        gp = sum(p[0] or 0 for p in parts)
        tuh = sum(p[1] for p in parts) if all(p[1] is not None for p in parts) else None
        if gp > games.get((team, "rr"), 99):
            w.warn(f"{player} [{team}] {subj}: {gp} games > team's {games.get((team, 'rr'))}; skipped")
            continue
        pts_l = [exact_points(p[2], p[0]) for p in parts]
        neg_l = [exact_points(p[3], p[0]) for p in parts]
        if None in pts_l:
            w.warn(f"{player} [{team}] {subj}: ppg x gp not integral {parts}")
            if len(parts) == 1:
                w.player_stat(player, team, subj, scope="rr", gp=gp, tuh=tuh, ppg=parts[0][2])
            continue
        pts = sum(pts_l)
        correct = negs = None
        if None not in neg_l:
            negs = sum(neg_l)
            c = (pts + 4 * negs) / 4
            if abs(c - round(c)) < 1e-9 and c >= 0:
                correct = c
            else:
                negs = None
        w.player_stat(player, team, subj, scope="rr", gp=gp, tuh=tuh, correct=correct,
                      negs=negs, points=pts)


# ---------------------------------------------------------------------------------------
# Hunter Invitational 2025
# ---------------------------------------------------------------------------------------
def parse_hunter_2025(t: Tournament, w: TournamentWriter, forfeit_codes: list[str] = (),
                      schools: dict[str, str] | None = None) -> None:
    res = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    # school hints: third column of the roster/payment tab (e.g. 'SUN' -> 'Canyon Crest Academy A')
    hints = dict(schools or {})
    rp = res.get("Teams RosterPayment")
    if rp is not None:
        for r in range(1, rp.nrows):
            n, sch = rp.text(r, 0), rp.text(r, 2)
            if n and sch and not re.search(r"community", sch, re.I):
                hints.setdefault(n, re.sub(r"\s+[A-D]$", "", sch))
    td = res["TeamsDivisions"]
    for r in range(td.nrows):
        code, name = td.text(r, 0), td.text(r, 1)
        if re.match(r"^[A-Z]\d$", code) and name:
            teams.add_code(code, name)
            w.team(name, school=hints.get(name, ""))
    ff = {teams.codes[c] for c in forfeit_codes}
    rounds = vs_schedule(res["RR Games"], teams)
    g = res["RR Scores"]
    for rows, cols in code_grid_blocks(g, teams):
        emit_rr(w, grid_pairs(g, rows, cols, w=w, label="RR Scores"), rounds, ff)

    g = res["Elimination Bracket"]
    ents = bracket_entries(g, teams, cols=(0, 13))
    games = bracket_pairs(ents, w=w)
    bracket_check(games, w)
    lab = {1: "Upper 1 / Lower 1", 3: "Lower 2", 5: "Upper 2 / Lower 3", 7: "Lower 4",
           9: "Finals 1", 11: "Finals 2"}
    emit_bracket(w, games, round_of={c: lab.get(c, f"col{c}") for c in ents}, seq0=10)

    st = load_grids(t.raw("stats.xlsx"))["RR Indiv Stats"]
    hdr = st.row_texts(0)
    subj_cols = {}
    for c, h in enumerate(hdr):
        if c >= 5 and h and "ppg" not in h.lower():
            s = normalize_subject(h)
            if s:
                subj_cols[s] = c
    for r in range(1, st.nrows):
        tm_raw, player = st.text(r, 0), st.text(r, 1)
        if not tm_raw or not player:
            continue
        team = teams.resolve(tm_raw)
        if not team:
            w.warn(f"RR Indiv Stats: unknown team {tm_raw!r}")
            continue
        gp = st.num(r, 2)
        w.player_stat(player, team, "overall", scope="rr", gp=gp, points=st.num(r, 3))
        for s, c in subj_cols.items():
            w.player_stat(player, team, s, scope="rr", gp=gp, points=st.num(r, c))


# ---------------------------------------------------------------------------------------
# BASH 2025
# ---------------------------------------------------------------------------------------
def parse_bash_2025(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None) -> None:
    res = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    gg = res["RR Groups"]
    for r, c in gg.find(r"^[A-G]\d$"):
        name = gg.text(r, c + 1)
        if name:
            teams.add_code(gg.text(r, c), name)
            w.team(name)
    for a, n in (aliases or {}).items():
        teams.alias(a, n)

    sched = res["RR Schedule"]
    rounds: dict[frozenset, int] = {}
    cur = None
    for r in range(sched.nrows):
        m = re.match(r"^Round\s*(\d+)", sched.text(r, 1), re.I)
        if m:
            cur = int(m.group(1))
        elif not sched.text(r, 2) or sched.text(r, 2) == "Team 1":
            if not any(sched.row_texts(r)[2:]):
                cur = None
            continue
        if cur is None:
            continue
        for c in range(2, sched.ncols - 1, 3):
            a, b = teams.resolve(sched.text(r, c)), teams.resolve(sched.text(r, c + 1))
            if a and b:
                rounds[frozenset((a, b))] = cur

    g = res["RRScoring"]
    for rows, cols in code_grid_blocks(g, teams):
        emit_rr(w, grid_pairs(g, rows, cols, w=w, label="RRScoring"), rounds)

    g = res["DE Bracket"]
    ents = bracket_entries(g, teams, rows=(2, None), cols=(0, 17))
    games = bracket_pairs(ents, w=w)
    bracket_check(games, w)
    emit_bracket(w, games, round_of=de_round_labels(g, 0, ents.keys()), seq0=10)

    st = load_grids(t.raw("stats.xlsx"))
    cols = {"name": 0, "gp": 1, "tuh": 2, "buzzes": 3, "ppg": 4, "npg": 5, "acc": 6}
    rows = []
    for tab, gr in st.items():
        if tab.lower() == "negs":
            continue  # same rows as Overall, sorted by negs
        subj = normalize_subject(tab)
        if not subj:
            w.warn(f"stats tab {tab!r}: unknown subject")
            continue
        for d in modaq_rows(gr, cols):
            code, player = split_code_name(d["name"])
            team = teams.codes.get(code)
            if not team:
                w.warn(f"{tab}: no team for {d['name']!r}; skipped")
                continue
            rows.append((player, team, subj, "rr", d))
    # subject tabs repeat the whole-game TUH, so only the overall row keeps it
    emit_modaq(w, rows, subject_tuh=False)
