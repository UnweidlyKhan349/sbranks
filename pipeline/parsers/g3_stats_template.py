"""Generated 'subject / all / bio ...' stats workbooks (2019-23 online events).

Tabs (one row per player or team, sorted by PPG):

    subject, subject_team   Player|GP|ppg|<one PPG column per subject>
    bonus                   team bonus conversion per subject
    all, all_team           Player|GP|4|-4|X|TUH|#buzz|%buzz|4s/-4|P/TUH|Points|PPG
    <subj>, <subj>_team     same columns, restricted to one category

Column labels vary between versions: ``4.0 / -4.0 / X`` (X = incorrect without penalty),
``4 / -4 / X`` or ``4s / 0s / -4s``. Subject tab names are bio, chem, energy, ess, math,
physics (DBHSST: life, physical; NSBA2: compsci). The team tabs' first column is ``Player``
in some versions and ``Team`` in others.

The player tabs have **no team column**. When team tabs exist, players are assigned to
teams by exact arithmetic: every team's per-subject (4s, -4s, 0s) totals must equal the sum
of its players' rows (the generator sums player rows into team rows). We enumerate, for
each team, the subsets of players whose vectors sum to the team vector, then solve the
exact cover (each player on exactly one team). A player is assigned only if every solution
found puts them on the same team; players with no buzzes at all cannot be placed this way
and are reported (and skipped) with a parser warning.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name
from ..util.grid import Grid, load_grids

_SKIP_TABS = {"subject", "subject_team", "bonus"}
# Extra subject labels used by some versions of the generator.
_EXTRA_SUBJECTS = {"physical": "other", "compsci": "other", "cs": "other"}

_COLS = {
    "gp": r"^GP$",
    "correct": r"^(4|4\.0|4s)$",
    "negs": r"^(-4|-4\.0|-4s)$",
    "zeros": r"^(X|0|0\.0|0s)$",
    "tuh": r"^TUH$",
    "points": r"^Points$",
    "ppg": r"^PPG$",
}
STAT_KEYS = ("correct", "negs", "zeros")


@dataclass
class StatRow:
    name: str
    gp: float | None = None
    tuh: float | None = None
    correct: float | None = None
    negs: float | None = None
    zeros: float | None = None
    points: float | None = None
    ppg: float | None = None


@dataclass
class TemplateStats:
    subjects: list[str]                                            # canonical, sheet order
    players: dict[str, dict[str, StatRow]] = field(default_factory=dict)   # name -> subj -> row
    teams: dict[str, dict[str, StatRow]] = field(default_factory=dict)
    player_order: list[str] = field(default_factory=list)
    subject_tabs: dict[str, list[str]] = field(default_factory=dict)  # canonical -> tab names


def _read_tab(g: Grid) -> list[StatRow]:
    hdr = g.row_texts(0)
    idx: dict[str, int] = {}
    for key, pat in _COLS.items():
        for i, h in enumerate(hdr):
            if i > 0 and re.match(pat, h, re.I):
                idx[key] = i
                break
    out = []
    for r in range(1, g.nrows):
        name = g.text(r, 0)
        if not name:
            continue
        row = StatRow(name=name)
        for key, i in idx.items():
            setattr(row, key, g.num(r, i))
        out.append(row)
    return out


def _keyed(rows: list[StatRow]) -> dict[str, StatRow]:
    """Rows keyed by name; a name used by several rows (two different players) is keyed
    ``name@GP`` so the rows can be lined up across tabs by games played."""
    count: dict[str, int] = defaultdict(int)
    for r in rows:
        count[r.name] += 1
    out: dict[str, StatRow] = {}
    for r in rows:
        key = r.name if count[r.name] == 1 else f"{r.name} @GP{r.gp:g}"
        if key in out:
            raise ValueError(f"cannot tell apart two rows named {r.name!r} with GP {r.gp}")
        out[key] = r
    return out


def read_template(path: Path, subject_map: dict[str, str] | None = None) -> TemplateStats:
    grids = load_grids(path)
    smap = {**_EXTRA_SUBJECTS, **(subject_map or {})}
    subjects: list[str] = []
    st = TemplateStats(subjects=subjects)
    for tab in grids:
        base = tab[:-5] if tab.endswith("_team") else tab
        if base in _SKIP_TABS:
            continue
        subj = "overall" if base == "all" else (smap.get(base) or normalize_subject(base))
        if subj is None:
            raise ValueError(f"{path.name}: unknown subject tab {tab!r}")
        if subj != "overall" and subj not in subjects:
            subjects.append(subj)
        if not tab.endswith("_team"):
            st.subject_tabs.setdefault(subj, [])
            if base not in st.subject_tabs[subj]:
                st.subject_tabs[subj].append(base)
        target = st.teams if tab.endswith("_team") else st.players
        for key, row in _keyed(_read_tab(grids[tab])).items():
            if tab == "all":
                st.player_order.append(key)
            d = target.setdefault(key, {})
            if subj in d:  # two source tabs mapped to one canonical subject: sum them
                d[subj] = _add(d[subj], row)
            else:
                d[subj] = row
    return st


def _add(a: StatRow, b: StatRow) -> StatRow:
    out = StatRow(name=a.name, gp=a.gp)
    for k in ("tuh", "correct", "negs", "zeros", "points"):
        va, vb = getattr(a, k), getattr(b, k)
        setattr(out, k, None if va is None and vb is None else (va or 0) + (vb or 0))
    if out.points is not None and a.gp:
        out.ppg = round(out.points / a.gp, 2)
    return out


# ---------------------------------------------------------------------------------------
# Player -> team assignment by exact sums
def _vector(rows: dict[str, StatRow], subjects: list[str]) -> tuple[int, ...]:
    v = []
    for s in subjects:
        r = rows.get(s)
        for k in STAT_KEYS:
            x = getattr(r, k) if r else None
            v.append(int(round(x or 0)))
    return tuple(v)


@dataclass
class Assignment:
    team_of: dict[str, str]                 # player -> team (only certain assignments)
    ambiguous: dict[str, set[str]]          # player -> candidate teams (multiple solutions)
    zero_players: list[str]                 # no buzzes: cannot be placed by sums
    unplaced: list[str]                     # nonzero players covered by no solution
    unmatched_teams: list[str]              # teams whose totals no subset reproduces
    n_solutions: int
    capped: bool


MISSING = "(players without a team row)"


class _Solver:
    """Assign players to teams so that every team's per-component sums are met exactly.

    Depth-first search with constraint propagation:

    * a player whose vector no longer fits any other candidate team is placed;
    * for a team component still to be filled, if the candidate contributors' total equals
      the remainder, all of them must be on that team (if it is smaller: dead end);
    * branching is on the unplaced player with the fewest candidate teams.

    Players with identical vectors and tossup profiles are interchangeable; they are kept
    in a fixed team order (symmetry breaking) and flagged ambiguous if a solution splits
    them across teams.
    """

    def __init__(self, pvec: dict[str, tuple[int, ...]], tvec: dict[str, tuple[int, ...]],
                 compat: dict[str, list[str]], sym_key: dict[str, Any]) -> None:
        self.pvec, self.tvec = pvec, tvec
        self.dim = len(next(iter(tvec.values())))
        self.teams = list(tvec)
        self.tix = {t: i for i, t in enumerate(self.teams)}
        self.compat = compat
        groups: dict[Any, list[str]] = defaultdict(list)
        for p in pvec:
            groups[sym_key[p]].append(p)
        self.prev_twin = {}
        for ps in groups.values():
            for a, b in zip(ps, ps[1:]):
                self.prev_twin[b] = a
        self.twins = {p: ps for ps in groups.values() for p in ps}
        self.solutions: list[dict[str, str]] = []
        self.nodes = 0
        self.stopped = False

    def run(self, limit: int, budget: int, forbid: tuple[str, str] | None = None) -> None:
        self.solutions, self.nodes, self.stopped = [], 0, False
        self.limit, self.budget = limit, budget
        cands = {p: set(self.compat[p]) for p in self.pvec}
        if forbid:
            cands[forbid[0]].discard(forbid[1])
        resid = {t: list(v) for t, v in self.tvec.items()}
        self._search(cands, resid, {})

    def _fits(self, p: str, t: str, resid: dict[str, list[int]]) -> bool:
        v, r = self.pvec[p], resid[t]
        for k in range(self.dim):
            if v[k] > r[k]:
                return False
        return True

    def _place(self, p: str, t: str, cands, resid, assign) -> bool:
        if not self._fits(p, t, resid):
            return False
        v = self.pvec[p]
        r = resid[t]
        for k in range(self.dim):
            r[k] -= v[k]
        assign[p] = t
        del cands[p]
        return True

    def _propagate(self, cands, resid, assign) -> bool:
        changed = True
        while changed:
            changed = False
            for p in list(cands):
                if p not in cands:
                    continue
                c = {t for t in cands[p] if self._fits(p, t, resid)}
                # symmetry breaking: a twin never goes to an earlier team than its predecessor
                tw = self.prev_twin.get(p)
                if tw is not None and tw in assign:
                    lo = self.tix[assign[tw]]
                    c = {t for t in c if self.tix[t] >= lo}
                if not c:
                    return False
                if len(c) == 1:
                    if not self._place(p, next(iter(c)), cands, resid, assign):
                        return False
                    changed = True
                else:
                    cands[p] = c
            for t in self.teams:
                r = resid[t]
                if not any(r):
                    continue
                contrib = [p for p, c in cands.items() if t in c]
                for k in range(self.dim):
                    if r[k] <= 0:
                        continue
                    ks = [p for p in contrib if self.pvec[p][k] > 0]
                    tot = sum(self.pvec[p][k] for p in ks)
                    if tot < r[k]:
                        return False
                    if tot == r[k]:
                        for p in ks:
                            if p in cands and not self._place(p, t, cands, resid, assign):
                                return False
                        changed = True
                        break
                if changed:
                    break
        return True

    def _search(self, cands, resid, assign) -> None:
        if self.stopped:
            return
        self.nodes += 1
        if self.nodes > self.budget:
            self.stopped = True
            return
        cands = {p: set(c) for p, c in cands.items()}
        resid = {t: list(r) for t, r in resid.items()}
        assign = dict(assign)
        if not self._propagate(cands, resid, assign):
            return
        if not cands:
            if all(not any(r) for r in resid.values()):
                self.solutions.append(assign)
                if len(self.solutions) >= self.limit:
                    self.stopped = True
            return
        p = min(cands, key=lambda q: (len(cands[q]), -sum(self.pvec[q])))
        for t in sorted(cands[p], key=lambda x: self.tix[x]):
            c2 = {q: set(c) for q, c in cands.items()}
            r2 = {x: list(r) for x, r in resid.items()}
            a2 = dict(assign)
            if self._place(p, t, c2, r2, a2):
                self._search(c2, r2, a2)
            if self.stopped:
                return


def assign_players(st: TemplateStats, *, solution_limit: int = 64,
                   budget: int = 200_000) -> Assignment:
    subs = [s for s in st.subjects]
    players = list(st.player_order) or list(st.players)
    pvec = {p: _vector(st.players[p], subs) for p in players}
    tvec = {t: _vector(rows, subs) for t, rows in st.teams.items()}
    tvec = {t: v for t, v in tvec.items() if any(v)}
    zero_players = [p for p in players if not any(pvec[p])]
    live = [p for p in players if any(pvec[p])]
    dim = len(next(iter(pvec.values()))) if pvec else 0
    # Players' totals minus teams' totals: if positive, some team has no row in the team
    # tabs; its players form one extra pseudo-team so that the cover stays exact.
    diff = [sum(pvec[p][k] for p in live) - sum(v[k] for v in tvec.values()) for k in range(dim)]
    if any(d < 0 for d in diff):
        raise ValueError(f"team totals exceed player totals: {diff}")
    if any(diff):
        tvec[MISSING] = tuple(diff)

    def tuh(rows: dict[str, StatRow], s: str) -> float:
        r = rows.get(s)
        return (r.tuh or 0) if r else 0

    def compatible(p: str, t: str) -> bool:
        if any(a > b for a, b in zip(pvec[p], tvec[t])):
            return False
        trows = st.teams.get(t, {})
        prow = st.players[p]
        # a player cannot hear more tossups (overall or per subject) than the team
        return not any(tuh(prow, s) > tuh(trows, s) + 1e-9
                       for s in ["overall", *subs] if s in trows)

    compat = {p: [t for t in tvec if compatible(p, t)] for p in live}
    sym_key = {p: (pvec[p], tuple(tuh(st.players[p], s) for s in ["overall", *subs]),
                   tuple(compat[p])) for p in live}
    pv = {p: pvec[p] for p in live}
    solver = _Solver(pv, tvec, compat, sym_key)
    solver.run(solution_limit, budget)
    sols, stopped = solver.solutions, solver.stopped

    team_of: dict[str, str] = {}
    ambiguous: dict[str, set[str]] = {}
    unplaced: list[str] = []
    if not sols:
        return Assignment({}, {}, zero_players, list(live), [], 0, solver.nodes > budget)
    inconclusive = False
    for p in live:
        ts = {s[p] for s in sols}
        twin_ts = {s[q] for s in sols for q in solver.twins[p]}
        if len(ts) > 1 or len(twin_ts) > 1:
            ambiguous[p] = ts | twin_ts
            continue
        t = next(iter(ts))
        if stopped:  # not every solution was seen: make sure none puts p elsewhere
            solver.run(1, budget // 4, forbid=(p, t))
            if solver.solutions or solver.stopped:
                inconclusive |= not solver.solutions
                ambiguous[p] = {t, "(other)"}
                continue
        if t == MISSING:
            unplaced.append(p)
        else:
            team_of[p] = t
    return Assignment(team_of, ambiguous, zero_players, unplaced, [], len(sols), inconclusive)


def assign_with_check(st: TemplateStats, w: TournamentWriter, **kw: Any) -> Assignment:
    a = assign_players(st, **kw)
    if a.capped:
        w.warn("player->team assignment search was capped; some assignments may be missing")
    if a.unmatched_teams:
        w.warn(f"no player subset reproduces team totals for: {', '.join(a.unmatched_teams)}")
    if a.ambiguous:
        w.warn(f"{len(a.ambiguous)} players fit several teams and were skipped: "
               + ", ".join(f"{p} ({'/'.join(sorted(ts))})" for p, ts in sorted(a.ambiguous.items())))
    if a.unplaced:
        w.warn(f"{len(a.unplaced)} players belong to no team listed in the team tabs (player "
               f"totals exceed team totals) and were skipped: {', '.join(a.unplaced)}")
    if a.zero_players:
        w.warn(f"{len(a.zero_players)} players with no buzzes could not be placed on a team: "
               + ", ".join(a.zero_players))
    return a


# ---------------------------------------------------------------------------------------
def player_display_name(name: str) -> str:
    n = clean_name(re.sub(r" @GP[\d.]+$", "", name))
    if re.match(r"^[^,#]+,\s*[^,#]+$", n):  # "Last, First" -> "First Last"
        last, first = [x.strip() for x in n.split(",", 1)]
        n = f"{first} {last}"
    return n


def write_player_stats(w: TournamentWriter, st: TemplateStats, team_of: dict[str, str], *,
                       scope: str = "all", team_map: dict[str, str] | None = None) -> int:
    """Write overall + per-subject rows for every player with a known team."""
    team_map = team_map or {}
    n = 0
    for p in st.player_order or list(st.players):
        team = team_of.get(p)
        if not team:
            continue
        team = team_map.get(team, team)
        name = player_display_name(p)
        for subj in ["overall", *st.subjects]:
            r = st.players[p].get(subj)
            if r is None:
                continue
            w.player_stat(name, team, subj, scope=scope, gp=r.gp, tuh=r.tuh, correct=r.correct,
                          zeros=r.zeros, negs=r.negs, points=r.points,
                          ppg=None if r.points is not None else r.ppg)
        n += 1
    return n


def team_names(st: TemplateStats) -> list[str]:
    """Team rows with any activity (skips template placeholders like 'Team Name' with GP 0)."""
    out = []
    for t, rows in st.teams.items():
        r = rows.get("overall")
        if r is None or not r.gp:
            continue
        out.append(t)
    return out


def parse_stats_only(t: Tournament, w: TournamentWriter, file: str = "stats.xlsx",
                     scope: str = "all", team_map: dict[str, str] | None = None,
                     subject_map: dict[str, str] | None = None) -> None:
    """Events whose only source is the stats workbook (no game results)."""
    st = read_template(t.raw(file), subject_map)
    team_map = team_map or {}
    for team in team_names(st):
        w.team(team_map.get(team, team))
    a = assign_with_check(st, w)
    write_player_stats(w, st, a.team_of, scope=scope, team_map=team_map)
