"""Johns Hopkins Invitational 2025 (Stanford 2025 set).

results.xlsx tabs:
  * 'Field'                     code (A1..D6) -> full team name
  * 'RR Scoresheet'             four pool grids side by side; row label 'A1 <short name>',
                                columns A1..A6 = that team's score against each opponent
  * 'RR Pairings and Schedule'  per pool: ROOM | RR1..RR5 cells 'A1 — A2'
  * 'DE Bracket'                columns DE 1..DE 7 + FINALS (two score columns) of
                                ``short name | score`` cells

stats.xlsx only has TEAM subject PPG (RR and DE tabs), which has no slot in the canonical
schema, so it is used only for notes.
"""
from __future__ import annotations

import re

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import Grid, load_grids
from .g5_common import bracket_column_games

CODE_RX = re.compile(r"^([A-Z]\d+)\s+(.*)$")


def _scoresheet(g: Grid, w: TournamentWriter, full: dict[str, str], short: dict[str, str]):
    """Yield (code1, code2, s1, s2) for each pair in every pool block."""
    out = []
    for r in range(g.nrows):
        for c in range(g.ncols):
            m = re.match(r"^([A-Z])1$", g.text(r, c))
            if not m or g.text(r, c + 1) != f"{m.group(1)}2":
                continue
            letter = m.group(1)
            codes = []
            cc = c
            while re.match(rf"^{letter}\d+$", g.text(r, cc)):
                codes.append(g.text(r, cc))
                cc += 1
            rows = {}
            for rr in range(r + 1, r + 1 + len(codes)):
                mm = CODE_RX.match(g.text(rr, c - 1))
                if not mm:
                    raise ValueError(f"scoresheet row {rr}: {g.text(rr, c - 1)!r}")
                short[mm.group(2)] = full[mm.group(1)]
                rows[mm.group(1)] = rr
            for i, a in enumerate(codes):
                for j in range(i + 1, len(codes)):
                    b = codes[j]
                    s_ab = g.num(rows[a], c + j)
                    s_ba = g.num(rows[b], c + i)
                    if s_ab is None or s_ba is None:
                        w.warn(f"no score {a} vs {b}")
                        continue
                    out.append((a, b, s_ab, s_ba))
    return out


def _schedule(g: Grid) -> dict[frozenset, int]:
    out = {}
    for r in range(g.nrows):
        for c in range(g.ncols):
            m = re.match(r"^RR(\d+)$", g.text(r, c))
            if not m:
                continue
            rnd = int(m.group(1))
            rr = r + 1
            while rr < g.nrows and g.text(rr, c):
                pair = re.split(r"\s*[—–-]\s*", g.text(rr, c))
                if len(pair) == 2:
                    out[frozenset(pair)] = rnd
                rr += 1
    return out


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx") -> None:
    grids = load_grids(t.raw(results))
    f = grids["Field"]
    full = {f.text(r, 0): f.text(r, 1) for r in range(f.nrows)
            if re.match(r"^[A-Z]\d+$", f.text(r, 0))}
    for code, name in full.items():
        w.team(name, notes=f"code {code}")
    short: dict[str, str] = {}
    games = _scoresheet(grids["RR Scoresheet"], w, full, short)
    sched = _schedule(grids["RR Pairings and Schedule"])
    for a, b, sa, sb in games:
        rnd = sched.get(frozenset((a, b)))
        if rnd is None:
            w.warn(f"{a} vs {b} not in schedule")
        w.game(full[a], full[b], sa, sb, stage="rr", round=f"RR{rnd}" if rnd else "RR",
               seq=rnd or 0, notes=f"pool {a[0]}")

    def name_map(s: str) -> str:
        if s in short:
            return short[s]
        if s in full.values():
            return s
        raise ValueError(f"unknown bracket name {s!r}")

    rounds = bracket_column_games(grids["DE Bracket"], name_map=name_map)
    n = len(rounds)
    for k, pairs in rounds:
        for a, b in pairs:
            final = k == n
            w.game(a.name, b.name, a.scores[0], b.scores[0], stage="playoff",
                   round="Final" if final else f"DE{k}", seq=5 + k)
            if final and len(a.scores) > 1 and len(b.scores) > 1:
                w.game(a.name, b.name, a.scores[1], b.scores[1], stage="playoff",
                       round="Final 2", seq=5 + k + 1)
