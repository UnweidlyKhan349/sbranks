"""Shared helpers for the g7 group (2024-26 online invitationals with stats).

* :class:`Teams` - canonical team names + alias/code resolution ("A3", "J4 - James Clemens",
  "interlake 2 (A4)", "Galen A 1", case/spacing variants, explicit aliases).
* :func:`grid_pairs` - round-robin grids where row = team and column = opponent; one game per
  pair, both cells cross-checked (optionally against W/L/T letters).
* :func:`bracket_entries` / :func:`bracket_pairs` - visual bracket sheets where each round is a
  column of ``team | score`` cells and consecutive entries in a column are one game. Games
  without scores get their winner from the next column that holds one of the two teams
  between the two rows (i.e. where the winner's line leads).
* :func:`rates_to_counts` - turn GP/buzzes/PPG/NPG/accuracy rows into exact counts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid

BYE_RX = re.compile(r"^\W*bye\W*$", re.I)


def key(s: Any) -> str:
    s = clean_name(s).lower().replace("&", " and ")
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class Teams:
    """Canonical team names of one tournament with alias resolution."""

    def __init__(self, names: Iterable[str] = (), aliases: dict[str, str] | None = None,
                 codes: dict[str, str] | None = None):
        self.names: list[str] = []
        self._alias: dict[str, str] = {}
        self.codes: dict[str, str] = {}
        for n in names:
            self.add(n)
        for code, n in (codes or {}).items():
            self.add_code(code, n)
        for a, n in (aliases or {}).items():
            self.alias(a, n)

    def add(self, name: str, *aliases: str) -> str:
        n = clean_name(name)
        if n and n not in self.names:
            self.names.append(n)
        if n:
            self._alias.setdefault(key(n), n)
        for a in aliases:
            self.alias(a, n)
        return n

    def alias(self, alias: str, name: str) -> None:
        n = self.resolve(name) or clean_name(name)
        if n not in self.names:
            self.add(n)
        self._alias[key(alias)] = n

    def add_code(self, code: str, name: str) -> None:
        n = self.resolve(name) or self.add(name)
        self.codes[clean_name(code).upper()] = n

    def resolve(self, text: Any) -> str | None:
        t = clean_name(text)
        if not t or BYE_RX.match(t):
            return None
        k = key(t)
        if k in self._alias:
            return self._alias[k]
        if t.upper() in self.codes:
            return self.codes[t.upper()]
        # "J4 - James Clemens" / "A1: Name"
        m = re.match(r"^([A-Za-z]{1,2}\d{1,2})\s*[-:–]\s*(.+)$", t)
        if m and m.group(1).upper() in self.codes:
            return self.codes[m.group(1).upper()]
        # "interlake 2 (A4)" / "Name (#3)" / "Name [A4]"
        m = re.match(r"^(.*?)\s*[(\[]\s*#?([A-Za-z]{0,2}\d{1,2})\s*[)\]]$", t)
        if m:
            if m.group(2).upper() in self.codes:
                return self.codes[m.group(2).upper()]
            r = self.resolve(m.group(1))
            if r:
                return r
        # leading seed "1. Name" / "#3 Name"
        m = re.match(r"^#?\d{1,2}[.)]?\s+(.+)$", t)
        if m and key(m.group(1)) in self._alias:
            return self._alias[key(m.group(1))]
        # trailing seed "Galen A 1"
        m = re.match(r"^(.+?)\s+#?\d{1,2}$", t)
        if m and key(m.group(1)) in self._alias:
            return self._alias[key(m.group(1))]
        return None

    def need(self, text: Any) -> str:
        r = self.resolve(text)
        if r is None:
            raise KeyError(f"unknown team {text!r}")
        return r


# ---------------------------------------------------------------------------------------
# Round-robin grids
# ---------------------------------------------------------------------------------------
@dataclass
class Pair:
    team1: str
    team2: str
    score1: float | None
    score2: float | None
    result: str = ""
    forfeit: bool = False
    notes: str = ""


_OPP = {"W": "L", "L": "W", "T": "T", "D": "D"}


def grid_pairs(g: Grid, rows: list[tuple[int, str]], cols: list[tuple[int, str]], *,
               row_scores: bool = True, score_off: int = 0, wl_off: int | None = None,
               w: TournamentWriter | None = None, label: str = "",
               forfeit: Callable[[float | None, float | None, str, str], Pair | None] | None = None
               ) -> list[Pair]:
    """One :class:`Pair` per unordered pair of teams in a row-vs-column grid block.

    ``rows`` = [(row index, team)], ``cols`` = [(column index, team)]. The cell at (row of A,
    column of B) is A's score against B when ``row_scores`` (else B's score against A).
    ``wl_off``: offset of a W/L/T letter cell relative to the score cell (checked).
    ``forfeit(sA, sB, A, B)`` may return a replacement Pair for forfeit markers.
    """
    col_of = {t: c for c, t in cols}
    row_of = {t: r for r, t in rows}
    teams = [t for _, t in rows if t in col_of]
    out = []

    def score(a: str, b: str) -> float | None:  # a's score against b
        if row_scores:
            return g.num(row_of[a], col_of[b] + score_off)
        return g.num(row_of[b], col_of[a] + score_off)

    def letter(a: str, b: str) -> str:
        if wl_off is None:
            return ""
        if row_scores:
            return g.text(row_of[a], col_of[b] + score_off + wl_off).upper()[:1]
        return g.text(row_of[b], col_of[a] + score_off + wl_off).upper()[:1]

    for i, a in enumerate(teams):
        for b in teams[i + 1:]:
            sa, sb = score(a, b), score(b, a)
            if forfeit:
                p = forfeit(sa, sb, a, b)
                if p is not None:
                    out.append(p)
                    continue
            if sa is None and sb is None:
                if w and (letter(a, b) or letter(b, a)):
                    w.warn(f"{label}: {a} vs {b} has W/L but no scores")
                continue
            if sa is None or sb is None:
                if w:
                    w.warn(f"{label}: one-sided score {a} {sa} vs {b} {sb}; skipped")
                continue
            exp = "W" if sa > sb else "L" if sa < sb else "T"
            la, lb = letter(a, b), letter(b, a)
            if la in ("W", "L") and lb == _OPP[la] and la != exp:
                # both cells agree on a winner the scores do not show (e.g. a tie broken by
                # a tiebreaker): keep the official result, drop the contradictory scores
                if w:
                    w.warn(f"{label}: {a} {sa:g}-{sb:g} {b} but marked {a} {la}; result kept, scores dropped")
                out.append(Pair(a, b, None, None, "1" if la == "W" else "2",
                                notes=f"sheet shows {sa:g}-{sb:g} but marks {a if la == 'W' else b} as winner"))
                continue
            for lt, e, who in ((la, exp, a), (lb, _OPP[exp], b)):
                if lt and lt not in (e, "D" if e == "T" else e) and w:
                    w.warn(f"{label}: {a} {sa}-{sb} {b}: {who} marked {lt}")
            out.append(Pair(a, b, sa, sb))
    return out


def schedule_round_map(pairs: Iterable[tuple[str, str, Any]]) -> dict[frozenset, Any]:
    return {frozenset((a, b)): rnd for a, b, rnd in pairs}


# ---------------------------------------------------------------------------------------
# Brackets
# ---------------------------------------------------------------------------------------
@dataclass
class Entry:
    row: int
    col: int
    team: str
    scores: list[float | None] = field(default_factory=list)
    raw: str = ""


@dataclass
class BGame:
    col: int
    team1: str
    team2: str
    score1: float | None
    score2: float | None
    result: str
    rows: tuple[int, int]
    part: int = 1           # 2 for the second game of a two-game final
    notes: str = ""


def bracket_entries(g: Grid, teams: Teams, *, rows: tuple[int, int | None] = (0, None),
                    cols: tuple[int, int | None] = (0, None), score_below: bool = False,
                    ignore: Iterable[tuple[int, int]] = (), second_score: bool = True,
                    embedded: bool = False) -> dict[int, list[Entry]]:
    """All team cells of a bracket area, grouped by column (each with its score cells)."""
    ign = {tuple(x) for x in ignore}
    r0, r1 = rows[0], g.nrows if rows[1] is None else min(rows[1], g.nrows)
    c0, c1 = cols[0], g.ncols if cols[1] is None else min(cols[1], g.ncols)
    out: dict[int, list[Entry]] = {}
    for r in range(r0, r1):
        for c in range(c0, c1):
            if (r, c) in ign:
                continue
            v = g.cell(r, c)
            if v is None or isinstance(v, (int, float)):
                continue
            t = clean_name(v)
            if not t or num(t) is not None:
                continue
            team = teams.resolve(t)
            scores: list[float | None] = []
            if embedded and g.num(r, c + 1) is None:
                # "NOHO 1 30": team name with the score in the same cell
                m = re.match(r"^(.*\S)\s+(-?\d+(?:\.\d+)?)$", t)
                if m and key(t) not in teams._alias and teams.resolve(m.group(1)):
                    team = teams.resolve(m.group(1))
                    scores = [float(m.group(2))]
            if team is None:
                continue
            if not scores:
                s = g.num(r, c + 1)
                if s is None and score_below and not g.text(r + 1, c):
                    s = g.num(r + 1, c + 1)
                scores = [s]
                if second_score and s is not None:
                    s2 = g.num(r, c + 2)
                    if s2 is not None:
                        scores.append(s2)
            out.setdefault(c, []).append(Entry(r, c, team, scores, t))
    return dict(sorted(out.items()))


def bracket_pairs(ents: dict[int, list[Entry]], *, w: TournamentWriter | None = None,
                  champion: str | None = None, label: str = "bracket",
                  infer_only_cols: Iterable[int] = ()) -> list[BGame]:
    """Pair consecutive entries per column into games (see module docstring).

    ``infer_only_cols``: columns that only repeat the previous round's winners (no games of
    their own); they are used to find winners of unscored games.
    """
    games: list[BGame] = []
    cols = sorted(ents)
    skip = set(infer_only_cols)
    for ci, c in enumerate(cols):
        if c in skip:
            continue
        es = sorted(ents[c], key=lambda e: e.row)
        if len(es) % 2:
            if w:
                w.warn(f"{label}: column {c} has an odd number of team cells "
                       f"{[(e.row, e.team) for e in es]}; last one ignored")
            es = es[:-1]
        for a, b in zip(es[0::2], es[1::2]):
            if a.team == b.team:
                if w:
                    w.warn(f"{label}: col {c} rows {a.row}/{b.row} pair {a.team} with itself; skipped")
                continue
            sa, sb = a.scores[0], b.scores[0]
            if sa is not None and sb is not None:
                games.append(BGame(c, a.team, b.team, sa, sb, "", (a.row, b.row)))
                if len(a.scores) > 1 and len(b.scores) > 1:
                    games.append(BGame(c, a.team, b.team, a.scores[1], b.scores[1], "",
                                       (a.row, b.row), part=2))
                continue
            if (sa is None) != (sb is None):
                if w:
                    w.warn(f"{label}: col {c} {a.team} {sa} vs {b.team} {sb}: one score missing; skipped")
                continue
            # no scores: follow the winner's line to the next column
            winner = None
            for c2 in cols[ci + 1:]:
                hit = [e for e in ents[c2] if a.row <= e.row <= b.row and e.team in (a.team, b.team)]
                if hit:
                    winner = hit[0].team
                    break
            if winner is None and champion and ci == len(cols) - 1:
                winner = champion if champion in (a.team, b.team) else None
            if winner is None:
                if w:
                    w.warn(f"{label}: col {c} {a.team} vs {b.team}: no scores and no winner; skipped")
                continue
            games.append(BGame(c, a.team, b.team, None, None, "1" if winner == a.team else "2",
                               (a.row, b.row), notes="no scores in source; winner from bracket"))
    return games


def column_labels(g: Grid, header_rows: Iterable[int], cols: Iterable[int]) -> dict[int, str]:
    """Map each bracket column to the nearest header text at or left of it."""
    heads: list[tuple[int, str]] = []
    for hr in header_rows:
        for c in range(g.ncols):
            t = g.text(hr, c)
            if t:
                heads.append((c, t))
    out = {}
    for c in cols:
        best = [h for h in heads if h[0] <= c]
        out[c] = max(best)[1] if best else ""
    return out


def emit_bracket(w: TournamentWriter, games: list[BGame], *, round_of: dict[int, str] | None = None,
                 seq0: int = 100, stage: str = "playoff", final_cols: Iterable[int] = (),
                 gid_prefix: str = "de", forfeit_pairs: Iterable[frozenset] = ()) -> None:
    """Write bracket games. Round = column label; seq = seq0 + column rank."""
    cols = sorted({gm.col for gm in games})
    rank = {c: i for i, c in enumerate(cols)}
    ff = set(forfeit_pairs)
    n = 0
    for gm in sorted(games, key=lambda x: (x.col, x.part, x.rows)):
        lbl = (round_of or {}).get(gm.col) or f"DE{rank[gm.col] + 1}"
        if gm.part == 2 or any(o.col == gm.col and o.part == 2 and o.rows == gm.rows for o in games):
            lbl = f"{lbl} (game {gm.part})"
        n += 1
        w.game(gm.team1, gm.team2, gm.score1, gm.score2, stage=stage, round=lbl,
               seq=seq0 + 2 * rank[gm.col] + (gm.part - 1), result=gm.result,
               forfeit=frozenset((gm.team1, gm.team2)) in ff, game_id=f"{gid_prefix}{n}",
               notes=gm.notes)


def bracket_check(games: list[BGame], w: TournamentWriter, label: str = "bracket",
                  max_losses: int = 2) -> None:
    """Warn when a team loses more than ``max_losses`` bracket games or plays after elimination."""
    losses: dict[str, int] = {}
    for gm in sorted(games, key=lambda x: (x.col, x.part)):
        res = gm.result or ("1" if gm.score1 > gm.score2 else "2" if gm.score2 > gm.score1 else "T")
        for t in (gm.team1, gm.team2):
            if losses.get(t, 0) >= max_losses:
                w.warn(f"{label}: {t} plays in column {gm.col} after {losses[t]} losses")
        if res in ("1", "2"):
            loser = gm.team2 if res == "1" else gm.team1
            losses[loser] = losses.get(loser, 0) + 1


# ---------------------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------------------
def rates_to_counts(gp: float | None, buzzes: float | None, ppg: float | None,
                    npg: float | None, acc: float | None, *, acc_pct: bool = False
                    ) -> dict[str, float] | None:
    """Exact counts from GP / buzzes / PPG / NPG / accuracy (= correct / buzzes).

    negs = NPG*GP and correct = buzzes*accuracy must both be (near-)integers, and
    4*correct - 4*negs must reproduce PPG*GP; otherwise None (caller keeps PPG only).
    """
    if None in (gp, buzzes, ppg, npg, acc) or not gp:
        return None
    if acc_pct:
        acc = acc / 100.0
    negs_f = abs(npg) * gp
    negs = round(negs_f)
    corr_f = buzzes * acc
    corr = round(corr_f)
    if abs(negs_f - negs) > 0.05 * max(1, gp) or abs(corr_f - corr) > 0.05 + 0.001 * buzzes:
        return None
    pts = 4 * corr - 4 * negs
    if abs(pts - ppg * gp) > 0.05 * gp + 0.02:
        return None
    zeros = buzzes - corr - negs
    if zeros < 0:
        return None
    return {"correct": corr, "negs": negs, "zeros": zeros, "points": pts}


def exact_points(ppg: float | None, gp: float | None) -> float | None:
    """points = PPG * GP when that is (near-)integral and a multiple of 2."""
    if ppg is None or not gp:
        return None
    p = ppg * gp
    if abs(p - round(p)) <= 0.02 * gp:
        return float(round(p))
    return None


def split_code_name(s: str) -> tuple[str, str]:
    """'K2 Michael W' -> ('K2', 'Michael W'); 'f3 aldric' -> ('F3', 'aldric'); else ('', s)."""
    t = clean_name(s)
    m = re.match(r"^([A-Za-z]\d{1,2})\s*[-:]?\s+(.+)$", t)
    if m:
        return m.group(1).upper(), m.group(2)
    return "", t


def bracket_team_name(s: str) -> tuple[str, str]:
    """'Kevin Q [AIOB]' -> ('Kevin Q', 'AIOB')."""
    t = clean_name(s)
    m = re.match(r"^(.*?)\s*\[(.+)\]\s*$", t)
    if m:
        return m.group(1), m.group(2)
    return t, ""
