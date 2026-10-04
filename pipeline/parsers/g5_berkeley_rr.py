"""Berkeley Science Bowl scoring template (Berkeley Dec 2024, Rice Dec 2025).

results.xlsx tabs:
  * 'Check-In Import' (hidden)  School Name | Team | coach | phone | Student 1..5
  * 'Morning RR'                 divisions of 6 teams; per team and round: Result | Score | Points
  * 'Round Robin Results' (hidden, imported from the scoring backend)
        team | This k | Opp k (k=1..5) | TU k | Penalty k | B k
        TU/Penalty/B k are comma-separated per-subject counts in the order
        Bio, Chem, E&S, Energy, Math, Physics (tossups correct, interrupt penalties
        committed, bonuses correct).
  * 'DE Bracket'                 visual double-elimination bracket (``team | score`` cells)

The opponent of each round is not listed, so RR games are rebuilt by pairing, within a
division and round, team X (this=a, opp=b) with the team Y (this=b, opp=a).
Scores of 1e+99 / -1e+99 mark byes. Player stats in this template are only "stat scores"
(TU + 0.5 x bonus - penalty style MVP numbers), which do not map onto correct/negs, so
they are not exported; rosters come from the check-in tab.
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import Grid, load_grids
from .g5_common import bracket_entries

SUBJECT_ORDER = ["biology", "chemistry", "ess", "energy", "math", "physics"]
BIG = 1e90


def _counts(s: str) -> list[float] | None:
    parts = [p.strip() for p in (s or "").split(",")]
    if len(parts) != 6 or not all(re.match(r"^-?\d+(\.\d+)?$", p) for p in parts):
        return None
    return [float(p) for p in parts]


def _divisions(m: Grid) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    cur = None
    for r in range(m.nrows):
        if m.text(r, 1).startswith("Division"):
            cur = m.text(r, 1)
            out[cur] = []
        elif cur and m.num(r, 0) is not None and m.text(r, 1):
            out[cur].append(m.text(r, 1))
    return out


def _match(teams: list[str], sc: dict[str, tuple[float, float]]) -> list[tuple[str, str]] | None:
    """Perfect matching of teams such that paired scores mirror each other."""
    if not teams:
        return []
    a, rest = teams[0], teams[1:]
    ta, oa = sc[a]
    for b in rest:
        tb, ob = sc[b]
        if tb == oa and ob == ta:
            sub = _match([x for x in rest if x != b], sc)
            if sub is not None:
                return [(a, b)] + sub
    return None


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
          rr_rounds: int = 5, de_scorer_check: bool = False) -> None:
    grids = load_grids(t.raw(results))
    ci = grids["Check-In Import"]
    for r in range(1, ci.nrows):
        team = ci.text(r, 1)
        if not team:
            continue
        players = [ci.text(r, c) for c in range(4, 9) if ci.text(r, c)]
        w.team(team, school=ci.text(r, 0), players=players)

    divs = _divisions(grids["Morning RR"])
    rr = grids["Round Robin Results"]
    hdr = rr.row_texts(0)
    col = {h: i for i, h in enumerate(hdr) if h}
    data: dict[str, dict] = {}
    for r in range(1, rr.nrows):
        team = rr.text(r, 0)
        if team:
            data[team] = {h: rr.cell(r, i) for h, i in col.items()}

    # Morning RR per-round result letters, for cross-checking.
    m = grids["Morning RR"]
    letters: dict[tuple[str, int], str] = {}
    for r in range(m.nrows):
        if m.num(r, 0) is not None and m.text(r, 1):
            for k in range(1, rr_rounds + 1):
                letters[(m.text(r, 1), k)] = m.text(r, 2 + 3 * (k - 1)).upper()[:1]

    for k in range(1, rr_rounds + 1):
        for div, teams in divs.items():
            sc = {}
            for tm in teams:
                if tm.upper() == "BYE" or tm not in data:
                    continue
                th, op = data[tm].get(f"This {k}"), data[tm].get(f"Opp {k}")
                if th is None or op is None or th == "" or op == "":
                    w.warn(f"{tm}: no score in round {k}")
                    continue
                th, op = float(th), float(op)
                if abs(th) >= BIG or abs(op) >= BIG:
                    continue  # bye
                sc[tm] = (th, op)
            pairs = _match(sorted(sc), sc)
            if pairs is None:
                w.warn(f"{div} round {k}: could not pair {sc}")
                continue
            for a, b in pairs:
                gid = w.game(a, b, sc[a][0], sc[b][0], stage="rr", round=f"RR{k}", seq=k,
                             notes=div)
                for x, y in ((a, b), (b, a)):
                    la = letters.get((x, k))
                    exp = "W" if sc[x][0] > sc[y][0] else "L" if sc[x][0] < sc[y][0] else "T"
                    if la and la != exp:
                        w.warn(f"{x} round {k}: Morning RR says {la}, scores say {exp}")
                _subjects(w, gid, a, b, data, k)

    _bracket(w, grids["DE Bracket"], rr_rounds)
    if de_scorer_check and "Copy of DE Scorer" in grids:
        _de_scorer_check(w, grids["Copy of DE Scorer"])


def _subjects(w: TournamentWriter, gid: str, a: str, b: str, data: dict, k: int) -> None:
    ca = {x: _counts(str(data[a].get(f"{x} {k}") or "")) for x in ("TU", "Penalty", "B")}
    cb = {x: _counts(str(data[b].get(f"{x} {k}") or "")) for x in ("TU", "Penalty", "B")}
    if any(v is None for v in (*ca.values(), *cb.values())):
        w.warn(f"game {gid} {a} vs {b}: missing subject breakdown")
        return
    bad = False
    for team, me, opp in ((a, ca, cb), (b, cb, ca)):
        score = float(data[team][f"This {k}"])
        calc = 4 * sum(me["TU"]) + 10 * sum(me["B"]) + 4 * sum(opp["Penalty"])
        if abs(calc - score) > 0.01:
            w.warn(f"game {gid} {team}: 4*TU+10*B+4*oppPen = {calc} != score {score}; "
                   f"subject breakdown skipped")
            bad = True
    if bad:
        return
    for team, me, opp in ((a, ca, cb), (b, cb, ca)):
        for i, subj in enumerate(SUBJECT_ORDER):
            tu, bo, ng = me["TU"][i], me["B"][i], me["Penalty"][i]
            w.team_game_subject(gid, team, subj, 4 * tu + 10 * bo, tossup_points=4 * tu,
                                bonus_points=10 * bo, tossups_correct=tu, negs=ng)


def _bracket(w: TournamentWriter, g: Grid, rr_rounds: int) -> None:
    cols = bracket_entries(g, skip_rx=r"^bye\d*$|^\[?bye\]?$|^L\d+$")
    rounds = []
    for c, ents in cols.items():
        ents = [e for e in ents if abs(e.scores[0]) < BIG]
        if len(ents) % 2:
            # a lone 1e99/-1e99 bye entry was dropped above; anything else is an error
            raise ValueError(f"DE column {c}: odd entries {[(e.row, e.name, e.scores) for e in ents]}")
        pairs = list(zip(ents[0::2], ents[1::2]))
        if pairs:
            rounds.append(pairs)
    n = len(rounds)
    for k, pairs in enumerate(rounds, start=1):
        label = f"DE{k}"
        if k == n:
            prev = rounds[k - 2] if k >= 2 else []
            if (len(pairs) == 1 and len(prev) == 1 and
                    {pairs[0][0].name, pairs[0][1].name} == {prev[0][0].name, prev[0][1].name}):
                label = "Final 2"
            else:
                label = "Final"
        elif k == n - 1 and len(pairs) == 1 and len(rounds[-1]) == 1 and \
                {pairs[0][0].name, pairs[0][1].name} == {rounds[-1][0][0].name, rounds[-1][0][1].name}:
            label = "Final"
        for a, b in pairs:
            w.game(a.name, b.name, a.scores[0], b.scores[0], stage="playoff", round=label,
                   seq=rr_rounds + k)


def _de_scorer_check(w: TournamentWriter, g: Grid) -> None:
    """Every team's DE scores in the DE scorer grid must appear in our bracket games."""
    have = defaultdict(list)
    for gm in w.rows["games"]:
        if gm["stage"] == "playoff":
            have[gm["team1"]].append(gm["score1"])
            have[gm["team2"]].append(gm["score2"])
    for r in range(g.nrows):
        if g.num(r, 0) is None or not g.text(r, 1):
            continue
        team = g.text(r, 1)
        scores = [g.num(r, c) for c in range(3, g.ncols, 3)
                  if g.text(r, c - 1)[:1] in ("W", "L", "T") and g.num(r, c) is not None]
        missing = [s for s in scores if s not in have.get(team, [])]
        if missing:
            w.warn(f"DE scorer: {team} scores {missing} not found in bracket games")
