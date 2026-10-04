"""LOST 2021 / SBST 2021 results template (same organisers, same workbook layout).

* ``MORNING RR`` / ``RR``: one block per division ("Division Bowman"); per team and round
  (RR1..RR5) a result (W/T/L, or 2/1/0 points) and the team's own score. Opponents are not
  given here.
* ``ROOM ASSIGNMENTS``: per room row ("(1,1) Bowman Room 1") and match k the two teams in
  that room; match k = RR round k. Rows after "Teams on bye" are ignored. (SBST 2021's
  cross-division "Eden" rooms were optional bye games and have no recorded results.)
* ``DE SCHEDULE``: hand-drawn double elimination; a room/game label ("Commons I, R3",
  "Rhydon 1") sits between the two entrants, each entrant's score is right of its name.

RR games = room pairings joined with both teams' (result, score) entries. A team whose
every entry is a 0-point loss is treated as a no-show (its games are forfeits).
"""
from __future__ import annotations

import re
from typing import Any

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import load_grids
from .g3_online import _emit_scored, label_bracket

_RESULT = {"W": "W", "L": "L", "T": "T", "2": "W", "1": "T", "0": "L"}


def _result(v: Any) -> str:
    s = clean_name(v).upper()
    n = num(v)
    if n is not None:
        s = str(int(n))
    return _RESULT.get(s, "")


def parse(t: Tournament, w: TournamentWriter, *, rr_tab: str, de_tab: str = "DE SCHEDULE",
          rooms_tab: str = "ROOM ASSIGNMENTS", de_label: str = r",\s*R(\d+|\.[A-Z])",
          rr_aliases: dict[str, str] | None = None, de_aliases: dict[str, str] | None = None,
          file: str = "results.xlsx") -> None:
    grids = load_grids(t.raw(file))
    g = grids[rr_tab]
    hr = next(r for r, _ in g.find(r"^RR1\b"))
    rcols = [c for c in range(g.ncols) if re.match(r"^RR\d", g.text(hr, c))]
    divisions: dict[str, str] = {}
    entries: dict[int, dict[str, tuple[str, float | None]]] = {k: {} for k in range(1, len(rcols) + 1)}
    div = ""
    for r in range(hr + 2, g.nrows):
        s = g.text(r, 0)
        if not s:
            continue
        if s.lower().startswith(("division ", "dvision ", "divsion ", "divison ")):
            div = clean_name(s.split(None, 1)[1]) if " " in s else s
            continue
        divisions[s] = div
        w.team(s, notes=f"Division {div}")
        for k, c in enumerate(rcols, 1):
            res = _result(g.cell(r, c))
            if res:
                entries[k][s] = (res, g.num(r, c + 1))
    teams = set(divisions)
    no_show = {tm for tm in teams
               if all(e[0] == "L" and not e[1] for k in entries for x, e in entries[k].items() if x == tm)
               and any(tm in entries[k] for k in entries)}
    if no_show:
        w.warn(f"no-show teams (every entry a 0-point loss): {sorted(no_show)}")

    lower = {tm.lower(): tm for tm in teams}

    def resolve(name: str, aliases: dict[str, str]) -> str | None:
        name = clean_name(name)
        name = aliases.get(name, name)
        return name if name in teams else lower.get(name.lower())

    rr_aliases = rr_aliases or {}
    rg = grids[rooms_tab]
    mrow = next(r for r, _ in rg.find(r"^Match 1$"))
    mcols: dict[int, list[int]] = {}
    for c in range(rg.ncols):
        m = re.match(r"^Match (\d+)$", rg.text(mrow, c))
        if m:
            mcols.setdefault(int(m.group(1)), []).append(c)
    skipped = 0
    for r in range(mrow + 1, rg.nrows):
        room = rg.text(r, 0)
        if not room:
            continue
        if not re.match(r"^\(\d+,\s*\d+\)", room):  # "(1,2) Bowman Room 2"; stop at bye list
            break
        for k, (ca, cb) in sorted(mcols.items()):
            na, nb = rg.text(r, ca), rg.text(r, cb)
            if not na or not nb:
                continue
            a, b = resolve(na, rr_aliases), resolve(nb, rr_aliases)
            if not a or not b:
                w.warn(f"rooms: unknown team {na if not a else nb!r} ({room}, match {k})")
                continue
            _rr_game(w, k, room, a, b, entries[k].get(a), entries[k].get(b), no_show, divisions)
            if a not in entries[k] and b not in entries[k]:
                skipped += 1
    if skipped:
        w.warn(f"{skipped} scheduled RR pairings have no result for either team (not played / not recorded)")

    # double elimination
    if de_tab not in grids:
        return
    de = grids[de_tab]
    de_aliases = de_aliases or {}
    n_rr = len(rcols)
    last = max((c for c in range(de.ncols) if de.text(0, c)), default=0)
    for gm in sorted(label_bracket(de, de_label, result_words={"win": "W", "loss": "L"}),
                     key=lambda x: (x["col"], x["row"])):
        (na, sa), (nb, sb) = gm["a"], gm["b"]
        a, b = resolve(na, de_aliases), resolve(nb, de_aliases)
        if not a or not b:
            w.warn(f"DE: unknown team {na if not a else nb!r} at {gm['label']}")
            continue
        k = gm["col"] // 2 + 1
        rnd = "DE Final" if gm["col"] == last and "FINAL" in de.text(0, last).upper() else f"DE R{k}"
        note = gm["label"]
        if isinstance(sa, str) or isinstance(sb, str):
            res = "1" if sa == "W" or sb == "L" else "2"
            w.game(a, b, stage="playoff", round=rnd, seq=n_rr + k, result=res,
                   notes=f"{note}; win/loss only")
        else:
            w.game(a, b, sa, sb, stage="playoff", round=rnd, seq=n_rr + k, notes=note)


