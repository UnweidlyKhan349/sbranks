"""Shared helpers for the g6 results-only parsers (MIT, MOSFET, Collierville, Brooklyn Tech,
DAST, MNSBT).

Three building blocks:

* :class:`Roster` resolves the (often abbreviated) team names used in bracket tabs to the
  canonical names from the round-robin tabs: exact match, explicit alias, then a strict fuzzy
  rule (tokens in order as prefixes, numbers / single-letter suffixes must agree, acronyms).
  Anything ambiguous raises so a per-tournament alias has to be added.
* Round-robin grids: :func:`code_grid_blocks` (2/1/0 win-tie-loss codes, row team vs column
  opponent) and :func:`score_matrix_pairs` (row team's own score vs column opponent).
* Bracket tabs: :func:`bracket_games` reads visual bracket layouts. A bracket game is found
  from an *anchor* cell (a game label, room label or score cell). The two participants are the
  nearest name cells above and below the anchor in the participant column; scores come from
  the anchor text (``"72 - 56"``), from the cell right of each participant, or from the first
  score-like cell to the right of the anchor; the winner from the scores, from the first name
  to the right of the anchor, or from which participant shows up in a later column.
  Games that the layout cannot express (finals drawn as one box, labelled-slot brackets) are
  given explicitly as ``"ID | round | A1 | B1 | W | SA | SB"`` strings whose fields are cell
  references (``C7``) read from the sheet, or ``=Name`` literals for inferred values.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid

SCORE_RE = re.compile(r"^\s*(-?\d+(?:\.0)?)\s*[–—-]\s*(-?\d+(?:\.0)?)\s*$")
STOP = {"high", "school", "hs", "the", "of", "and", "sr", "senior", "jr"}


# ---------------------------------------------------------------------------------------
# cell references
def a1(ref: str) -> tuple[int, int]:
    """'C7' -> (6, 2) (0-based row, col)."""
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref.strip().upper())
    if not m:
        raise ValueError(f"bad cell ref {ref!r}")
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col - 1


def ref(r: int, c: int) -> str:
    s, c1 = "", c + 1
    while c1:
        c1, rem = divmod(c1 - 1, 26)
        s = chr(65 + rem) + s
    return f"{s}{r + 1}"


# ---------------------------------------------------------------------------------------
# team names
def norm(s: str) -> str:
    s = clean_name(s).lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in norm(s).split() if t not in STOP]


def _fits(raw: str, cand: str) -> bool:
    r, c = _tokens(raw), _tokens(cand)
    if not r or not c:
        return False
    # numbers and single-letter suffixes (A/B/C) must agree exactly
    key = lambda ts: sorted(t for t in ts if t.isdigit() or len(t) == 1)  # noqa: E731
    if key(r) != key(c):
        return False
    rw = [t for t in r if not (t.isdigit() or len(t) == 1)]
    cw = [t for t in c if not (t.isdigit() or len(t) == 1)]
    if not rw:
        return False
    # acronym: 'amsa' == initials of 'Advanced Math Science Academy',
    # 'asfa' == 'Alabama School of Fine Arts'
    if len(rw) == 1 and len(cw) > 1:
        full = [t for t in norm(cand).split() if t not in ("of", "and", "the", "for")
                and not (t.isdigit() or len(t) == 1)]
        if rw[0] in ("".join(t[0] for t in cw), "".join(t[0] for t in full)):
            return True
    i = 0
    for t in rw:
        while i < len(cw) and not cw[i].startswith(t):
            i += 1
        if i == len(cw):
            return False
        i += 1
    return True


class Roster:
    """Canonical team names + alias/fuzzy resolution."""

    def __init__(self, names: Iterable[str] = (), aliases: dict[str, str] | None = None):
        self.names: list[str] = []
        for n in names:
            self.add(n)
        self.aliases = {norm(k): clean_name(v) for k, v in (aliases or {}).items()}

    def add(self, name: str) -> str:
        n = clean_name(name)
        if n and n not in self.names:
            self.names.append(n)
        return n

    def resolve(self, raw: Any) -> str:
        s = clean_name(raw)
        if s in self.names:
            return s
        k = norm(s)
        if k in self.aliases:
            return self.aliases[k]
        exact = [n for n in self.names if norm(n) == k]
        if len(exact) == 1:
            return exact[0]
        fit = [n for n in self.names if _fits(s, n)]
        if len(fit) == 1:
            return fit[0]
        raise KeyError(f"cannot resolve team {s!r} (candidates: {fit or 'none'})")


# ---------------------------------------------------------------------------------------
# round robin: win/tie/loss code grids (2 = row team won, 1 = tie, 0 = row team lost)
@dataclass
class CodeBlock:
    title: str
    teams: list[str]                       # in row order
    codes: dict[tuple[int, int], str]      # (row idx, col idx) -> raw cell text


def code_grid_blocks(g: Grid, header_re: str = r"^(Team Name|SCHOOL)$") -> list[CodeBlock]:
    """Find every 'Team Name' / 'SCHOOL' header row and read the block below it.

    Two layouts: ``ID | Team Name | A1 A2 ... | Total`` (ids in the column left of the
    name) and ``SCHOOL | TEAM ID | vs. 1 vs. 2 ... | TOTAL`` (``vs. k`` = the team whose id
    ends in k).
    """
    blocks = []
    for hr, hc in g.find(header_re):
        school_layout = g.text(hr, hc).upper() == "SCHOOL"
        ncol, idcol = (hc, hc + 1) if school_layout else (hc, hc - 1)
        first_opp = ncol + 2 if school_layout else ncol + 1
        title = ""
        for r in range(hr - 1, max(hr - 4, -1), -1):
            t0 = g.text(r, 0)
            if t0 and not re.match(r"^(Note|Scroll)", t0) and t0 != "Opponent":
                title = t0
                break
        opp_cols: dict[str, int] = {}
        for c in range(first_opp, g.ncols):
            h = g.text(hr, c)
            m = re.match(r"^vs\.?\s*(\d+)$", h, re.I) if school_layout else re.match(r"^([A-Z]?\d+)(?:\.0)?$", h)
            if not m:
                break
            opp_cols[m.group(1)] = c
        rows = []
        r = hr + 1
        while r < g.nrows and g.text(r, ncol):
            rows.append(r)
            r += 1
        teams, ids = [], []
        for r in rows:
            tid = g.text(r, idcol)
            ids.append(re.sub(r"^[A-Za-z]+", "", tid) if school_layout else _idkey(tid))
            teams.append(g.text(r, ncol))
        codes = {}
        for i, r in enumerate(rows):
            for j, key in enumerate(ids):
                if i == j or key not in opp_cols:
                    continue
                v = g.text(r, opp_cols[key])
                if v:
                    codes[(i, j)] = v
        blocks.append(CodeBlock(title, teams, codes))
    return blocks


def _idkey(s: str) -> str:
    s = clean_name(s)
    m = re.match(r"^(\d+)\.0$", s)
    return m.group(1) if m else s


def code_pairs(block: CodeBlock, w: TournamentWriter | None = None):
    """Yield (i, j, result, forfeit, note) for each played pair (i < j) of a code block.

    result is '1' (team i won), '2' (team j won) or 'T'. Codes with a '*' are reported with
    forfeit=True (the MIT sheets use it for an adjudicated / forfeited game).
    """
    n = len(block.teams)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = block.codes.get((i, j)), block.codes.get((j, i))
            if a is None and b is None:
                continue
            star = "*" in (a or "") or "*" in (b or "")
            va = num((a or "").replace("*", ""))
            vb = num((b or "").replace("*", ""))
            note = ""
            if va is None or vb is None:
                note = "only one side of the grid filled"
                if w:
                    w.warn(f"{block.title}: {block.teams[i]} vs {block.teams[j]}: one-sided cell ({a!r}/{b!r})")
                va = 2 - vb if va is None else va
                vb = 2 - va if vb is None else vb
            if va + vb != 2:
                if w:
                    w.warn(f"{block.title}: {block.teams[i]} vs {block.teams[j]}: inconsistent codes {a!r}/{b!r}; skipped")
                continue
            res = "1" if va == 2 else "2" if vb == 2 else "T"
            yield i, j, res, star, ("marked * in source" if star else note)


# ---------------------------------------------------------------------------------------
# round robin: score matrices (row team's own points vs the column opponent)
def score_matrix_pairs(teams: list[str], cell, w: TournamentWriter | None = None, title: str = ""):
    """``cell(i, j)`` returns the raw value of row team i vs column team j.

    Yields (i, j, score_i, score_j) for i < j where both values are numeric. One-sided
    pairs are reported as parser warnings.
    """
    n = len(teams)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = num(cell(i, j)), num(cell(j, i))
            if a is None and b is None:
                continue
            if a is None or b is None:
                if w:
                    w.warn(f"{title}: {teams[i]} vs {teams[j]}: only one score ({cell(i, j)!r}/{cell(j, i)!r}); skipped")
                continue
            yield i, j, a, b


# ---------------------------------------------------------------------------------------
# brackets
@dataclass
class BGame:
    gid: str
    round: str
    seq: int
    t1: str
    t2: str
    s1: float | None = None
    s2: float | None = None
    winner: str | None = None       # canonical name
    forfeit: bool = False
    note: str = ""
    where: str = ""

    @property
    def loser(self) -> str | None:
        if self.winner is None:
            return None
        return self.t2 if self.winner == self.t1 else self.t1


@dataclass
class BracketSpec:
    tab: str
    anchor: str | None = None                # regex for anchor cells
    gid_re: str | None = None                # regex group(1) of anchor text = game id
    pcols: list[int] = field(default_factory=lambda: [0])   # participant column offsets
    skip: list[str] = field(default_factory=list)            # non-name cells
    strip: list[str] = field(default_factory=list)           # regexes removed from names
    bye: str = r"^(BYE|N/?A|--|TBD)$"
    score: str = "none"                       # none | anchor | right | row
    winner: str = "right"                     # right | later | none
    winner_high: bool = False                 # scores unordered: winner gets the larger one
    header_row: int = 0
    header_skip: str = r"^(Lunch|Break|Time|Round)$|\d:\d\d|^\d+(\.0)?$"
    round_num: str | None = None              # regex: header -> number for seq
    round_fmt: str | None = None              # e.g. 'DE{n}' (with round_num) or '{h}'
    seq_base: int = 10
    extra_rounds: dict[str, int] = field(default_factory=dict)
    round_overrides: dict[str, str] = field(default_factory=dict)  # anchor A1 -> round label
    ignore: list[str] = field(default_factory=list)                # game ids to skip
    winner_cells: dict[str, str] = field(default_factory=dict)     # gid -> A1 / =Name
    games: list[str] = field(default_factory=list)                 # explicit games
    stage: str = "playoff"
    max_gap: int = 40

    @classmethod
    def from_opts(cls, d: dict[str, Any]) -> "BracketSpec":
        return cls(**d)


class BracketReader:
    def __init__(self, g: Grid, spec: BracketSpec, roster: Roster, w: TournamentWriter):
        self.g, self.s, self.roster, self.w = g, spec, roster, w
        self.anchor_rx = re.compile(spec.anchor) if spec.anchor else None
        self.skip_rx = [re.compile(p, re.I) for p in spec.skip]
        self.bye_rx = re.compile(spec.bye, re.I)
        self.rounds = self._rounds()

    # -- headers / rounds ---------------------------------------------------------------
    def _rounds(self) -> list[tuple[int, str, int]]:
        out: list[tuple[int, str, int]] = []
        if self.s.header_row < 0:
            return out
        hdr_skip = re.compile(self.s.header_skip, re.I)
        for c in range(self.g.ncols):
            h = self.g.text(self.s.header_row, c)
            if not h or hdr_skip.search(h):
                continue
            if self.s.round_num:
                m = re.search(self.s.round_num, h, re.I)
                if not m:
                    continue
                n = int(m.group(1))
                seq = self.s.seq_base + n
            else:
                n = len(out) + 1
                seq = self.s.seq_base + n
            label = self.s.round_fmt.format(n=n, h=h) if self.s.round_fmt else h
            out.append((c, label, seq))
        return out

    def round_at(self, c: int) -> tuple[str, int]:
        best = None
        for col, label, seq in self.rounds:
            if col <= c:
                best = (label, seq)
        if best is None:  # anchor left of the first header (e.g. room labels in column A)
            if not self.rounds:
                raise ValueError(f"{self.s.tab}: no round headers")
            best = (self.rounds[0][1], self.rounds[0][2])
        return best

    def seq_for(self, label: str) -> int:
        if label in self.s.extra_rounds:
            return self.s.extra_rounds[label]
        for _, lab, seq in self.rounds:
            if lab == label:
                return seq
        raise ValueError(f"{self.s.tab}: unknown round {label!r}")

    # -- cells --------------------------------------------------------------------------
    def clean(self, v: Any) -> str:
        s = clean_name(v)
        for p in self.s.strip:
            s = re.sub(p, "", s, flags=re.I).strip()
        return s

    def is_anchor(self, r: int, c: int) -> bool:
        return bool(self.anchor_rx and self.anchor_rx.search(self.g.text(r, c)))

    def is_skip(self, s: str) -> bool:
        return any(p.search(s) for p in self.skip_rx)

    def is_name(self, r: int, c: int) -> bool:
        s = self.g.text(r, c)
        if not s or self.is_anchor(r, c) or self.is_skip(s) or SCORE_RE.match(s):
            return False
        if num(s) is not None:
            return False
        return True

    def nearest(self, r: int, c: int, step: int) -> int | None:
        rr = r + step
        while 0 <= rr < self.g.nrows and abs(rr - r) <= self.s.max_gap:
            if self.is_anchor(rr, c):
                return None
            if self.is_name(rr, c):
                return rr
            rr += step
        return None

    def name_at(self, r: int, c: int) -> str | None:
        """Canonical team at a cell, or None for a bye."""
        s = self.clean(self.g.cell(r, c))
        if self.bye_rx.search(s):
            return None
        return self.roster.resolve(s)

    def lit(self, token: str) -> str | None:
        token = token.strip()
        if token.startswith("="):
            return self.roster.resolve(token[1:])
        r, c = a1(token)
        return self.name_at(r, c)

    # -- reading ------------------------------------------------------------------------
    def read(self) -> list[BGame]:
        games: list[BGame] = []
        if self.anchor_rx:
            for r in range(self.g.nrows):
                for c in range(self.g.ncols):
                    if self.is_anchor(r, c):
                        gm = self._anchor_game(r, c)
                        if gm:
                            games.append(gm)
        for spec in self.s.games:
            games.append(self._explicit(spec))
        return games

    def _gid(self, r: int, c: int) -> str:
        txt = self.g.text(r, c)
        if self.s.gid_re:
            m = re.search(self.s.gid_re, txt)
            if m:
                return m.group(1)
        return ref(r, c)

    def _anchor_game(self, r: int, c: int) -> BGame | None:
        gid = self._gid(r, c)
        if gid in self.s.ignore:
            return None
        where = f"{self.s.tab}!{ref(r, c)}"
        rows = None
        for off in self.s.pcols:
            up, dn = self.nearest(r, c + off, -1), self.nearest(r, c + off, +1)
            if up is not None and dn is not None:
                rows = (up, dn, c + off)
                break
        if rows is None:
            raise ValueError(f"{where} ({self.g.text(r, c)!r}): participants not found")
        up, dn, pc = rows
        t1, t2 = self.name_at(up, pc), self.name_at(dn, pc)
        if t1 is None or t2 is None:
            return None  # bye
        if ref(r, c) in self.s.round_overrides:
            label = self.s.round_overrides[ref(r, c)]
            seq = self.seq_for(label)
        else:
            label, seq = self.round_at(c)
        gm = BGame(gid, label, seq, t1, t2, where=where)
        # scores
        raw1 = raw2 = None
        if self.s.score == "anchor":
            m = SCORE_RE.match(self.g.text(r, c))
            raw1, raw2 = (m.group(1), m.group(2)) if m else (None, None)
        elif self.s.score == "right":
            raw1, raw2 = self.g.text(up, pc + 1), self.g.text(dn, pc + 1)
        elif self.s.score == "row":
            for cc in range(c + 1, self.g.ncols):
                m = SCORE_RE.match(self.g.text(r, cc))
                if m:
                    raw1, raw2 = m.group(1), m.group(2)
                    break
                if self.is_name(r, cc) and not self.bye_rx.search(self.g.text(r, cc)):
                    break
        gm.s1, gm.s2 = num(raw1), num(raw2)
        if gm.s1 is None or gm.s2 is None:
            if any(re.search(r"^(FRFT|forfeit|FF)$", x or "", re.I) for x in (raw1, raw2)):
                gm.forfeit = True
                gm.note = f"forfeit ({raw1 or '-'} / {raw2 or '-'})"
            gm.s1 = gm.s2 = None
        # winner
        wtxt = None
        if gid in self.s.winner_cells:
            gm.winner = self.lit(self.s.winner_cells[gid])
        elif self.s.winner == "right":
            # first column right of the anchor holding a name within the participants' row
            # span; the one nearest the anchor row is the advancing team
            for cc in range(c + 1, self.g.ncols):
                if self.is_anchor(r, cc):
                    break
                cands = sorted((abs(rr - r), rr) for rr in range(up, dn + 1)
                               if self.is_name(rr, cc) and not self.bye_rx.search(self.g.text(rr, cc)))
                if cands:
                    rr = cands[0][1]
                    wtxt = self.g.text(rr, cc)
                    gm.winner = self.name_at(rr, cc)
                    break
        elif self.s.winner == "later":
            gm.winner = self._later(pc, {t1, t2}, where)
        self._finish(gm, wtxt)
        return gm

    def _later(self, col: int, cands: set[str], where: str) -> str | None:
        seen = set()
        for rr in range(self.g.nrows):
            for cc in range(col + 1, self.g.ncols):
                if not self.is_name(rr, cc):
                    continue
                try:
                    n = self.name_at(rr, cc)
                except KeyError:
                    continue
                if n in cands:
                    seen.add(n)
        return seen.pop() if len(seen) == 1 else None

    def _explicit(self, spec: str) -> BGame:
        parts = [p.strip() for p in spec.split("|")]
        parts += [""] * (7 - len(parts))
        gid, label, ta, tb, tw, sa, sb = parts[:7]
        t1, t2 = self.lit(ta), self.lit(tb)
        if t1 is None or t2 is None:
            raise ValueError(f"{self.s.tab} explicit game {gid}: bye participant")
        gm = BGame(gid, label, self.seq_for(label), t1, t2, where=f"{self.s.tab}!{ta},{tb}")
        if sa and sb:
            gm.s1 = num(self.g.cell(*a1(sa))) if not sa.startswith("=") else num(sa[1:])
            gm.s2 = num(self.g.cell(*a1(sb))) if not sb.startswith("=") else num(sb[1:])
        if tw:
            gm.winner = self.lit(tw)
            if tw.startswith("="):
                gm.note = "winner inferred from the bracket (not shown in the source)"
        self._finish(gm, None)
        return gm

    def _finish(self, gm: BGame, wtxt: str | None) -> None:
        has_scores = gm.s1 is not None and gm.s2 is not None
        if gm.winner is not None and gm.winner not in (gm.t1, gm.t2):
            raise ValueError(f"{gm.where} {gm.gid}: winner {gm.winner!r} not in {gm.t1!r} / {gm.t2!r}")
        if has_scores:
            if gm.s1 == gm.s2:
                raise ValueError(f"{gm.where} {gm.gid}: tied bracket score {gm.s1}")
            by_score = gm.t1 if gm.s1 > gm.s2 else gm.t2
            if gm.winner is not None and gm.winner != by_score:
                if self.s.winner_high:
                    if gm.winner == gm.t1:
                        gm.s1, gm.s2 = max(gm.s1, gm.s2), min(gm.s1, gm.s2)
                    else:
                        gm.s1, gm.s2 = min(gm.s1, gm.s2), max(gm.s1, gm.s2)
                else:
                    raise ValueError(f"{gm.where} {gm.gid}: winner {gm.winner} disagrees with score {gm.s1}-{gm.s2}")
            gm.winner = gm.winner or by_score
        if gm.winner is None:
            raise ValueError(f"{gm.where} {gm.gid}: no winner for {gm.t1} vs {gm.t2}")


def bracket_games(g: Grid, spec: BracketSpec, roster: Roster, w: TournamentWriter) -> list[BGame]:
    return BracketReader(g, spec, roster, w).read()


def emit_games(w: TournamentWriter, games: list[BGame], stage: str = "playoff",
               prefix: str = "") -> None:
    """Write bracket games; the bracket's own game label is used as game_id when unique."""
    used = {g["game_id"] for g in w.rows["games"]}
    for gm in sorted(games, key=lambda x: (x.seq, x.where)):
        res = "" if (gm.s1 is not None and gm.s2 is not None) else ("1" if gm.winner == gm.t1 else "2")
        gid = f"{prefix}{gm.gid}"
        if re.fullmatch(r"[A-Z]+\d+", gm.gid) and gm.where.endswith(gm.gid):
            gid = f"{prefix or 'de-'}{gm.gid}"   # anchor cell ref: keep it but mark as bracket
        if gid in used:
            gid = None
        else:
            used.add(gid)
        w.game(gm.t1, gm.t2, gm.s1, gm.s2, stage=stage, round=gm.round, seq=gm.seq,
               result=res, forfeit=gm.forfeit, notes=gm.note, game_id=gid)


