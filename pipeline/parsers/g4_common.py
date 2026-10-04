"""Shared helpers for the g4 parsers (DASONI / SMH / Catstats / LiveScoresheet / ASS).

* :class:`Roster` maps the abbreviated / misspelt team names used in schedules, brackets
  and stats tabs to one canonical spelling per tournament.
* :func:`seed_pair` reads Google-Sheets "1-2" pairings that were auto-converted to dates.
* :func:`read_bracket` reads a visual elimination bracket: every ``name | score`` cell pair is
  a bracket slot, and slots are paired top-down within a column (that is how all of these
  bracket templates are drawn). Round labels come from header rows.
* :func:`exact_int` turns a value derived from rounded source figures into an integer when
  the rounding error cannot reach the next integer (e.g. points = ppg * gp, ppg to 2 dp).
* :func:`assign_players` reconstructs player -> team membership from stats tabs that lost
  the team column, by exact matching of team totals to sums of player rows.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid


# ---- cell references ---------------------------------------------------------------------
def a1(refstr: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", refstr.strip().upper())
    if not m:
        raise ValueError(f"bad cell ref {refstr!r}")
    c = 0
    for ch in m.group(1):
        c = c * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, c - 1


def ref(r: int, c: int) -> str:
    s, c1 = "", c + 1
    while c1:
        c1, rem = divmod(c1 - 1, 26)
        s = chr(65 + rem) + s
    return f"{s}{r + 1}"


# ---- names -------------------------------------------------------------------------------
def norm(s: Any) -> str:
    s = clean_name(s).lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"^the ", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def _tok_fit(raw: str, cand: str) -> bool:
    """Every token of ``raw`` is a prefix of a distinct later token of ``cand`` (in order)."""
    rt, ct = raw.split(), cand.split()
    j = 0
    for t in rt:
        while j < len(ct) and not ct[j].startswith(t):
            j += 1
        if j == len(ct):
            return False
        j += 1
    return True


class Roster:
    """Canonical team names + alias / fuzzy resolution."""

    def __init__(self, names: Iterable[str] = (), aliases: dict[str, str] | None = None):
        self.names: list[str] = []
        self.aliases: dict[str, str] = {}
        for n in names:
            self.add(n)
        for k, v in (aliases or {}).items():
            self.aliases[norm(k)] = clean_name(v)

    def add(self, name: Any) -> str:
        n = clean_name(name)
        if n and n not in self.names:
            self.names.append(n)
        return n

    def candidates(self, raw: Any) -> list[str]:
        r = norm(raw)
        if not r:
            return []
        if r in self.aliases:
            return [self.aliases[r]]
        exact = [n for n in self.names if norm(n) == r]
        if exact:
            return exact
        squash = [n for n in self.names if norm(n).replace(" ", "") == r.replace(" ", "")]
        if squash:
            return squash
        pre = [n for n in self.names if norm(n).startswith(r + " ")]
        if pre:
            return pre
        fit = [n for n in self.names if _tok_fit(r, norm(n))]
        if fit:
            return fit
        rev = [n for n in self.names if r.startswith(norm(n) + " ")]
        return rev

    def resolve(self, raw: Any, within: Iterable[str] | None = None, required: bool = True) -> str | None:
        c = self.candidates(raw)
        if within is not None:
            w = set(within)
            c = [x for x in c if x in w] or ([] if c else c)
        if len(c) == 1:
            return c[0]
        if required:
            raise ValueError(f"cannot resolve team {raw!r}: candidates {c}")
        return None


# ---- schedule pairs ------------------------------------------------------------------------
def seed_pair(v: Any) -> tuple[int, int] | None:
    """'1-2' / '1 — 2' / 'A1 — A2' / a date that Sheets made out of '1-2' -> (1, 2)."""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.month, v.day
    s = clean_name(v)
    m = re.fullmatch(r"[A-Za-z]?(\d+)\s*[-—–]\s*[A-Za-z]?(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def code_pair(v: Any) -> tuple[str, str] | None:
    """'A1 — A2' -> ('A1', 'A2'); 'A1 BYE' -> None."""
    s = clean_name(v)
    m = re.fullmatch(r"([A-Za-z]+\d+)\s*[-—–]+\s*([A-Za-z]+\d+)", s)
    return (m.group(1).upper(), m.group(2).upper()) if m else None


# ---- exact arithmetic ------------------------------------------------------------------------
def exact_int(x: float | None, err: float = 0.06) -> int | None:
    """Round ``x`` when it is within ``err`` of an integer (rounding noise), else None."""
    if x is None:
        return None
    r = round(x)
    return int(r) if abs(x - r) <= err else None


def split_tag(s: str) -> tuple[str, str]:
    """'yufei [Emmyversity]' -> ('yufei', 'Emmyversity'); no tag -> (s, '')."""
    m = re.fullmatch(r"(.*?)\s*\[(.*)\]\s*", clean_name(s))
    if m:
        return clean_name(m.group(1)), clean_name(m.group(2))
    return clean_name(s), ""


# ---- brackets -------------------------------------------------------------------------------
@dataclass
class Slot:
    r: int
    c: int
    raw: str
    score: float | None
    team: str = ""

    @property
    def where(self) -> str:
        return ref(self.r, self.c)


@dataclass
class BGame:
    a: Slot
    b: Slot
    round: str
    col: int
    seq: int = 0
    note: str = ""
    winner: str = ""
    explicit: bool = False

    @property
    def gid(self) -> str:
        return f"de-{self.a.where}" + ("x" if self.explicit else "")


def read_bracket(g: Grid, roster: Roster, *, header_rows: Iterable[int] = (0,),
                 seeds: dict[int, str] | None = None, cell_names: dict[str, str] | None = None,
                 skip_names: str = r"^(bye|tbd|tba)$", skip_cells: Iterable[str] = (),
                 round_labels: dict[int, str] | None = None, min_col: int = 0,
                 max_col: int | None = None, extra: Iterable[str] = (),
                 start_losses: dict[str, int] | None = None,
                 label_rx: str | None = None,
                 teams: Iterable[str] | None = None) -> list[BGame]:
    """Read a visual bracket into games (columns left -> right, slots paired top-down).

    ``seeds``: seed number -> team; used when a slot has a seed number in the cell left of it.
    ``cell_names``: A1 ref of a name cell -> canonical team (overrides resolution).
    ``round_labels``: column (0-based, of the name cell) -> round label.
    ``extra``: explicit games "Round|NAME1|SCORE1|NAME2|SCORE2" (A1 refs) for layouts that the
    column rule cannot express (e.g. a best-of-3 final with two score columns).
    ``start_losses``: team -> losses carried into the bracket (seeds that start in the one-loss
    bracket); only used to tell apart same-school teams in later rounds.
    ``teams``: the teams that qualified for the bracket (restricts name resolution).
    """
    qualified = set(teams) if teams else None
    cell_names = {k.upper(): v for k, v in (cell_names or {}).items()}
    round_labels = {int(k): v for k, v in (round_labels or {}).items()}
    skip = {s.upper() for s in skip_cells}
    rx_skip = re.compile(skip_names, re.I)
    by_col: dict[int, list[Slot]] = defaultdict(list)
    last = g.ncols if max_col is None else max_col + 1
    for r in range(g.nrows):
        for c in range(min_col, last):
            t = g.text(r, c)
            if not t or num(g.cell(r, c)) is not None or rx_skip.search(t):
                continue
            s = num(g.cell(r, c + 1))
            if s is None or ref(r, c) in skip:
                continue
            by_col[c].append(Slot(r, c, t, s))
    hdr = list(header_rows)

    def label(c: int) -> str:
        if round_labels and c in round_labels:
            return round_labels[c]
        for cc in (c, c + 1, c - 1):
            for hr in hdr:
                t = g.text(hr, cc)
                if t and num(g.cell(hr, cc)) is None:
                    if label_rx and (m := re.search(label_rx, t)):
                        return clean_name(m.group(1))
                    return t
        return f"col{c}"

    games: list[BGame] = []
    for c in sorted(by_col):
        slots = by_col[c]
        if len(slots) % 2:
            raise ValueError(f"bracket column {c}: odd number of slots "
                             f"{[s.where + ':' + s.raw for s in slots]}")
        for i in range(0, len(slots), 2):
            games.append(BGame(slots[i], slots[i + 1], label(c), c))
    for spec in extra:
        rnd, n1, s1, n2, s2 = [x.strip() for x in spec.split("|")]
        (r1, c1), (r2, c2) = a1(n1), a1(n2)
        sa = Slot(r1, c1, g.text(r1, c1), num(g.cell(*a1(s1))))
        sb = Slot(r2, c2, g.text(r2, c2), num(g.cell(*a1(s2))))
        gm = BGame(sa, sb, rnd, max(c1, c2), explicit=True)
        games.append(gm)
    games.sort(key=lambda gm: (gm.col, gm.a.r))

    # resolve names in play order, using the bracket so far to break ties between A/B teams
    seen: list[str] = []
    losses: dict[str, int] = defaultdict(int, start_losses or {})
    for gm in games:
        for s in (gm.a, gm.b):
            if s.where in cell_names:
                s.team = cell_names[s.where]
                continue
            sd = num(g.cell(s.r, s.c - 1))
            if seeds and sd is not None and int(sd) in seeds:
                s.team = seeds[int(sd)]
                continue
            cands = roster.candidates(s.raw)
            if qualified is not None and len(cands) > 1:
                cands = [x for x in cands if x in qualified] or cands
            if len(cands) > 1:
                alive = [x for x in cands if x in seen and losses[x] < 2]
                cands = alive if alive else cands
            if len(cands) != 1:
                raise ValueError(f"bracket cell {s.where} {s.raw!r}: candidates {cands}")
            s.team = cands[0]
        for s in (gm.a, gm.b):
            if s.team not in seen:
                seen.append(s.team)
        if gm.a.score is not None and gm.b.score is not None and gm.a.score != gm.b.score:
            loser = gm.b.team if gm.a.score > gm.b.score else gm.a.team
            losses[loser] += 1
    # seq by column order of the round labels
    order: list[str] = []
    for gm in games:
        if gm.round not in order:
            order.append(gm.round)
    for gm in games:
        gm.seq = order.index(gm.round)
    return games


def advanced(games: list[BGame], gm: BGame) -> str | None:
    """Which team of a (tied) game appears in a later column of the bracket."""
    later = {s.team for x in games if x.col > gm.col for s in (x.a, x.b)}
    a, b = gm.a.team in later, gm.b.team in later
    if a != b:
        return gm.a.team if a else gm.b.team
    return None


def write_bracket(w: TournamentWriter, games: list[BGame], *, seq_base: int = 100,
                  stage: str = "playoff", forfeits: Iterable[str] = (),
                  notes: dict[str, str] | None = None, final_text: str = "") -> None:
    forfeits = {f.upper() for f in forfeits}
    notes = {k.upper(): v for k, v in (notes or {}).items()}
    for gm in games:
        note = gm.note
        s1, s2 = gm.a.score, gm.b.score
        result = ""
        if s1 is not None and s2 is not None and s1 == s2:
            adv = advanced(games, gm)
            note = (note + "; " if note else "") + (
                f"tied {s1:g}-{s2:g} in the bracket; {adv} advanced (tiebreaker not recorded)"
                if adv else f"tied {s1:g}-{s2:g} in the bracket")
        extra = notes.get(gm.gid[3:].upper())
        if extra:
            note = (note + "; " if note else "") + extra
        w.game(gm.a.team, gm.b.team, s1, s2, stage=stage, round=gm.round, seq=seq_base + gm.seq,
               result=result, forfeit=gm.a.where in forfeits, game_id=gm.gid, notes=note)


def bracket_summary(games: list[BGame]) -> dict[str, tuple[int, int]]:
    rec: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for gm in games:
        if gm.a.score is None or gm.b.score is None or gm.a.score == gm.b.score:
            continue
        win, lose = (gm.a, gm.b) if gm.a.score > gm.b.score else (gm.b, gm.a)
        rec[win.team][0] += 1
        rec[lose.team][1] += 1
    return {k: (v[0], v[1]) for k, v in rec.items()}


# ---- player -> team reconstruction -----------------------------------------------------------
def assign_players(players: dict[str, list[float]], teams: dict[str, list[float]],
                   allowed: dict[str, set[str]] | None = None, max_size: int = 8,
                   max_solutions: int = 2) -> list[dict[str, str]]:
    """Partition players into teams so that each team's vector equals the sum of its players'.

    ``players`` / ``teams``: name -> vector of non-negative counts (same layout).
    ``allowed``: optional player -> set of teams it may belong to (e.g. from GP limits or a
    "(Team)" annotation). Players whose vector is all zero are ignored (they cannot be placed).
    Returns up to ``max_solutions`` complete assignments (player -> team).
    """
    pl = {p: v for p, v in players.items() if any(x for x in v)}
    tnames = list(teams)
    dim = len(next(iter(teams.values())))
    cand: dict[str, list[str]] = {}
    for t in tnames:
        tv = teams[t]
        cand[t] = [p for p, v in pl.items()
                   if all(v[i] <= tv[i] + 1e-9 for i in range(dim))
                   and (allowed is None or p not in allowed or t in allowed[p])]
    sols: list[dict[str, str]] = []

    def subsets(t: str, avail: set[str]) -> Iterable[list[str]]:
        cs = [p for p in cand[t] if p in avail]
        cs.sort(key=lambda p: -sum(pl[p]))
        target = teams[t]
        n = len(cs)
        # suffix sums for pruning
        suf = [[0.0] * dim for _ in range(n + 1)]
        for i in range(n - 1, -1, -1):
            suf[i] = [suf[i + 1][k] + pl[cs[i]][k] for k in range(dim)]

        def rec(i: int, rem: list[float], chosen: list[str]):
            if all(abs(x) < 1e-9 for x in rem):
                yield list(chosen)
                return
            if i == n or len(chosen) >= max_size:
                return
            if any(suf[i][k] < rem[k] - 1e-9 for k in range(dim)):
                return
            v = pl[cs[i]]
            if all(v[k] <= rem[k] + 1e-9 for k in range(dim)):
                chosen.append(cs[i])
                yield from rec(i + 1, [rem[k] - v[k] for k in range(dim)], chosen)
                chosen.pop()
            yield from rec(i + 1, rem, chosen)

        yield from rec(0, list(target), [])

    def solve(remaining: list[str], avail: set[str], cur: dict[str, str]) -> None:
        if len(sols) >= max_solutions:
            return
        if not remaining:
            if not avail:
                sols.append(dict(cur))
            return
        # every remaining player must still have a remaining team that can take it
        for p in avail:
            if not any(p in cand[t] for t in remaining):
                return
        t = min(remaining, key=lambda t: sum(1 for p in cand[t] if p in avail))
        rest = [x for x in remaining if x != t]
        for sub in subsets(t, avail):
            for p in sub:
                cur[p] = t
            solve(rest, avail - set(sub), cur)
            for p in sub:
                del cur[p]
            if len(sols) >= max_solutions:
                return

    solve(tnames, set(pl), {})
    return sols


# ---- stats rows (SMH / Catstats / ICSBT "gp, tuh, buzzes, ppg, npg, accuracy" layouts) -------
def _hdr_rate(h: str) -> int | None:
    m = re.search(r"(?:pts|pp|points)\s*/?\s*(\d+)\s*tu", h, re.I)
    return int(m.group(1)) if m else None


def stat_columns(headers: list[str]) -> dict[str, int]:
    """Locate the usual columns of these stats exports (case-insensitive header match)."""
    out: dict[str, int] = {}
    for i, h in enumerate(headers):
        k = h.strip().lower()
        if not k:
            continue
        if re.fullmatch(r"games ?played|gp", k):
            out.setdefault("gp", i)
        elif re.fullmatch(r"tuh|tossups heard|tus heard|qs played", k):
            out.setdefault("tuh", i)
        elif re.fullmatch(r"buzzes|#buzz", k):
            out.setdefault("buzzes", i)
        elif re.fullmatch(r"ppg", k):
            out.setdefault("ppg", i)
        elif re.fullmatch(r"points|total points", k):
            out.setdefault("points", i)
        elif re.fullmatch(r"npg|negs/game", k):
            out.setdefault("npg", i)
        elif re.fullmatch(r"negs|total negs", k):
            out.setdefault("negs", i)
        elif re.fullmatch(r"acc(uracy)?\.?", k):
            out.setdefault("acc", i)
        elif re.match(r"(pts|pp)\s*/?\s*\d+\s*tuh", k):
            out.setdefault("rate_pts", i)
            out["rate_pts_n"] = _hdr_rate(k) or 0
        elif re.match(r"negs\s*/\s*\d+\s*tuh", k):
            out.setdefault("rate_negs", i)
            out["rate_negs_n"] = int(re.search(r"(\d+)", k).group(1))
    return out


@dataclass
class Counts:
    gp: float | None
    tuh: float | None
    buzzes: float | None
    correct: int | None
    negs: int | None
    points: int | None
    zeros: int | None
    problem: str = ""


def derive_counts(gp: Any, tuh: Any, buzzes: Any, *, ppg: Any = None, npg: Any = None,
                  points: Any = None, negs: Any = None, acc: Any = None,
                  rate_pts: Any = None, rate_pts_n: int | None = None,
                  rate_negs: Any = None, rate_negs_n: int | None = None,
                  ppg_dp: int = 2) -> Counts:
    """Integer tossup counts from a row of rounded per-game figures.

    points: the 'Points' column if present, else ppg*gp (exact when the 2-dp rounding error
    times gp stays below 0.5), else rate*tuh/N.  negs likewise.  correct = (points+4*negs)/4.
    The accuracy column (correct/buzzes, 3 dp) is used as a check only.
    """
    gp, tuh, buzzes = num(gp), num(tuh), num(buzzes)
    tol = (0.5 * 10 ** -ppg_dp) * (gp or 0) + 1e-6
    pts = exact_int(num(points), 0.01) if num(points) is not None else None
    if pts is None and num(ppg) is not None and gp is not None and tol < 0.5:
        pts = exact_int(num(ppg) * gp, max(tol, 0.01))
    if pts is None and num(rate_pts) is not None and tuh and rate_pts_n:
        pts = exact_int(num(rate_pts) * tuh / rate_pts_n, 0.02)
    ng = exact_int(num(negs), 0.06) if num(negs) is not None else None
    if ng is None and num(npg) is not None and gp is not None and tol < 0.5:
        ng = exact_int(num(npg) * gp, max(tol, 0.01))
    if ng is None and num(rate_negs) is not None and tuh and rate_negs_n:
        ng = exact_int(num(rate_negs) * tuh / rate_negs_n, 0.02)
    out = Counts(gp, tuh, buzzes, None, ng, pts, None)
    if pts is None and num(points) is not None:
        out.points = round(num(points), 2)   # the source's own (non-integer) figure
    if pts is None or ng is None:
        out.problem = f"points/negs not exactly derivable (points {num(points)}, negs {num(negs)})"
        out.negs = None
        return out
    if (pts + 4 * ng) % 4:
        out.problem = f"points {pts} not a multiple of 4; kept as given, no correct/negs"
        out.negs = None
        return out
    c = (pts + 4 * ng) // 4
    out.correct = c
    if buzzes is not None:
        z = int(round(buzzes)) - c - ng
        if z < 0:
            out.problem = f"correct+negs {c + ng} > buzzes {buzzes:g}"
        else:
            out.zeros = z
        a = num(acc)
        if a is not None and buzzes > 0 and abs(a * buzzes - c) > 0.0006 * buzzes + 0.02:
            out.problem = f"accuracy {a} * buzzes {buzzes:g} != correct {c}"
    return out


# ---- round-robin score grids -----------------------------------------------------------------
@dataclass
class ScoreGrid:
    title: str            # group label (text above the anchor, if any)
    r: int                # anchor row (column-label row)
    c: int                # anchor col (row-label col)
    labels: list[str]     # team labels in grid order
    cells: list[list[Any]]  # cells[i][j] = raw score cell of row team i vs col team j


def find_grids(g: Grid, stop: str = r"^(wins|ties|losses|points|ppg|total|rr score|record)$") -> list[ScoreGrid]:
    """Find square score grids: a header row of team labels and the same labels down a column.

    The anchor cell (top-left) usually holds a number (sum of scores) or is blank.
    """
    rx_stop = re.compile(stop, re.I)
    out: list[ScoreGrid] = []
    used: set[tuple[int, int]] = set()
    for r in range(g.nrows - 1):
        for c in range(g.ncols):
            if (r, c) in used:
                continue
            first = g.text(r, c + 1)
            if not first or num(g.cell(r, c + 1)) is not None or g.text(r + 1, c) != first:
                continue
            labels = []
            k = c + 1
            while g.text(r, k) and not rx_stop.search(g.text(r, k)) and num(g.cell(r, k)) is None:
                labels.append(g.text(r, k))
                k += 1
            n = 0
            while n < len(labels) and g.text(r + 1 + n, c) == labels[n]:
                n += 1
            if n < 2:
                continue
            labels = labels[:n]
            cells = [[g.cell(r + 1 + i, c + 1 + j) for j in range(n)] for i in range(n)]
            title = ""
            for rr in range(r - 1, max(r - 3, -1), -1):
                if g.text(rr, c):
                    title = g.text(rr, c)
                    break
            out.append(ScoreGrid(title, r, c, labels, cells))
            used.update((r, cc) for cc in range(c, c + n + 1))
    return out


def grid_pairs(sg: ScoreGrid, skip_labels: str = r"^bye$") -> Iterable[tuple[int, int, Any, Any]]:
    """Yield (i, j, cell_ij, cell_ji) for i < j where at least one cell is filled."""
    rx = re.compile(skip_labels, re.I)
    n = len(sg.labels)
    for i in range(n):
        for j in range(i + 1, n):
            if rx.search(sg.labels[i]) or rx.search(sg.labels[j]):
                continue
            a, b = sg.cells[i][j], sg.cells[j][i]
            if clean_name(a) in ("", "-") and clean_name(b) in ("", "-"):
                continue
            yield i, j, a, b
