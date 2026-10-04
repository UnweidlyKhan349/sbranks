"""2019-23 online events (group g3): one-off results layouts.

Each ``parse_*`` function handles one source layout; stats workbooks in the generated
'subject/all/bio' template are read with :mod:`.g3_stats_template`.

Shared helpers here:

* :func:`label_bracket` - hand-drawn brackets where a game label ("Room 3", "Commons I, R4")
  sits in a column between the two entrants and each entrant's score is in the cell to the
  right of its name.
* :func:`infer_pairings` - round-robin tables that give each team's per-round result and
  own score but not the opponent: finds the round-by-round pairings consistent with
  W/L/T, scores and "each pair meets at most once".
"""
from __future__ import annotations

import itertools
import json
import re
from collections import defaultdict
from typing import Any, Iterable

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, load_grids
from . import g3_stats_template as tpl


# ---------------------------------------------------------------------------------------
# helpers
def _is_number(v: Any) -> bool:
    return num(v) is not None


def label_bracket(g: Grid, label_rx: str, *, rows: tuple[int, int] = (0, 10 ** 9),
                  result_words: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Games of a 'label between entrants' bracket.

    An *entry* is a non-numeric text cell whose right neighbour holds a score (or one of
    ``result_words``, e.g. win/loss). For every label cell matching ``label_rx`` the two
    entrants are the nearest entries above and below it in the label's column (or, if
    that column has none, the column to its right). Labels without two entrants (e.g. an
    unplayed "if needed" final) are skipped.
    """
    words = {k.lower(): v for k, v in (result_words or {}).items()}

    def entry(r: int, c: int) -> tuple[str, Any] | None:
        name = g.text(r, c)
        if not name or _is_number(name) or re.search(label_rx, name):
            return None
        sc = g.cell(r, c + 1)
        if _is_number(sc):
            return name, num(sc)
        if clean_name(sc).lower() in words:
            return name, words[clean_name(sc).lower()]
        return None

    games = []
    lo, hi = rows
    for r, c in g.find(label_rx):
        if not lo <= r < hi:
            continue
        for col in (c, c + 1):
            up = next(((rr, e) for rr in range(r - 1, lo - 1, -1) if (e := entry(rr, col))), None)
            dn = next(((rr, e) for rr in range(r + 1, min(hi, g.nrows)) if (e := entry(rr, col))), None)
            if up and dn:
                games.append({"label": g.text(r, c), "row": r, "col": c, "entry_col": col,
                              "a": up[1], "b": dn[1], "a_row": up[0], "b_row": dn[0]})
                break
    return games


def infer_pairings(entries: dict[Any, dict[str, tuple[str, float | None]]],
                   fixed_pairs: Iterable[frozenset[str]] = (), limit: int = 50
                   ) -> tuple[list[dict[Any, list[tuple[str, str]]]], bool]:
    """Pairings per round consistent with each team's (result, score) entries.

    ``entries[round][team] = (result, score)`` with result W/L/T. In each round every team
    with an entry plays exactly one other team with an entry: W meets L with a higher
    score, T meets T with an equal score (scores may be None = unknown). Each pair meets at
    most once overall. Returns up to ``limit`` solutions and whether the search was cut.
    """
    rounds = sorted(entries)
    used: set[frozenset[str]] = set(fixed_pairs)
    sols: list[dict[Any, list[tuple[str, str]]]] = []
    cut = False

    def ok(a: tuple[str, float | None], b: tuple[str, float | None]) -> bool:
        (ra, sa), (rb, sb) = a, b
        if {ra, rb} == {"W", "L"}:
            if sa is None or sb is None:
                return True
            return (sa > sb) if ra == "W" else (sb > sa)
        if ra == rb == "T":
            return sa is None or sb is None or sa == sb
        return False

    def match(teams: list[str], ent: dict[str, tuple[str, float | None]]) -> Iterable[list[tuple[str, str]]]:
        if not teams:
            yield []
            return
        a, rest = teams[0], teams[1:]
        for i, b in enumerate(rest):
            pair = frozenset((a, b))
            if pair in used or not ok(ent[a], ent[b]):
                continue
            used.add(pair)
            for m in match(rest[:i] + rest[i + 1:], ent):
                yield [(a, b), *m]
            used.discard(pair)

    def rec(k: int, acc: dict[Any, list[tuple[str, str]]]) -> None:
        nonlocal cut
        if cut:
            return
        if k == len(rounds):
            sols.append(dict(acc))
            if len(sols) >= limit:
                cut = True
            return
        rnd = rounds[k]
        ent = entries[rnd]
        teams = sorted(ent)
        if len(teams) % 2:
            return
        for m in match(teams, ent):
            pairs = [frozenset(p) for p in m]
            used.update(pairs)
            acc[rnd] = m
            rec(k + 1, acc)
            del acc[rnd]
            used.difference_update(pairs)
            if cut:
                return

    rec(0, {})
    return sols, cut


def certain_games(sols: list[dict[Any, list[tuple[str, str]]]],
                  entries: dict[Any, dict[str, tuple[str, float | None]]]) -> list[dict[str, Any]]:
    """Games implied by every pairing solution. A pair met in the same round in all
    solutions keeps its round and scores; a pair met in every solution but in different
    rounds keeps only its result, if that is the same in all of them."""
    def meetings(sol: dict[Any, list[tuple[str, str]]]) -> dict[frozenset[str], Any]:
        return {frozenset(p): rnd for rnd, ps in sol.items() for p in ps}

    ms = [meetings(s) for s in sols]
    out = []
    for pair, rnd in ms[0].items():
        if not all(pair in m for m in ms[1:]):
            continue
        a, b = sorted(pair)
        rounds = sorted({m[pair] for m in ms})
        results = {entries[m[pair]][a][0] for m in ms}
        if len(rounds) == 1:
            (ra, sa), (rb, sb) = entries[rnd][a], entries[rnd][b]
            out.append({"a": a, "b": b, "round": rnd, "sa": sa, "sb": sb, "rounds": rounds})
        elif len(results) == 1:
            r = results.pop()
            out.append({"a": a, "b": b, "round": None, "rounds": rounds,
                        "result": "1" if r == "W" else "2" if r == "L" else "T"})
    return out


def _emit_scored(w: TournamentWriter, a: str, sa: Any, b: str, sb: Any, *, stage: str,
                 rnd: Any, seq: int, winner: str | None = None, notes: str = "") -> str | None:
    """Write a game; if the declared winner disagrees with the scores (e.g. a tie broken by
    a tiebreaker tossup), keep the result and move the scores into the notes."""
    sa, sb = num(sa), num(sb)
    if winner is None:
        return w.game(a, b, sa, sb, stage=stage, round=rnd, seq=seq, notes=notes)
    res = "1" if winner == a else "2"
    if sa is not None and sb is not None:
        exp = "1" if sa > sb else "2" if sb > sa else "T"
        if exp != res:
            note = f"source score {sa:g}-{sb:g}; winner per source {winner}"
            w.warn(f"{rnd}: {a} vs {b}: {note}")
            return w.game(a, b, stage=stage, round=rnd, seq=seq, result=res,
                          notes=(notes + "; " if notes else "") + note)
    return w.game(a, b, sa, sb, stage=stage, round=rnd, seq=seq, result=res, notes=notes)


def _stats_players(t: Tournament, w: TournamentWriter, file: str, scope: str,
                   team_map: dict[str, str] | None, subject_map: dict[str, str] | None = None,
                   school_hints: bool = False) -> tpl.TemplateStats:
    st = tpl.read_template(t.raw(file), subject_map)
    team_map = team_map or {}
    for team in tpl.team_names(st):
        mapped = team_map.get(team, team)
        w.team(mapped, school=team if (school_hints and mapped != team) else "")
    a = tpl.assign_with_check(st, w)
    tpl.write_player_stats(w, st, a.team_of, scope=scope, team_map=team_map)
    return st


# ---------------------------------------------------------------------------------------
# Discord Winter Tournament 2020: standings + individual stats only
def parse_discord_winter(t: Tournament, w: TournamentWriter) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    field = grids["Field"]
    rosters: dict[str, list[str]] = {}
    for r in range(1, field.nrows):
        team = field.text(r, 0)
        if team:
            rosters[team] = [field.text(r, c) for c in range(1, field.ncols) if field.text(r, c)]
    ts = grids["Team Standings"]
    hdr = ts.row_texts(0)
    ti = hdr.index("Team")
    for r in range(1, ts.nrows):
        if ts.text(r, ti):
            w.team(ts.text(r, ti), players=rosters.get(ts.text(r, ti), []))
    ind = grids["Individual Standings"]
    h = ind.row_texts(0)
    col = {k: h.index(k) for k in ("Player", "Team", "GP", "TUH", "4", "-4", "Pts")}
    for r in range(1, ind.nrows):
        p = ind.text(r, col["Player"])
        if not p:
            continue
        w.player_stat(p, ind.text(r, col["Team"]), "overall", scope="all",
                      gp=ind.cell(r, col["GP"]), tuh=ind.cell(r, col["TUH"]),
                      correct=ind.cell(r, col["4"]), negs=ind.cell(r, col["-4"]),
                      points=ind.cell(r, col["Pts"]))


# ---------------------------------------------------------------------------------------
# SBL 2020 (online league): per-round player TUH/points and team scores, no opponents
def parse_sbl(t: Tournament, w: TournamentWriter,
              divisions: dict[str, list[str]] | None = None) -> None:
    grids = load_grids(t.raw("stats.xlsx"))
    divisions = divisions or {"Standard": ["TUHStand", "PointStand", "TeamStand"],
                              "Competitive": ["TUHComp", "PointComp", "TeamComp"]}
    for div, (tuh_tab, pt_tab, team_tab) in divisions.items():
        tg = grids[team_tab]
        for r in range(1, tg.nrows):
            name = tg.text(r, 0)
            if name and name != "Average Score":
                w.team(name, notes=f"{div} division")
        tuh_rows: dict[tuple[str, str], list[float]] = {}
        g = grids[tuh_tab]
        h = g.row_texts(0)
        rcols = [i for i, x in enumerate(h) if re.match(r"^Round \d+$", x)]
        for r in range(1, g.nrows):
            p, team = g.text(r, 0), g.text(r, 1)
            if p:
                tuh_rows[(p, team)] = [g.num(r, c) or 0 for c in rcols]
        g = grids[pt_tab]
        h = g.row_texts(0)
        tcol, pcol = h.index("TUH"), h.index("Total Points")
        for r in range(1, g.nrows):
            p, team = g.text(r, 0), g.text(r, 1)
            if not p:
                continue
            per_round = tuh_rows.get((p, team))
            if per_round is None:
                w.warn(f"{div}: no TUH row for {p} ({team})")
                continue
            tuh = g.num(r, tcol)
            if abs(sum(per_round) - (tuh or 0)) > 0.01:
                w.warn(f"{div}: {p} TUH {tuh} != sum of rounds {sum(per_round)}")
            gp = sum(1 for x in per_round if x > 0)
            if gp == 0:
                continue
            w.player_stat(p, team, "overall", scope="all", gp=gp, tuh=tuh, points=g.num(r, pcol))


# ---------------------------------------------------------------------------------------
# MIT Science Bowl 2020: RR win-point grids (no scores) + visual DE with "a – b" scores
_WORDNUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen".split())}


def parse_mit2020(t: Tournament, w: TournamentWriter) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    rr = grids["Round Robin"]
    for r, c in rr.find(r"^SCHOOL$"):
        div = rr.text(r - 1, 0).title()
        hdr = rr.row_texts(r)
        vs = [i for i, x in enumerate(hdr) if re.match(r"^vs\. \d$", x)]
        teams = []
        for rr_ in range(r + 1, r + 1 + len(vs)):
            name = rr.text(rr_, c)
            if name:
                teams.append((rr_, name, rr.text(rr_, c + 1)))
        for (i, (ri, ti, _)), (j, (rj, tj, _)) in itertools.combinations(enumerate(teams), 2):
            vij, vji = rr.num(ri, vs[j]), rr.num(rj, vs[i])
            if (vij, vji) == (2, 0):
                res = "1"
            elif (vij, vji) == (0, 2):
                res = "2"
            elif (vij, vji) == (1, 1):
                res = "T"
            else:
                w.warn(f"RR {div}: {ti} vs {tj}: cells {vij}/{vji} disagree; skipped")
                continue
            w.game(ti, tj, stage="rr", round="", seq=1, result=res,
                   notes=f"{div}; win/loss only (no scores in source)")
    de = grids["Double Elimination"]
    labels = {c: de.text(0, c) for c in range(de.ncols) if de.text(0, c).startswith("ROUND")}
    skip = re.compile(r"^L\(DE|^In double| - \d(st|nd|rd|th)$|Teams? Re|P\.M\.|PLACE|CHAMPION|^N/A$")

    def name_at(rr_: int, c: int, step: int) -> tuple[int, str] | None:
        while 0 <= rr_ < de.nrows:
            s = de.text(rr_, c)
            if s and not skip.search(s) and not re.match(r"^\d+\s*[–-]\s*\d+$", s):
                return rr_, s
            rr_ += step
        return None

    for r, c in de.find(r"^\d+\s*[–-]\s*\d+$"):
        m = re.match(r"^(\d+)\s*[–-]\s*(\d+)$", de.text(r, c))
        s1, s2 = int(m.group(1)), int(m.group(2))
        up, dn = name_at(r - 1, c - 1, -1), name_at(r + 1, c - 1, +1)
        winner = de.text(r, c + 1)
        if not up or not dn or winner not in (up[1], dn[1]):
            w.warn(f"DE score at {r},{c}: could not identify teams/winner")
            continue
        rnd = _WORDNUM.get(labels.get(c - 1, "").replace("ROUND ", "").lower())
        a, b = up[1], dn[1]
        if (s1 > s2) != (winner == a):
            # the source lists the winner's score first here; the round's own average-score
            # table confirms the winner scored the higher number
            w.warn(f"DE round {rnd}: {a} vs {b} score '{s1} – {s2}' listed winner-first")
            s1, s2 = (s2, s1)
        w.game(a, b, s1, s2, stage="playoff", round=f"DE {rnd}", seq=rnd or 99)


# ---------------------------------------------------------------------------------------
# MOSFET 2020: day-2 divisions, win grids (1 = row team beat column team) + round schedule
def parse_mosfet2020(t: Tournament, w: TournamentWriter, team_map: dict[str, str] | None = None,
                     stats_file: str = "stats.xlsx") -> None:
    grids = load_grids(t.raw("results.xlsx"))
    for tab, g in grids.items():
        rounds = list(g.find(r"^Round$"))
        for sr, sc in g.find(r"^Seed$"):
            rr0, _ = min(rounds, key=lambda x: abs(x[0] - sr))
            div = clean_name(re.sub(r"^Division\s*", "", g.text(rr0 - 1, 0)))
            heads = []
            c = sc + 2
            while g.text(sr, c) and "Points" not in g.text(sr, c):
                heads.append(c)
                c += 1
            seeds: dict[int, tuple[int, str]] = {}
            for r in range(sr + 1, sr + 1 + len(heads)):
                if g.num(r, sc) is not None and g.text(r, sc + 1):
                    seeds[int(g.num(r, sc))] = (r, g.text(r, sc + 1))
            for r in range(rr0 + 1, rr0 + 10):
                rn = g.num(r, 0)
                if rn is None:
                    break
                for c in range(1, 4):
                    m = re.match(r"^(\d)v(\d)$", g.text(r, c))
                    if not m:
                        continue
                    i, j = int(m.group(1)), int(m.group(2))
                    (ri, ti), (rj, tj) = seeds[i], seeds[j]
                    vij, vji = g.num(ri, heads[j - 1]), g.num(rj, heads[i - 1])
                    valid = {0.0, 0.5, 1.0}
                    if vij in valid and vji in valid and vij + vji == 1:
                        pass
                    elif vij in valid and vji not in valid and vji is not None:
                        w.warn(f"{div} R{int(rn)}: {ti} vs {tj}: cells {vij}/{vji}; used {ti}'s cell")
                        vji = 1 - vij
                    elif vji in valid and vij not in valid and vij is not None:
                        w.warn(f"{div} R{int(rn)}: {ti} vs {tj}: cells {vij}/{vji}; used {tj}'s cell")
                        vij = 1 - vji
                    else:
                        w.warn(f"{div} R{int(rn)}: {ti} vs {tj}: no result recorded ({vij}/{vji})")
                        continue
                    res = "1" if vij == 1 else "2" if vij == 0 else "T"
                    w.game(ti, tj, stage="rr", round=int(rn), seq=int(rn), result=res,
                           notes=f"Division {div}; win/loss only (no scores in source)")
    _stats_players(t, w, stats_file, "rr", team_map, school_hints=True)


# ---------------------------------------------------------------------------------------
# SBST 2020: hand-drawn 16-team double elimination (seeded "N- Team" cells, score to the
# right). Game cells are listed explicitly: (round label, round no., (row, name col, score
# col), (row, name col, score col)); coordinates are 0-based.
_SBST2020 = [
    ("W1", 1, (2, 1, 2), (3, 1, 2)), ("W1", 1, (6, 1, 2), (7, 1, 2)),
    ("W1", 1, (10, 1, 2), (11, 1, 2)), ("W1", 1, (14, 1, 2), (15, 1, 2)),
    ("W1", 1, (18, 1, 2), (19, 1, 2)), ("W1", 1, (22, 1, 2), (23, 1, 2)),
    ("W1", 1, (26, 1, 2), (27, 1, 2)), ("W1", 1, (30, 1, 2), (31, 1, 2)),
    ("W2", 2, (4, 4, 5), (5, 4, 5)), ("W2", 2, (12, 4, 5), (13, 4, 5)),
    ("W2", 2, (20, 4, 5), (21, 4, 5)), ("W2", 2, (28, 4, 5), (29, 4, 5)),
    ("L2", 2, (35, 4, 5), (36, 4, 5)), ("L2", 2, (41, 4, 5), (42, 4, 5)),
    ("L2", 2, (47, 4, 5), (48, 4, 5)), ("L2", 2, (53, 4, 5), (54, 4, 5)),
    ("W3", 3, (8, 7, 8), (9, 7, 8)), ("W3", 3, (24, 7, 8), (25, 7, 8)),
    ("L3", 3, (32, 6, 7), (35, 6, 7)), ("L3", 3, (38, 6, 7), (41, 6, 7)),
    ("L3", 3, (44, 6, 7), (47, 6, 7)), ("L3", 3, (50, 6, 7), (53, 6, 7)),
    ("W4", 4, (16, 10, 11), (17, 10, 11)),
    ("L4", 4, (33, 8, 9), (39, 8, 9)), ("L4", 4, (45, 8, 9), (51, 8, 9)),
    ("L5", 5, (30, 11, 12), (36, 11, 12)), ("L5", 5, (48, 11, 12), (54, 11, 12)),
    ("L6", 6, (33, 13, 14), (51, 13, 14)),
    ("L7", 7, (24, 13, 16), (41, 15, 16)),
    ("Final", 8, (16, 13, 18), (32, 17, 18)),
]


def _sbst2020_name(s: str) -> str:
    s = re.sub(r"\s*\(.*$", "", s)            # "(May request a staffer ...)"
    s = re.sub(r"^\d+\s*-\s*", "", s)          # seed prefix "3- " / "6 - "
    return {"SciOly Sucks": "Scioly Sucks"}.get(s.strip(), s.strip())


def parse_sbst2020(t: Tournament, w: TournamentWriter) -> None:
    g = load_grids(t.raw("results.xlsx"))["Sheet1"]
    for label, rnd, (r1, n1, s1), (r2, n2, s2) in _SBST2020:
        a, b = _sbst2020_name(g.text(r1, n1)), _sbst2020_name(g.text(r2, n2))
        sa, sb = g.num(r1, s1), g.num(r2, s2)
        if not a or not b or sa is None or sb is None:
            raise ValueError(f"SBST 2020 layout changed near row {r1}: {a!r} {sa} / {b!r} {sb}")
        w.game(a, b, sa, sb, stage="playoff", round=label, seq=rnd,
               notes="Final game 1 (the undefeated team won, so no game 2)" if label == "Final" else "")


# ---------------------------------------------------------------------------------------
# WISC 2021: Primary / Secondary playoff brackets (winners only); stats = round robin
def _winner_bracket(g: Grid, w: TournamentWriter, prefix: str, stage_main: str,
                    seq_by_col: dict[int, int], names: dict[str, str]) -> None:
    sections = sorted([(r, g.text(r, c)) for r, c in
                       g.find(r"^(Consolation Bracket|Playoffs Game|WISC Playoffs Bracket)$")])

    def section(r: int) -> str:
        cur = ""
        for sr, s in sections:
            if sr <= r:
                cur = s
        return cur

    for r, c in g.find(r"^Room \d+$"):
        lo = max([sr for sr, _ in sections if sr <= r] or [0])
        up = next((g.text(x, c) for x in range(r - 1, lo, -1)
                   if g.text(x, c) and not g.text(x, c).startswith("Room")), "")
        dn = next((g.text(x, c) for x in range(r + 1, g.nrows)
                   if g.text(x, c) and not g.text(x, c).startswith("Room")), "")
        win = next((g.text(r, x) for x in range(c + 1, g.ncols) if g.text(r, x)), "")
        a, b, win = (names.get(x, x) for x in (up, dn, win))
        if not a or not b or win not in (a, b):
            w.warn(f"{prefix}: room cell at {r},{c} unreadable ({up!r} vs {dn!r} -> {win!r})")
            continue
        sec = section(r)
        if "Consolation" in sec:
            stage, rnd = "consolation", f"{prefix} Consolation {'R1' if c == 1 else 'Final'}"
        elif "Playoffs Game" in sec:
            stage, rnd = stage_main, f"{prefix} 3rd place"
        else:
            stage = stage_main
            rnd = {0: "QF", 1: "SF"}.get(c, "Final")
            rnd = f"{prefix} {rnd}"
        w.game(a, b, stage=stage, round=rnd, seq=seq_by_col.get(c, 9), result="1" if win == a else "2",
               notes="winner only (no scores in source)")


def parse_wisc2021(t: Tournament, w: TournamentWriter, team_map: dict[str, str] | None = None,
                   names: dict[str, str] | None = None) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    names = names or {}
    # QF 4:15, SF 5:00, 3rd place / consolation final 5:45, Primary final 6:30
    _winner_bracket(grids["Primary"], w, "Primary", "playoff", {0: 6, 1: 7, 2: 8, 3: 9}, names)
    _winner_bracket(grids["Secondary"], w, "Secondary", "playoff", {0: 6, 1: 7, 2: 8}, names)
    _stats_players(t, w, "stats.xlsx", "rr", team_map)


# ---------------------------------------------------------------------------------------
# CSBL 2021: 4-team groups (per-round W/L + own score, no opponents) + DE / wildcard bracket
def parse_csbl2021(t: Tournament, w: TournamentWriter, names: dict[str, str] | None = None) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    names = names or {}
    g = grids["Group Stage Table"]
    hdr = g.row_texts(0)
    rcols = [i for i, x in enumerate(hdr) if re.match(r"^Round \d+$", x)]
    groups: dict[str, list[int]] = defaultdict(list)
    grp = ""
    for r in range(1, g.nrows):
        if g.text(r, 0):
            grp = g.text(r, 0)
        if g.text(r, 1) and g.text(r, rcols[0]).lower() in ("w", "l", "t"):
            groups[grp].append(r)
    n_rr = len(rcols)
    for grp, rows in groups.items():
        entries: dict[int, dict[str, tuple[str, float | None]]] = {}
        for k, c in enumerate(rcols, 1):
            entries[k] = {g.text(r, 1): (g.text(r, c).upper(), g.num(r, c + 1)) for r in rows
                          if g.text(r, c)}
        sols, cut = infer_pairings(entries)
        if not sols:
            w.warn(f"group {grp}: no consistent pairing; group games skipped")
            continue
        if cut:
            w.warn(f"group {grp}: too many consistent pairings; group games skipped")
            continue
        if len(sols) > 1:
            w.warn(f"group {grp}: {len(sols)} pairings fit the results; games whose round is "
                   "ambiguous are kept with their (certain) result but without scores")
        for gm in certain_games(sols, entries):
            note = f"Group {grp}; opponent inferred from per-round results/scores"
            if gm["round"] is None:
                w.game(gm["a"], gm["b"], stage="rr", round="", seq=1, result=gm["result"],
                       notes=note + "; round (and so score) ambiguous between rounds "
                       + "/".join(str(x) for x in gm["rounds"]))
            else:
                w.game(gm["a"], gm["b"], gm["sa"], gm["sb"], stage="rr", round=gm["round"],
                       seq=gm["round"], notes=note)
        for r in rows:
            w.team(g.text(r, 1))
    de = grids["Elimination Rounds"]
    hdr_cols = {c: de.text(0, c) for c in range(de.ncols) if de.text(0, c).startswith("Round")}
    wc_row = next((r for r, _ in de.find(r"^WILDCARD")), de.nrows)
    used: set[tuple[int, int]] = set()
    for gm in sorted(label_bracket(de, r"^(Room \d+|Bottom-16-finals)"), key=lambda x: (x["col"], x["row"])):
        h = hdr_cols.get(gm["col"]) or hdr_cols.get(gm["col"] + 1) or ""
        k = int(re.match(r"Round (\d+)", h).group(1)) if h else 0
        wildcard = gm["row"] > wc_row
        (a, sa), (b, sb) = gm["a"], gm["b"]
        a, b = names.get(a, a), names.get(b, b)
        for key in ((gm["a_row"], gm["entry_col"]), (gm["b_row"], gm["entry_col"])):
            if key in used:
                w.warn(f"bracket entry at {key} used twice")
            used.add(key)
        rnd = f"{'Wildcard' if wildcard else 'DE'} R{k}"
        if gm["label"].startswith("Bottom"):
            rnd = "Wildcard final"
        w.game(a, b, sa, sb, stage="consolation" if wildcard else "playoff", round=rnd,
               seq=n_rr + k)


# ---------------------------------------------------------------------------------------
# DBHSST 2021: RR blocks with per-match "W 118-60" (own score first); opponents matched by
# mirrored scores within the division and match. Elimination results are not in the sheet.
def parse_dbhsst2021(t: Tournament, w: TournamentWriter, team_map: dict[str, str] | None = None) -> None:
    g = load_grids(t.raw("results.xlsx"))["RR Results"]
    hdr = g.row_texts(1)
    mcols = [i for i, x in enumerate(hdr) if x == "Match result"]
    div = ""
    rows_by_div: dict[str, list[int]] = defaultdict(list)
    for r in range(2, g.nrows):
        s = g.text(r, 0)
        if s.endswith("DIVISION"):
            div = re.sub(r"\s*DIVISION$", "", s).title()
        elif s and g.text(r, mcols[0]):
            rows_by_div[div].append(r)

    def team_name(s: str) -> str:
        return clean_name(re.sub(r"\s*\(.*?\)\s*", " ", s))

    for div, rows in rows_by_div.items():
        for k, c in enumerate(mcols, 1):
            ent = []
            for r in rows:
                res, sc = g.text(r, c).upper(), g.text(r, c + 1)
                m = re.match(r"^(\d+)-(\d+)$", sc)
                if res and m:
                    own, opp = int(m.group(1)), int(m.group(2))
                    if (res == "W" and own < opp) or (res == "L" and own > opp):
                        w.warn(f"{div} match {k}: {team_name(g.text(r, 0))} {res} {sc}: score "
                               "written winner-first; swapped")
                        own, opp = opp, own
                    ent.append((team_name(g.text(r, 0)), res, own, opp))
            left = list(ent)
            while left:
                a, ra, sa, oa = left.pop(0)
                cands = [e for e in left if e[2] == oa and e[3] == sa and
                         ({ra, e[1]} == {"W", "L"} or ra == e[1] == "T")]
                if len(cands) != 1:
                    w.warn(f"{div} match {k}: {a} ({ra} {sa}-{oa}): {len(cands)} possible opponents; skipped")
                    continue
                b, rb, sb, ob = cands[0]
                left.remove(cands[0])
                note = f"{div} division"
                if sa == 0 and sb == 0:
                    w.game(a, b, stage="rr", round=k, seq=k, result="1" if ra == "W" else "2",
                           forfeit=True, notes=note + "; forfeit (0-0 in source)")
                    continue
                winner = a if ra == "W" else b if rb == "W" else None
                _emit_scored(w, a, sa, b, sb, stage="rr", rnd=k, seq=k, winner=winner, notes=note)
    _stats_players(t, w, "stats.xlsx", "all", team_map, subject_map={"physical": "other"})


# ---------------------------------------------------------------------------------------
# WSBT 2022-23: Challonge double-elimination playoffs (embedded JSON) + RR stats workbook
def _challonge_store(path: Any) -> dict[str, Any]:
    h = open(path, encoding="utf-8").read()
    key = "window._initialStoreState['TournamentStore'] = "
    i = h.find(key)
    if i < 0:
        raise ValueError(f"{path}: no TournamentStore JSON")
    d, _ = json.JSONDecoder().raw_decode(h[i + len(key):])
    return d


def parse_challonge_de(t: Tournament, w: TournamentWriter, file: str, *, seq_offset: int = 0,
                       forfeit_matches: dict[int, str] | None = None) -> None:
    """``forfeit_matches``: Challonge match identifier -> note, for matches with a score
    that the bracket's context shows to be a forfeit."""
    forfeit_matches = {int(k): v for k, v in (forfeit_matches or {}).items()}
    d = _challonge_store(t.raw(file))
    mbr = d["matches_by_round"]
    matches = [m for ms in mbr.values() for m in ms if m.get("state") == "complete"]
    wmax = max(int(k) for k in mbr if int(k) > 0)
    has_losers = any(int(k) < 0 for k in mbr)

    def rlabel(rnd: int) -> str:
        if rnd < 0:
            return f"L{-rnd}"
        if has_losers and rnd == wmax:
            return "Grand Final"
        return f"W{rnd}"

    # play order: a team's matches go winners rounds, then losers rounds, then grand final
    def order_key(m: dict[str, Any]) -> tuple[int, int]:
        r = m["round"]
        if has_losers and r == wmax:
            return (2, 0)
        return (0, r) if r > 0 else (1, -r)

    by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for m in matches:
        for pk in ("player1", "player2"):
            if m.get(pk):
                by_team[m[pk]["id"]].append(m)
    for ms in by_team.values():
        ms.sort(key=order_key)
    seq: dict[int, int] = {}

    def seq_of(m: dict[str, Any]) -> int:
        if m["id"] in seq:
            return seq[m["id"]]
        s = 1
        for pk in ("player1", "player2"):
            ms = by_team[m[pk]["id"]]
            i = ms.index(m)
            if i > 0:
                s = max(s, seq_of(ms[i - 1]) + 1)
        seq[m["id"]] = s
        return s

    for m in sorted(matches, key=lambda m: (seq_of(m), order_key(m), m["identifier"])):
        p1, p2 = m["player1"], m["player2"]
        a, b = clean_name(p1["display_name"]), clean_name(p2["display_name"])
        sc = m.get("scores") or []
        winner = a if m["winner_id"] == p1["id"] else b if m["winner_id"] == p2["id"] else None
        rnd = rlabel(m["round"])
        if len(sc) == 2 and sc[0] == 0 and sc[1] == 0 or m.get("forfeited") \
                or m["identifier"] in forfeit_matches:
            why = forfeit_matches.get(m["identifier"]) or "0-0 (forfeit)"
            w.game(a, b, stage="playoff", round=rnd, seq=seq_offset + seq_of(m),
                   result="1" if winner == a else "2", forfeit=True,
                   notes=f"Challonge match {m['identifier']}; {why}")
            continue
        sa, sb = (sc + [None, None])[:2]
        _emit_scored(w, a, sa, b, sb, stage="playoff", rnd=rnd, seq=seq_offset + seq_of(m),
                     winner=winner, notes=f"Challonge match {m['identifier']}")


def parse_wsbt(t: Tournament, w: TournamentWriter, team_map: dict[str, str] | None = None,
               challonge_file: str = "challonge_module.html",
               forfeit_matches: dict[int, str] | None = None) -> None:
    parse_challonge_de(t, w, challonge_file, seq_offset=10, forfeit_matches=forfeit_matches)
    _stats_players(t, w, "stats.xlsx", "rr", team_map)
