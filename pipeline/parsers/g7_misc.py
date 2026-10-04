"""g7: the remaining one-off online invitationals.

* FE!M 2025, National ChemBowl 2026, CLASH HS 2026 - pool grids with ``score | W/L`` cell
  pairs, schedules, ``Stage``-labelled DE brackets (FE!M also has per-player rate stats).
* THUMB 2025 - two-person teams; ``W/L | score`` grids, single-elimination bracket, per-player PPG.
* Lexington Biology Bowl 2026 - per-round results list + schedule, DE bracket.
* Clements Invitational 2025 - pool grids (column = scoring team) + "130-48" style DE bracket
  + per-subject RR / DE stats tabs.
* NWI 2 2025 - pool grids + DE bracket (+ rosters); NSI 2 2024 - single SE bracket tab.
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name
from ..util.grid import Grid, load_grids
from .g7_bsb import emit_rr, team_game_counts
from .g7_common import (BYE_RX, BGame, Pair, Teams, bracket_check, bracket_entries,
                        bracket_pairs, bracket_team_name, emit_bracket, exact_points,
                        grid_pairs, split_code_name)


# ---------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------
def header_blocks(g: Grid, teams: Teams, boundary_rx: str, *, group_size: int = 6, step: int = 2,
                  register: bool = True, w: TournamentWriter | None = None,
                  max_row: int | None = None) -> list[tuple[list, list, int]]:
    """Grid blocks found from a boundary header cell ('Wins', 'Points', 'Lost', 'PPG', ...).

    The opponent names sit at ``bc - step*k`` (k = group_size..1) of the header row and the
    team names in the column just left of the first opponent column, in the rows below.
    Returns [(rows, cols, name_col)].
    """
    out = []
    for hr, bc in g.find(boundary_rx):
        if max_row is not None and hr >= max_row:
            continue
        hcols = [bc - step * k for k in range(group_size, 0, -1)]
        if hcols[0] < 1:
            continue
        name_col = hcols[0] - 1
        cols = []
        for c in hcols:
            t = g.text(hr, c)
            if not t or BYE_RX.match(t):
                continue
            if register and not teams.resolve(t):
                teams.add(t)
            tm = teams.resolve(t)
            if tm:
                cols.append((c, tm))
        rows = []
        for r in range(hr + 1, min(g.nrows, hr + 1 + group_size + 3)):
            if any(re.search(boundary_rx, x, re.I) for x in g.row_texts(r) if x):
                break
            t = g.text(r, name_col)
            if not t or BYE_RX.match(t):
                continue
            tm = teams.resolve(t)
            if tm is None:
                if w and cols and len(rows) < len(cols):
                    w.warn(f"{g.title} r{r}: row team {t!r} not in header")
                if len(rows) >= len(cols):
                    break
                continue
            rows.append((r, tm))
        if cols and rows:
            out.append((rows, cols, name_col))
    return out


def code_map_from_blocks(g: Grid, blocks, code_col_offset: int = -1) -> dict[str, str]:
    """Team codes written just left of the team-name column (e.g. 'A1 | Name')."""
    out = {}
    for rows, _, name_col in blocks:
        for r, tm in rows:
            code = g.text(r, name_col + code_col_offset)
            if re.match(r"^[A-Za-z]\d$", code):
                out[code.upper()] = tm
    return out


def emit_bracket_tab(w: TournamentWriter, g: Grid, teams: Teams, *, rows=(0, None), cols=(0, None),
                     header_row: int | None = 0, score_below: bool = False, ignore=(),
                     infer_only_cols=(), champion: str | None = None, max_losses: int = 2,
                     labels: dict[int, str] | None = None, stage: str = "playoff",
                     forfeit_pairs=()) -> list[BGame]:
    ents = bracket_entries(g, teams, rows=tuple(rows), cols=tuple(cols), score_below=score_below,
                           ignore=[tuple(x) for x in ignore])
    games = bracket_pairs(ents, w=w, champion=teams.resolve(champion) if champion else None,
                          infer_only_cols=infer_only_cols)
    bracket_check(games, w, max_losses=max_losses)
    round_of = dict(labels or {})
    if header_row is not None:
        heads = sorted({c for c in range(g.ncols) if g.text(header_row, c)})
        for c in ents:
            if c in round_of:
                continue
            hs = [h for h in heads if h <= c]
            lbl = clean_name(g.text(header_row, hs[-1])) if hs else ""
            m = re.match(r"^((?:DE/SE|DE|SE)\s*\d+)\b", lbl)
            round_of[c] = m.group(1) if m else lbl
    emit_bracket(w, games, round_of=round_of, seq0=10, stage=stage,
                 forfeit_pairs=[frozenset(teams.resolve(x) for x in p) for p in forfeit_pairs])
    return games


def _aliases(teams: Teams, aliases: dict[str, str] | None) -> None:
    for a, n in (aliases or {}).items():
        teams.alias(a, n)


# ---------------------------------------------------------------------------------------
# FE!M 2025
# ---------------------------------------------------------------------------------------
def parse_fem(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None) -> None:
    wb = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    g = wb["RR Brackets & Scores"]
    blocks = header_blocks(g, teams, r"^Wins$", w=w)
    codes = code_map_from_blocks(g, blocks)
    for code, tm in codes.items():
        teams.add_code(code, tm)
    _aliases(teams, aliases)
    for n in teams.names:
        w.team(n)
    # schedule: 'Round k' rows, code pairs in (Team 1, Team 2) column pairs
    m = wb["RR Matchups"]
    rounds = {}
    cur = None
    for r in range(m.nrows):
        mm = re.match(r"^Round\s*(\d+)", m.text(r, 0), re.I)
        if mm:
            cur = int(mm.group(1))
        if cur is None:
            continue
        for c in range(1, m.ncols - 1):
            a, b = teams.codes.get(m.text(r, c).upper()), teams.codes.get(m.text(r, c + 1).upper())
            if a and b:
                rounds[frozenset((a, b))] = cur
    for rows, cols, _ in blocks:
        emit_rr(w, grid_pairs(g, rows, cols, wl_off=1, w=w, label="RR"), rounds)

    emit_bracket_tab(w, wb["DE Brackets"], teams, rows=(1, None), infer_only_cols=[17])

    # stats: per-player rates only (PP20TUH overall, PP4TUH per subject); no GP/TUH in source
    st = wb["RR Overall PPG"]
    hdr = st.row_texts(0)
    subj_cols = {}
    for c, h in enumerate(hdr):
        if c == 0:
            continue
        hl = h.lower()
        if "neg" in hl:
            continue
        s = "overall" if "overall" in hl else normalize_subject(re.sub(r"pp\d+tuh", "", hl))
        if s:
            subj_cols[s] = c
    for r in range(1, st.nrows):
        raw = st.text(r, 0)
        if not raw:
            continue
        code, player = split_code_name(raw)
        team = teams.codes.get(code)
        if not team:
            w.warn(f"stats: no team for {raw!r}; skipped")
            continue
        for s, c in subj_cols.items():
            v = st.num(r, c)
            if v is not None:
                w.player_stat(player, team, s, scope="rr", ppg=v)


# ---------------------------------------------------------------------------------------
# National ChemBowl 2026
# ---------------------------------------------------------------------------------------
def parse_chembowl(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
                   de_labels: dict[int, str] | None = None) -> None:
    wb = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    g = wb["RR SCORES"]
    blocks = header_blocks(g, teams, r"^Wins$", w=w)
    for code, tm in code_map_from_blocks(g, blocks).items():
        teams.add_code(code, tm)
    _aliases(teams, aliases)
    for n in teams.names:
        w.team(n)
    m = wb["RR MATCHUPS"]
    rounds = {}
    for r in range(m.nrows):
        mm = re.match(r"^Round\s*(\d+)", m.text(r, 0), re.I)
        if not mm:
            continue
        for c in range(1, m.ncols):
            p = re.split(r"\s+vs\.?\s+", m.text(r, c), flags=re.I)
            if len(p) == 2 and p[0].upper() in teams.codes and p[1].upper() in teams.codes:
                rounds[frozenset((teams.codes[p[0].upper()], teams.codes[p[1].upper()]))] = int(mm.group(1))
    for rows, cols, _ in blocks:
        emit_rr(w, grid_pairs(g, rows, cols, wl_off=1, w=w, label="RR"), rounds)
    emit_bracket_tab(w, wb["DE BRACKET"], teams, rows=(2, None), cols=(0, 13),
                     labels={int(k): v for k, v in (de_labels or {}).items()})
    # Player stats (stats.xlsx 'Raw Stats') list players without their team -> not usable.


# ---------------------------------------------------------------------------------------
# CLASH HS 2026
# ---------------------------------------------------------------------------------------
def parse_clash(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
                champion: str | None = None) -> None:
    wb = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    g = wb["HS RR"]
    blocks = header_blocks(g, teams, r"^Points$", register=True, w=None)
    _aliases(teams, aliases)
    blocks = header_blocks(g, teams, r"^Points$", register=False, w=w)
    for n in teams.names:
        w.team(n)
    # HS round-robin schedule: per group, rows after a 'Time' header are RR1..RR5
    s = wb["RR Schedule"]
    rounds = {}
    for hr, hc in s.find(r"^Time$"):
        if hc > 4:
            continue  # middle-school schedule on the right
        k = 0
        for r in range(hr + 1, s.nrows):
            if not s.text(r, hc):
                break
            k += 1
            for c in range(hc + 1, hc + 4):
                p = re.split(r"\s+vs\.?\s+", s.text(r, c), flags=re.I)
                if len(p) == 2:
                    a, b = teams.resolve(p[0]), teams.resolve(p[1])
                    if a and b:
                        rounds[frozenset((a, b))] = k
                    else:
                        w.warn(f"RR Schedule: unknown team in {s.text(r, c)!r}")
    for rows, cols, _ in blocks:
        emit_rr(w, grid_pairs(g, rows, cols, wl_off=1, w=w, label="HS RR"), rounds)
    emit_bracket_tab(w, wb["HS DE"], teams, rows=(1, None), cols=(5, 24), header_row=0,
                     champion=champion)


# ---------------------------------------------------------------------------------------
# THUMB 2025
# ---------------------------------------------------------------------------------------
def parse_thumb(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None) -> None:
    wb = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    g = wb["Round Robin"]
    blocks = header_blocks(g, teams, r"^(P|Pts)$", w=w)
    _aliases(teams, aliases)
    # rosters (real names; Discord handles in the next column)
    field = wb["Field"]
    roster = {}
    for r in range(1, field.nrows):
        tm = teams.resolve(field.text(r, 1))
        if not field.text(r, 1):
            continue
        if not tm:
            w.warn(f"Field team {field.text(r, 1)!r} not in round robin")
            continue
        roster[tm] = [field.text(r, 2), field.text(r, 4)]
    for n in teams.names:
        w.team(n, players=[p for p in roster.get(n, []) if p])
    # schedule by position within a group (same for every group)
    pos_round = {}
    hr = g.find_first(r"^Round$")
    if hr:
        rr, rc = hr
        rnd_cols = {c: int(g.num(rr, c)) for c in range(rc + 1, g.ncols) if g.num(rr, c)}
        for r in range(rr + 1, g.nrows):
            if not g.text(r, rc).lower().startswith("room"):
                continue
            for c, k in rnd_cols.items():
                m = re.match(r"^(\d)\s*v\s*(\d)$", g.text(r, c))
                if m:
                    pos_round[frozenset((int(m.group(1)), int(m.group(2))))] = k
    rounds = {}
    for rows, cols, name_col in blocks:
        pos = {}
        for r, tm in rows:
            p = g.num(r, name_col - 1)
            if p is not None:
                pos[tm] = int(p)
        for a in pos:
            for b in pos:
                if a < b and frozenset((pos[a], pos[b])) in pos_round:
                    rounds[frozenset((a, b))] = pos_round[frozenset((pos[a], pos[b]))]
    for rows, cols, _ in blocks:
        emit_rr(w, grid_pairs(g, rows, cols, score_off=1, wl_off=-1, w=w, label="RR"), rounds)
    emit_bracket_tab(w, wb["Single Elimination"], teams, rows=(4, None), cols=(0, 12),
                     header_row=3, score_below=True, max_losses=1)

    # per-player PPG (RR only): 'A for B' = teammate A's PPG, 'B for A' = teammate B's
    st = load_grids(t.raw("stats.xlsx"))["overall"]
    hdr = st.row_texts(0)
    ca, cb = hdr.index("A for B"), hdr.index("B for A")
    games = team_game_counts(w)
    for r in range(1, st.nrows):
        tm = teams.resolve(st.text(r, 1))
        if not tm:
            if st.text(r, 1):
                w.warn(f"stats: unknown team {st.text(r, 1)!r}")
            continue
        pa, pb = (roster.get(tm) or ["", ""])[:2]
        gp = games.get((tm, "rr"))
        for player, c in ((pa, ca), (pb, cb)):
            v = st.num(r, c)
            if player and v is not None:
                pts = exact_points(v, gp)
                w.player_stat(player, tm, "overall", scope="rr", gp=gp,
                              points=pts if pts is not None and pts % 2 == 0 else None,
                              ppg=None if pts is not None and pts % 2 == 0 else v)


# ---------------------------------------------------------------------------------------
# Lexington Biology Bowl 2026
# ---------------------------------------------------------------------------------------
def parse_lexington_bio(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
                        no_show: list[str] = ()) -> None:
    wb = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    grp = wb["RR Groups"]
    order: dict[str, list[str]] = defaultdict(list)   # group letter -> codes in order
    for r, c in grp.find(r"^[A-Z]\d$"):
        name = grp.text(r, c + 1)
        code = grp.text(r, c)
        teams.add_code(code, teams.add(name))
        order[code[0]].append(code)
    _aliases(teams, aliases)
    ns = {teams.need(x) for x in no_show}
    for n in teams.names:
        w.team(n)
    # schedule: per RR round, code pairs in (Team 1, Team 2) columns
    m = wb["RR Matchups"]
    opp: dict[tuple[str, int], str] = {}
    cur = None
    for r in range(m.nrows):
        mm = re.match(r"^RR\s*(\d+)$", m.text(r, 1))
        if mm:
            cur = int(mm.group(1))
        if cur is None:
            continue
        for c in range(2, m.ncols - 1):
            a, b = teams.codes.get(m.text(r, c)), teams.codes.get(m.text(r, c + 1))
            if a and b:
                opp[(a, cur)] = b
                opp[(b, cur)] = a
    # results: per group block, rows in code order: 'W|score' per round
    res = wb["RR Results"]
    own: dict[tuple[str, int], tuple[str, float]] = {}
    for hr, hc in res.find(r"^RR1$"):
        name_col = hc - 1
        rcols = {}
        for c in range(hc, res.ncols):
            mm = re.match(r"^RR(\d+)$", res.text(hr, c))
            if mm:
                rcols[int(mm.group(1))] = c
            elif res.text(hr, c) == "Total":
                break
        # block letter = group of the first team row
        r = hr + 1
        rows = []
        while r < res.nrows and res.text(r, name_col):
            rows.append(r)
            r += 1
        letter = None
        for L, codes in order.items():
            tm0 = teams.resolve(res.text(rows[0], name_col))
            if tm0 and teams.codes.get(codes[0]) == tm0:
                letter = L
        for i, r in enumerate(rows):
            nm = res.text(r, name_col)
            tm = teams.resolve(nm)
            if tm is None and letter and i < len(order[letter]):
                tm = teams.codes[order[letter][i]]
                teams.alias(nm, tm)   # short name used in the results / DE sheets
            if tm is None:
                w.warn(f"RR Results: cannot place {nm!r}")
                continue
            for k, c in rcols.items():
                own[(tm, k)] = (res.text(r, c).upper(), res.num(r, c + 1))
    done = set()
    for (tm, k), (wl, s) in sorted(own.items(), key=lambda x: (x[0][1], x[0][0])):
        o = opp.get((tm, k))
        if not o or frozenset((tm, o, k)) in done:
            continue
        done.add(frozenset((tm, o, k)))
        wl2, s2 = own.get((o, k), ("", None))
        if s is None or s2 is None:
            w.warn(f"RR{k}: {tm} vs {o} missing score")
            continue
        exp = "W" if s > s2 else "L" if s < s2 else "T"
        if wl and wl != exp:
            w.warn(f"RR{k}: {tm} {s:g}-{s2:g} {o} marked {wl}")
        if tm in ns and o in ns:
            w.warn(f"RR{k}: {tm} vs {o} - both teams absent ({s:g}-{s2:g}); skipped")
            continue
        if tm in ns or o in ns:
            res_ = "1" if o in ns else "2"
            w.game(tm, o, stage="rr", round=k, seq=k, result=res_, forfeit=True,
                   notes=f"opponent did not show up (sheet shows {s:g}-{s2:g})")
            continue
        w.game(tm, o, s, s2, stage="rr", round=k, seq=k)
    emit_bracket_tab(w, wb["DE Bracket"], teams, rows=(2, None), header_row=1)


# ---------------------------------------------------------------------------------------
# Clements Invitational 2025
# ---------------------------------------------------------------------------------------
def parse_clements_2025(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None
                        ) -> None:
    wb = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    g = wb["RR Results & Seeding"]
    blocks = header_blocks(g, teams, r"^Lost$", group_size=5, step=1, w=w)
    _aliases(teams, aliases)
    for n in teams.names:
        w.team(n)
    # schedule by pool position (X-1 .. X-5) from 'RR & Schedule'
    sch = wb["RR & Schedule"]
    pos: dict[str, int] = {}
    for r in range(sch.nrows):
        for c in (4, 7):
            p, n = sch.num(r, c), sch.text(r, c + 1)
            if p is not None and teams.resolve(n):
                pos[teams.resolve(n)] = int(p)
    pool_of = {}
    for i, (rows, _, _) in enumerate(blocks):
        for _, tm in rows:
            pool_of[tm] = i
    pos_round = {}
    hr = sch.find_first(r"^Round$")
    if hr:
        rr, rc = hr
        rcols = {c: int(re.sub(r"\D", "", sch.text(rr, c))) for c in range(rc + 1, sch.ncols)
                 if re.match(r"^RR\d$", sch.text(rr, c))}
        for r in range(rr + 1, sch.nrows):
            for c, k in rcols.items():
                m = re.match(r"^X-(\d)\s*vs\s*X-(\d)$", sch.text(r, c))
                if m:
                    pos_round[frozenset((int(m.group(1)), int(m.group(2))))] = k
    rounds = {}
    for a in pos:
        for b in pos:
            if a < b and pool_of.get(a) == pool_of.get(b):
                k = pos_round.get(frozenset((pos[a], pos[b])))
                if k:
                    rounds[frozenset((a, b))] = k

    def forfeit(sa, sb, a, b):
        if sa == -1 or sb == -1:
            return Pair(a, b, sa, sb, forfeit=True)
        return None

    for rows, cols, _ in blocks:
        emit_rr(w, grid_pairs(g, rows, cols, row_scores=False, w=w, label="RR", forfeit=forfeit),
                rounds)

    # DE bracket: "130-48" score cells between the two team cells (top-bottom order),
    # winner written to the right
    de = wb["DE Bracket"]
    games = []
    for r, c in de.find(r"^-?\d+\s*-\s*-?\d+$"):
        a_s, b_s = (float(x) for x in re.match(r"^(-?\d+)\s*-\s*(-?\d+)$", de.text(r, c)).groups())
        up = down = None
        for rr in range(r - 1, -1, -1):
            if teams.resolve(de.text(rr, c - 1)):
                up = (rr, teams.resolve(de.text(rr, c - 1)))
                break
        for rr in range(r + 1, de.nrows):
            if teams.resolve(de.text(rr, c - 1)):
                down = (rr, teams.resolve(de.text(rr, c - 1)))
                break
        if not up or not down:
            w.warn(f"DE: cannot find both teams for score {de.text(r, c)!r} at r{r} c{c}")
            continue
        win = None
        for cc in range(c + 1, de.ncols):
            if teams.resolve(de.text(r, cc)):
                win = teams.resolve(de.text(r, cc))
                break
        exp = up[1] if a_s > b_s else down[1]
        if win and win != exp:
            w.warn(f"DE: {up[1]} {a_s:g}-{b_s:g} {down[1]} but winner written {win}")
        games.append(BGame(c - 1, up[1], down[1], a_s, b_s, "", (up[0], down[0])))
    bracket_check(games, w)
    heads = {c: de.text(0, c) for c in range(de.ncols) if de.text(0, c)}
    emit_bracket(w, games, round_of={c: heads.get(c, "") for c in {gm.col for gm in games}}, seq0=10)

    # stats tabs inside the results workbook: 'RR <Subject>' (round robin) and lowercase
    # '<subject>' tabs (double elimination)
    rows_out = []
    for tab, st in wb.items():
        m = re.match(r"^(RR )?(overall|energy|ess|math|physics|chemistry|biology)$", tab, re.I)
        if not m:
            continue
        scope = "rr" if m.group(1) else "playoff"
        subj = normalize_subject(m.group(2))
        hdr = [h.lower() for h in st.row_texts(0)]
        ci = {k: hdr.index(k) for k in ("games", "buzzes", "correct", "negs", "ppg")}
        for r in range(1, st.nrows):
            raw = re.sub(r"\.\d+$", "", st.text(r, 0))   # 'Name [Team].1' = second MODAQ id
            if not raw:
                continue
            player, tm_raw = bracket_team_name(raw)
            tm = teams.resolve(tm_raw)
            if not tm:
                w.warn(f"{tab}: unknown team in {raw!r}; skipped")
                continue
            v = {k: st.num(r, c) for k, c in ci.items()}
            rows_out.append((player, tm, subj, scope, v))
    games_n = team_game_counts(w)
    agg = defaultdict(lambda: defaultdict(float))
    for player, tm, subj, scope, v in rows_out:
        a = agg[(player.title() if player.islower() else player, tm, subj, scope)]
        for k, x in v.items():
            if k != "ppg":
                a[k] += x or 0
        a["n"] += 1
        if v["ppg"] is not None and v["games"]:
            pts = 4 * (v["correct"] or 0) - 4 * (v["negs"] or 0)
            if abs(pts - v["ppg"] * v["games"]) > 0.02 * v["games"] + 0.01:
                w.warn(f"{player} [{tm}] {subj} {scope}: 4*correct-4*negs={pts:g} but "
                       f"ppg*games={v['ppg'] * v['games']:g}")
    for (player, tm, subj, scope), a in agg.items():
        if a["games"] > games_n.get((tm, scope), 0):
            w.warn(f"{player} [{tm}] {subj} {scope}: {a['games']:g} games > team's "
                   f"{games_n.get((tm, scope))}; skipped")
            continue
        zeros = a["buzzes"] - a["correct"] - a["negs"]
        w.player_stat(player, tm, subj, scope=scope, gp=a["games"], correct=a["correct"],
                      negs=a["negs"], zeros=zeros if zeros >= 0 else None)


# ---------------------------------------------------------------------------------------
# NWI 2 (2025)
# ---------------------------------------------------------------------------------------
def parse_nwi2(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None) -> None:
    wb = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    g = wb["RR Scores"]
    blocks = header_blocks(g, teams, r"^PPG$", group_size=4, step=1, w=w)
    # registration tab: pools in the same order, full names + rosters
    reg = wb["Teams"]
    full: dict[str, tuple[str, list[str]]] = {}
    pool_rows = [r for r in range(reg.nrows) if reg.text(r, 0) and not any(reg.row_texts(r)[1:])]
    blocks_by_name = {}
    for rows, cols, name_col in blocks:
        # pool name is the text above the block in the name column
        for rr in range(rows[0][0] - 1, -1, -1):
            if g.text(rr, name_col) and not teams.resolve(g.text(rr, name_col)):
                blocks_by_name[g.text(rr, name_col).lower()] = [tm for _, tm in cols]
                break
    for i, pr in enumerate(pool_rows):
        pool = reg.text(pr, 0).lower()
        rr_teams = blocks_by_name.get(pool, [])
        hdr_r = pr + 1
        slots = [c for c in (1, 4, 7, 10) if reg.text(hdr_r, c)]
        k = 0
        for c in slots:
            nm = reg.text(hdr_r, c)
            if BYE_RX.match(nm):
                continue
            players = []
            r = hdr_r + 1
            while r < reg.nrows and r not in pool_rows:
                if reg.text(r, c):
                    players.append(reg.text(r, c))
                r += 1
            tm = teams.resolve(nm) or (rr_teams[k] if k < len(rr_teams) else None)
            k += 1
            if not tm:
                w.warn(f"Teams tab: cannot place {nm!r}")
                continue
            teams.alias(nm, tm)
            full[tm] = (nm, players)
    _aliases(teams, aliases)
    for n in teams.names:
        nm, players = full.get(n, ("", []))
        w.team(n, school=nm if nm and nm != n else "", players=players)
    rounds = {}
    rooms = wb["Rooms"]
    for c in range(1, rooms.ncols):
        mm = re.match(r"^RR(\d+)$", rooms.text(0, c))
        if not mm:
            continue
        for r in range(1, rooms.nrows):
            p = re.split(r"\s+v\s*s\s+", rooms.text(r, c))
            if len(p) == 2:
                a, b = teams.resolve(p[0]), teams.resolve(p[1])
                if a and b:
                    rounds[frozenset((a, b))] = int(mm.group(1))
                else:
                    w.warn(f"Rooms: unknown team in {rooms.text(r, c)!r}")
    for rows, cols, _ in blocks:
        emit_rr(w, grid_pairs(g, rows, cols, w=w, label="RR"), rounds)
    emit_bracket_tab(w, wb["Bracket"], teams, rows=(1, None), cols=(0, 17), header_row=0)


# ---------------------------------------------------------------------------------------
# NSI 2 (2024)
# ---------------------------------------------------------------------------------------
def parse_nsi2(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None) -> None:
    g = load_grids(t.raw("results.xlsx"))["Sheet1"]
    teams = Teams()
    for r in range(g.nrows):
        n = g.text(r, 0)
        if n and g.num(r, 1) is not None:
            teams.add(n)
    _aliases(teams, aliases)
    for n in teams.names:
        w.team(n)
    labels = {0: "Round of 16", 2: "Quarterfinals", 4: "Semifinals", 6: "Final"}
    emit_bracket_tab(w, g, teams, rows=(1, None), header_row=None, labels=labels, max_losses=1)
