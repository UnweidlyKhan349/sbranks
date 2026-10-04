""""LiveScoresheet" results template: AVES 2024 and ICSBT 2 2025.

Results workbook tabs: "Team List" (code A1..G6 -> team, plus a roster or RR group),
"RR Pairings and Schedule" (cells "A1 — A2" under RR1..RR5), "LiveScoresheet" (one score
grid per group, labelled by code; "-" marks the BYE slot), "DE Seeding" and "DE Bracket"
(visual 16-team double-elimination bracket with full team names).

AVES stats ("Individual PPG"): one row per player keyed "FirstL" (first name + last initial);
team membership comes from the Team List rosters. Columns: Qs Played (tossups heard) and PPG
(points per 20 tossups) overall, and per subject "<Subj> Qs Played" / "<Subj> PPG" (points per
4 tossups of that subject). Points are recovered as PPG*Qs/20 (overall) and PPG*Qs/4
(subjects); the overall figure is checked against the sum of the subjects.

ICSBT 2 stats (separate workbook, tabs ovr/bio/chem/ess/math/phys/csenergy): rows
"f1 harry g [label]" with GP, TUH, Buzzes, PPG, NPG, Acc. The leading code is the team; a
player is often split over several rows (moderators typed the label differently), so rows
are summed per (team, player).
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import load_grids
from .g4_common import (Counts, Roster, code_pair, derive_counts, exact_int, find_grids,
                        grid_pairs, read_bracket, stat_columns, write_bracket)


def _results(t: Tournament, w: TournamentWriter, results: str, aliases: dict[str, str] | None,
             bracket_opts: dict | None, bracket_forfeits: list[str] | None,
             bracket_notes: dict[str, str] | None) -> tuple[dict[str, str], Roster, dict]:
    g = load_grids(t.raw(results))
    tl = g["Team List"]
    codes: dict[str, str] = {}
    extra: dict[str, str] = {}
    for r in range(tl.nrows):
        code = tl.text(r, 0).upper()
        if re.fullmatch(r"[A-Z]\d", code) and tl.text(r, 1) and tl.text(r, 1).upper() != "BYE":
            codes[code] = tl.text(r, 1)
            extra[code] = tl.text(r, 2)
    roster = Roster(codes.values(), aliases)

    sch = g["RR Pairings and Schedule"]
    round_of: dict[frozenset, int] = {}
    for r in range(sch.nrows):
        for c in range(sch.ncols):
            p = code_pair(sch.cell(r, c))
            if p:
                k = next((int(m.group(1)) for rr in range(r, -1, -1)
                          if (m := re.fullmatch(r"RR\s*(\d+)", sch.text(rr, c)))), None)
                round_of[frozenset(p)] = k

    n_games = defaultdict(int)
    for sg in find_grids(g["LiveScoresheet"]):
        labels = [x.upper() for x in sg.labels]
        for i, j, a, b in grid_pairs(sg):
            ci, cj = labels[i], labels[j]
            if ci not in codes or cj not in codes:
                continue                      # BYE slot
            sa, sb = num(a), num(b)
            k = round_of.get(frozenset((ci, cj)))
            if sa is None or sb is None:
                w.warn(f"RR {ci} vs {cj}: missing score ({a!r}, {b!r})")
                continue
            w.game(codes[ci], codes[cj], sa, sb, stage="rr", round=f"RR{k}" if k else "",
                   seq=k or 0, game_id=f"rr-{ci}{cj}")
            n_games[codes[ci]] += 1
            n_games[codes[cj]] += 1

    games = read_bracket(g["DE Bracket"], roster, **(bracket_opts or {}))
    write_bracket(w, games, forfeits=bracket_forfeits or [], notes=bracket_notes)
    return codes, roster, {"extra": extra, "rr_games": n_games, "bracket": games}


# ---- AVES 2024 -------------------------------------------------------------------------------
def _key(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def parse_aves(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
               aliases: dict[str, str] | None = None, bracket_opts: dict | None = None,
               bracket_forfeits: list[str] | None = None, bracket_notes: dict[str, str] | None = None,
               stats_tab: str = "Individual PPG", player_teams: dict[str, str] | None = None,
               scope: str = "rr") -> None:
    codes, roster, info = _results(t, w, results, aliases, bracket_opts, bracket_forfeits, bracket_notes)
    # rosters: "Advik S, Michael M, ..." -> key 'adviks' -> (display name, team)
    by_key: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for code, team in codes.items():
        names = [clean_name(x) for x in re.split(r"[,;/]", info["extra"].get(code, "")) if clean_name(x)]
        w.team(team, players=names)
        for n in names:
            by_key[_key(n)].append((n, team))
    forced = {k.lower(): v for k, v in (player_teams or {}).items()}

    g = load_grids(t.raw(results))
    x = g[stats_tab]
    hdr = x.row_texts(0)
    ci = {h: i for i, h in enumerate(hdr) if h}
    subj_cols = []
    for h, i in ci.items():
        m = re.fullmatch(r"(.+?) Qs Played", h)
        if m and h != "Qs Played":
            subj = normalize_subject(m.group(1))
            if subj is None or not hdr[i + 1].endswith("PPG"):
                raise ValueError(f"unexpected stats columns {h!r} / {hdr[i + 1]!r}")
            subj_cols.append((subj, i, i + 1))
    for r in range(1, x.nrows):
        raw = x.text(r, ci["Name"])
        if not raw or x.num(r, ci["Qs Played"]) is None:
            continue
        k = _key(raw)
        if raw.lower() in forced:
            hits = [(raw, roster.resolve(forced[raw.lower()]))]
        else:
            hits = by_key.get(k, [])
        if len(hits) != 1:
            w.warn(f"{stats_tab}: player {raw!r} matches {len(hits)} roster entries {hits}; skipped")
            continue
        player, team = hits[0]
        tot = 0
        ok = True
        for subj, qc, pc in subj_cols:
            q, p = x.num(r, qc), x.num(r, pc)
            if q is None or p is None:
                continue
            pts = exact_int(p * q / 4, 0.1) if q else 0
            if pts is None or pts % 4:
                w.warn(f"{raw} {subj}: PPG {p} * {q}/4 is not a whole tossup total")
                ok = False
                continue
            tot += pts
            w.player_stat(player, team, subj, scope=scope, tuh=q, points=pts)
        q, p = x.num(r, ci["Qs Played"]), x.num(r, ci["PPG"])
        est = p * q / 20
        if ok and abs(est - tot) <= 0.05 * q / 20 + 0.01:
            w.player_stat(player, team, "overall", scope=scope, tuh=q, points=tot)
        else:
            w.warn(f"{raw}: overall PPG {p} * {q}/20 = {est:.2f} vs subject sum {tot}; overall points from PPG")
            pts = round(est / 4) * 4
            w.player_stat(player, team, "overall", scope=scope, tuh=q, points=pts if abs(est - pts) < 0.05 * q / 20 + 0.01 else None,
                          ppg=None if abs(est - pts) < 0.05 * q / 20 + 0.01 else p)


# ---- ICSBT 2 2025 ----------------------------------------------------------------------------
TAB_SUBJECTS = {"ovr": "overall", "bio": "biology", "chem": "chemistry", "ess": "ess", "math": "math",
                "phys": "physics", "csenergy": "energy"}


def parse_icsbt(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
                stats: str = "stats.xlsx", aliases: dict[str, str] | None = None,
                bracket_opts: dict | None = None, bracket_forfeits: list[str] | None = None,
                bracket_notes: dict[str, str] | None = None, scope: str = "rr",
                tab_subjects: dict[str, str] | None = None) -> None:
    codes, roster, info = _results(t, w, results, aliases, bracket_opts, bracket_forfeits, bracket_notes)
    gs = load_grids(t.raw(stats))
    tabs = tab_subjects or TAB_SUBJECTS
    for tab, subj in tabs.items():
        x = gs[tab]
        cols = stat_columns(x.row_texts(0))
        tot: dict[tuple[str, str], Counts] = {}
        display: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in range(1, x.nrows):
            raw = x.text(r, 0)
            if not raw or x.num(r, cols["gp"]) is None:
                continue
            m = re.match(r"([a-gA-G]\d)\s+(.*?)\s*(\[.*\])?\s*$", raw)
            if not m or m.group(1).upper() not in codes:
                w.warn(f"{tab}: cannot place {raw!r}")
                continue
            team = codes[m.group(1).upper()]
            name = clean_name(m.group(2))
            key = (team, name.lower())
            display[key][name] += 1
            get = lambda k: x.cell(r, cols[k]) if k in cols else None  # noqa: E731
            cn = derive_counts(get("gp"), get("tuh"), get("buzzes"), ppg=get("ppg"), npg=get("npg"),
                               acc=get("acc"))
            if cn.problem:
                w.warn(f"{tab} {raw!r}: {cn.problem}")
            if key in tot:
                a = tot[key]
                for f in ("gp", "tuh", "buzzes", "correct", "negs", "points", "zeros"):
                    va, vb = getattr(a, f), getattr(cn, f)
                    setattr(a, f, va + vb if va is not None and vb is not None else None)
            else:
                tot[key] = cn
        for key, cn in tot.items():
            name = max(display[key].items(), key=lambda kv: (kv[1], kv[0]))[0]
            w.player_stat(name, key[0], subj, scope=scope, gp=cn.gp, tuh=cn.tuh, correct=cn.correct,
                          zeros=cn.zeros, negs=cn.negs, points=cn.points)