def _rr_game(w: TournamentWriter, k: int, room: str, a: str, b: str,
             ea: tuple[str, float | None] | None, eb: tuple[str, float | None] | None,
             no_show: set[str], divisions: dict[str, str]) -> None:
    note = f"{room}"
    if a in no_show or b in no_show:
        if a in no_show and b in no_show:
            return
        winner = b if a in no_show else a
        w.game(a, b, stage="rr", round=k, seq=k, result="1" if winner == a else "2",
               forfeit=True, notes=f"{note}; forfeit ({a if a in no_show else b} did not play)")
        return
    if ea is None and eb is None:
        return
    if ea is None or eb is None:
        (have, e) = (a, ea) if ea else (b, eb)
        if e[0] == "T":
            w.warn(f"RR{k} {a} vs {b}: only {have}'s tie recorded; skipped")
            return
        won = have if e[0] == "W" else (b if have == a else a)
        w.warn(f"RR{k} {a} vs {b}: only {have}'s result recorded; kept result without scores")
        w.game(a, b, stage="rr", round=k, seq=k, result="1" if won == a else "2",
               notes=f"{note}; only {have}'s result in source")
        return
    (ra, sa), (rb, sb) = ea, eb
    if not ({ra, rb} == {"W", "L"} or ra == rb == "T"):
        w.warn(f"RR{k} {a} ({ra} {sa}) vs {b} ({rb} {sb}): results disagree; skipped")
        return
    winner = None if ra == "T" else (a if ra == "W" else b)
    if winner is None:
        if sa != sb:
            w.warn(f"RR{k} {a} vs {b}: tie with scores {sa}-{sb}; kept as tie without scores")
            w.game(a, b, stage="rr", round=k, seq=k, result="T", notes=f"{note}; source scores {sa}-{sb}")
            return
        w.game(a, b, sa, sb, stage="rr", round=k, seq=k, notes=note)
        return
    _emit_scored(w, a, sa, b, sb, stage="rr", rnd=k, seq=k, winner=winner, notes=note)