def elimination_summary(games: list[BGame]) -> dict[str, Any]:
    """Losses per team and the winner of the last game (for DE sanity checks)."""
    losses: Counter[str] = Counter()
    played: Counter[str] = Counter()
    for gm in games:
        losses[gm.loser] += 1
        played[gm.t1] += 1
        played[gm.t2] += 1
    last = max(games, key=lambda x: x.seq) if games else None
    return {"losses": dict(losses), "played": dict(played),
            "champion": last.winner if last else None}


def check_labels(games: list[BGame], g: Grid, roster: Roster, w: TournamentWriter,
                 pattern: str = r"^(Winner|Loser|Lower|One-loss)( of)? ([A-Z]+\d+):\s*(.+?)!?$") -> int:
    """Cross-check 'Winner of W5: X' / 'Loser W30: Y' labels against the reconstructed games."""
    by_id = {gm.gid: gm for gm in games}
    bad = 0
    rx = re.compile(pattern)
    for r in range(g.nrows):
        for c in range(g.ncols):
            m = rx.match(g.text(r, c))
            if not m:
                continue
            kind, gid, name = m.group(1), m.group(3), m.group(4)
            gm = by_id.get(gid)
            if gm is None:
                continue
            try:
                team = roster.resolve(name)
            except KeyError:
                continue
            exp = gm.winner if kind == "Winner" else gm.loser
            if team != exp:
                bad += 1
                w.warn(f"label {g.title}!{ref(r, c)} says {kind} {gid} = {team}, reconstructed {exp}")
    return bad


def de_warnings(w: TournamentWriter, games: list[BGame], max_losses: int = 2) -> None:
    summ = elimination_summary(games)
    for team, n in summ["losses"].items():
        if n > max_losses:
            w.warn(f"bracket: {team} has {n} losses")
