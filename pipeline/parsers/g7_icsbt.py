"""g7: sheets built on the "ICSBT 2 Tournament Hub" template.

South Clemens Bonanza 2025 and NSSB 2026 share it: ``Field``, ``RR Groups`` (code -> team),
``Schedule + Room Assignments`` ("B1–B6" pairings per RR round), ``RR Scores`` (one grid
per group, row = team's own score), ``DE Seeding`` and a ``DE Bracket`` sheet whose columns
are rounds of ``team | score`` cells. South Clemens also has a stats workbook with
``Player | C | I | P | TUH | Games | Total Points | ...`` tabs per subject (RR only).
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import Grid, load_grids
from .g7_bsb import emit_rr
from .g7_common import (Teams, bracket_check, bracket_entries, bracket_pairs,
                        emit_bracket, grid_pairs, split_code_name)


def _groups(g: Grid, teams: Teams) -> None:
    for r, c in g.find(r"^[a-zA-Z]\d$"):
        name = g.text(r, c + 1)
        if name and name.upper() != "BYE":
            teams.add_code(g.text(r, c), teams.resolve(name) or name)


def _rr_blocks(g: Grid, teams: Teams, w: TournamentWriter, max_row: int | None = None):
    for hr, wc in g.find(r"^Wins$"):
        if max_row is not None and hr >= max_row:
            continue
        cols = [(c, teams.resolve(g.text(hr, c))) for c in range(2, wc)]
        cols = [(c, t) for c, t in cols if t]
        rows = []
        r = hr + 1
        while r < g.nrows and g.text(r, 1):
            tm = teams.resolve(g.text(r, 1))
            if tm:
                rows.append((r, tm))
            elif g.text(r, 1).upper() != "BYE":
                w.warn(f"RR Scores row {r}: unknown team {g.text(r, 1)!r}")
            r += 1
        yield rows, cols


def _schedule(g: Grid, teams: Teams) -> dict[frozenset, int]:
    out = {}
    hdr = None
    for r in range(g.nrows):
        if any(re.match(r"^RR\s*\d+$", x) for x in g.row_texts(r)):
            hdr = r
            break
    if hdr is None:
        return out
    for c in range(g.ncols):
        m = re.match(r"^RR\s*(\d+)$", g.text(hdr, c))
        if not m:
            continue
        for r in range(hdr + 1, g.nrows):
            parts = re.split(r"\s*[–—-]\s*", g.text(r, c))
            if len(parts) == 2:
                a, b = teams.codes.get(parts[0].upper()), teams.codes.get(parts[1].upper())
                if a and b:
                    out[frozenset((a, b))] = int(m.group(1))
    return out


def parse(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
          de_rows: list[int] | None = None, de_ignore: list[list[int]] = (),
          de_infer_only_cols: list[int] = (), champion: str | None = None,
          de_header_row: int = 0, stats: bool = False, de_embedded_scores: bool = False) -> None:
    res = load_grids(t.raw("results.xlsx"))
    teams = Teams()
    scores = res["RR Scores"]
    # team names as written in the score grids are canonical
    for hr, wc in scores.find(r"^Wins$"):
        for c in range(2, wc):
            n = scores.text(hr, c)
            if n and n.upper() != "BYE":
                teams.add(n)
    for a, n in (aliases or {}).items():
        teams.alias(a, n)
    _groups(res["RR Groups"], teams)
    for n in teams.names:
        w.team(n)

    rounds = _schedule(res["Schedule + Room Assignments"], teams)
    seen: set[frozenset] = set()
    for rows, cols in _rr_blocks(scores, teams, w):
        if not rows or not cols:
            continue
        # the sheet repeats the grids further down (a W/L helper copy); keep the first copy
        key = frozenset(t for _, t in rows)
        if key in seen:
            continue
        seen.add(key)
        emit_rr(w, grid_pairs(scores, rows, cols, w=w, label="RR Scores"), rounds)

    g = res["DE Bracket"]
    r0, r1 = (de_rows or [0, None])
    ents = bracket_entries(g, teams, rows=(r0, r1), ignore=[tuple(x) for x in de_ignore],
                           embedded=de_embedded_scores)
    games = bracket_pairs(ents, w=w, champion=teams.resolve(champion) if champion else None,
                          infer_only_cols=de_infer_only_cols)
    bracket_check(games, w)
    heads = sorted({c for c in range(g.ncols) if g.text(de_header_row, c)})
    round_of = {}
    for c in ents:
        hs = [h for h in heads if h <= c]
        round_of[c] = f"DE{len(hs)}" if hs else ""
    emit_bracket(w, games, round_of=round_of, seq0=10)

    if stats:
        _stats(t, w, teams)


def _stats(t: Tournament, w: TournamentWriter, teams: Teams) -> None:
    st = load_grids(t.raw("stats.xlsx"))
    # tab -> subject
    for tab, g in st.items():
        subj = normalize_subject(re.sub(r"\bRR\b|\bSTATS\b", " ", tab, flags=re.I))
        if not subj:
            w.warn(f"stats tab {tab!r}: unknown subject")
            continue
        hdr = [h.lower() for h in g.row_texts(0)]
        ci = {k: hdr.index(k) for k in ("player", "c", "i", "p", "tuh", "games", "total points")}
        coded: dict[tuple[str, str], str] = {}   # (first, last-initial) -> (team, name)
        rows = []
        for r in range(1, g.nrows):
            raw = g.text(r, ci["player"])
            if not raw:
                continue
            code, name = split_code_name(raw)
            code = code.rstrip("-")
            m = re.match(r"^([a-zA-Z]\d)-\s+(.+)$", raw)
            if m:  # "b4- ruikang w": same player, second MODAQ id
                code, name = m.group(1).upper(), m.group(2)
            vals = {k: g.num(r, ci[k]) for k in ("c", "i", "p", "tuh", "games", "total points")}
            team = teams.codes.get(code) if code else None
            rows.append([raw, code, name, team, vals])
            if team:
                parts = name.lower().split()
                if len(parts) >= 2:
                    coded.setdefault((parts[0], parts[-1][0]), (team, name))
        # rows without a team code: "Name(TEAM)" or a full name matching one coded player
        for row in rows:
            raw, code, name, team, vals = row
            if team:
                continue
            m = re.match(r"^(.+?)\s*\((.+)\)$", raw)
            if m and teams.resolve(m.group(2)):
                tm = teams.resolve(m.group(2))
                first = m.group(1).lower().split()[0]
                cands = [v for k, v in coded.items() if k[0] == first and v[0] == tm]
                row[3], row[2] = tm, (cands[0][1] if len(cands) == 1 else m.group(1))
                continue
            parts = raw.lower().split()
            if len(parts) >= 2 and (parts[0], parts[-1][0]) in coded:
                row[3], row[2] = coded[(parts[0], parts[-1][0])]
        agg: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for raw, code, name, team, vals in rows:
            if not team:
                if tab == next(iter(st)):
                    w.warn(f"stats: no team for {raw!r}; skipped")
                continue
            a = agg[(name, team)]
            for k, v in vals.items():
                a[k] += v or 0
        for (name, team), a in agg.items():
            w.player_stat(name, team, subj, scope="rr", gp=a["games"],
                          tuh=a["tuh"],
                          correct=a["c"], zeros=a["i"], negs=a["p"], points=a["total points"])
