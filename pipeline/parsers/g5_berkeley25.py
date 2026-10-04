"""Berkeley Science Bowl Dec 2025.

results.xlsx:
  * 'Raw RR Results'  Team 1 | Team 2 | Team 1 Score | Team 2 Score (no round numbers)
  * 'RR Viewer'       divisions: code | full school name | team | division letter, plus a
                      row-vs-column score grid per division
  * 'DE Bracket'      16-team double elimination (``team | score`` columns)
  * 'Swiss Bracket'   afternoon consolation Swiss (non-DE teams, joined by DE teams once
                      eliminated): per round a column of ``seed | team | score | record``
stats.xlsx:
  * 'All RR Questions'  per TEAM, per round (1-5) and question (1-23): TU (tossup correct),
                        B (tossup + bonus correct), P (penalty), blank; row 2 = category.
  * 'RR PPG'            player leaderboards (abbreviated names, per-game "stat scores"
                        that mix tossups and bonuses) - not exported.

The round of each RR game is recovered from the question grid: the round k in which both
teams' question outcomes reproduce the final score (4*TU + 14*B + 4*opponent penalties).
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, num
from ..util.grid import Grid, load_grids
from .g5_common import bracket_entries

BIG = 1e90


def _questions(q: Grid):
    rounds = {c: int(q.num(1, c)) for c in range(4, q.ncols) if q.num(1, c) is not None}
    cats = {c: normalize_subject(q.text(2, c)) for c in rounds}
    out = {}
    for r in range(4, q.nrows):
        team = q.text(r, 0)
        if not team or q.num(r, 1) is None:
            continue
        per = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # k -> subj -> code
        for c, k in rounds.items():
            v = q.text(r, c).upper()
            if v in ("TU", "B", "P"):
                per[k][cats[c]][v] += 1
        out[team] = per
    return out, cats


def _tot(per_k) -> tuple[int, int, int]:
    tu = sum(d["TU"] for d in per_k.values())
    b = sum(d["B"] for d in per_k.values())
    p = sum(d["P"] for d in per_k.values())
    return tu, b, p


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
          stats: str = "stats.xlsx", rr_rounds: int = 5) -> None:
    grids = load_grids(t.raw(results))
    sgrids = load_grids(t.raw(stats))

    # Teams, schools and divisions from the RR viewer.
    v = grids["RR Viewer"]
    div_of = {}
    grid_scores = {}
    for r in range(v.nrows):
        code, full, team, div = v.text(r, 1), v.text(r, 2), v.text(r, 3), v.text(r, 4)
        if re.match(r"^[A-H]\d$", code) and team and team.upper() != "BYE":
            school = re.sub(r"\s+[A-D]$", "", full)
            w.team(team, school=school)
            div_of[team] = div
            grid_scores[code] = team
    # division grids: row label (col 7) = code, header row has codes in cols 8..13
    for r in range(v.nrows):
        rc = v.text(r, 7)
        if re.match(r"^[A-H]\d$", rc) and rc in grid_scores:
            hr = r
            while hr > 0 and v.text(hr, 7) != "X":
                hr -= 1
            for c in range(8, 14):
                oc = v.text(hr, c)
                s = v.num(r, c)
                if oc in grid_scores and s is not None:
                    grid_scores[(grid_scores[rc], grid_scores[oc])] = s

    raw = grids["Raw RR Results"]
    games = []
    for r in range(1, raw.nrows):
        a, b = raw.text(r, 0), raw.text(r, 1)
        if not a or not b or "BYE" in (a.upper(), b.upper()):
            continue
        games.append((a, b, raw.num(r, 2), raw.num(r, 3)))

    qd, cats = _questions(sgrids["All RR Questions"])
    qg = sgrids["All RR Questions"]
    qrounds = {c: int(qg.num(1, c)) for c in range(4, qg.ncols) if qg.num(1, c) is not None}
    assigned: dict[int, int] = {}
    for i, (a, b, sa, sb) in enumerate(games):
        if a not in qd or b not in qd:
            continue
        ks = []
        for k in range(1, rr_rounds + 1):
            ta, ba, pa = _tot(qd[a][k])
            tb, bb, pb = _tot(qd[b][k])
            if 4 * ta + 14 * ba + 4 * pb == sa and 4 * tb + 14 * bb + 4 * pa == sb:
                ks.append(k)
        if len(ks) == 1:
            assigned[i] = ks[0]
    exact = set(assigned)
    # Remaining games: each team plays at most once per round.
    changed = True
    while changed:
        changed = False
        used = defaultdict(set)
        for i, k in assigned.items():
            used[games[i][0]].add(k)
            used[games[i][1]].add(k)
        for i, (a, b, sa, sb) in enumerate(games):
            if i in assigned:
                continue
            cands = [k for k in range(1, rr_rounds + 1) if k not in used[a] and k not in used[b]]
            if len(cands) == 1:
                assigned[i] = cands[0]
                changed = True
                break
            if len(cands) > 1 and a in qd and b in qd:
                # closest reconstruction of the two scores
                def err(k):
                    ta, ba, pa = _tot(qd[a][k])
                    tb, bb, pb = _tot(qd[b][k])
                    return abs(4 * ta + 14 * ba + 4 * pb - sa) + abs(4 * tb + 14 * bb + 4 * pa - sb)
                best = sorted(cands, key=err)
                if err(best[0]) < err(best[1]):
                    assigned[i] = best[0]
                    changed = True
                    break
    for i, (a, b, sa, sb) in enumerate(games):
        k = assigned.get(i)
        if k is None:
            w.warn(f"RR {a} vs {b}: round unknown")
        for x, y, s in ((a, b, sa), (b, a, sb)):
            gs = grid_scores.get((x, y))
            if gs is not None and gs != s:
                w.warn(f"RR {x} vs {y}: viewer grid {gs} != results {s}")
        gid = w.game(a, b, sa, sb, stage="rr", round=f"RR{k}" if k else "RR", seq=k or 0,
                     notes=f"division {div_of.get(a, '')}".strip())
        if i in exact:
            subjects = sorted({sj for c, sj in cats.items() if sj and qrounds.get(c) == k})
            for team, opp in ((a, b), (b, a)):
                for subj in subjects:
                    d = qd[team][k].get(subj, {"TU": 0, "B": 0, "P": 0})
                    tu = d["TU"] + d["B"]
                    w.team_game_subject(gid, team, subj, 4 * tu + 10 * d["B"],
                                        tossup_points=4 * tu, bonus_points=10 * d["B"],
                                        tossups_correct=tu, negs=d["P"])
        elif k:
            w.warn(f"RR{k} {a} {sa} - {b} {sb}: question grid does not reproduce the score; "
                   f"no subject breakdown")

    # Double elimination.
    rounds = []
    for c, ents in bracket_entries(grids["DE Bracket"], skip_rx=r"^bye\d*$").items():
        ents = [e for e in ents if abs(e.scores[0]) < BIG]
        if len(ents) % 2:
            raise ValueError(f"DE column {c}: odd entries")
        rounds.append(list(zip(ents[0::2], ents[1::2])))
    for k, pairs in enumerate(rounds, start=1):
        lab = "Final" if k == len(rounds) else f"DE{k}"
        for a, b in pairs:
            w.game(a.name, b.name, a.scores[0], b.scores[0], stage="playoff", round=lab,
                   seq=rr_rounds + k)

    # Swiss consolation: pair entries two rows apart in each round column.
    sw = grids["Swiss Bracket"]
    cols = bracket_entries(sw, skip_rx=r"^bye\d*$|^\d+-\d+$|^\d{4}-\d\d-\d\d")
    for k, (c, ents) in enumerate(cols.items(), start=1):
        ents = sorted(ents, key=lambda e: e.row)
        i = 0
        while i < len(ents):
            a = ents[i]
            b = ents[i + 1] if i + 1 < len(ents) else None
            if b is not None and b.row - a.row == 2:
                if abs(a.scores[0]) < BIG and abs(b.scores[0]) < BIG:
                    w.game(a.name, b.name, a.scores[0], b.scores[0], stage="consolation",
                           round=f"Swiss {k}", seq=rr_rounds + k)
                elif a.scores[0] * b.scores[0] < 0 and min(abs(a.scores[0]), abs(b.scores[0])) >= BIG:
                    # +1e99 / -1e99 between two real teams: forfeit win
                    w.game(a.name, b.name, stage="consolation", round=f"Swiss {k}",
                           seq=rr_rounds + k, result="1" if a.scores[0] > 0 else "2",
                           forfeit=True, notes="forfeit (scored +/-1e99 in the sheet)")
                i += 2
            else:
                if abs(a.scores[0]) < BIG:
                    w.warn(f"Swiss {k}: unpaired entry {a.name} {a.scores[0]} (row {a.row})")
                i += 1
    hdr = [sw.text(0, c) for c in range(sw.ncols) if sw.text(0, c).startswith("Swiss")]
    if len(hdr) > len(cols):
        w.warn(f"Swiss rounds {hdr[len(cols):]} have no scores")
