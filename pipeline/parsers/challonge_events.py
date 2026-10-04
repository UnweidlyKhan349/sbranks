"""Events whose results exist only as a Challonge bracket (DAST 2021, SSBT 2022, NSBA 3 2025).

The bracket comes from Challonge's embed page (``https://challonge.com/<id>/module``), which
carries the TournamentStore JSON; see ``g3_online._challonge_store``. Optional player stats
come from a stats workbook with ``Player | Discord Username | Team | TU Heard | 4s | 0s | -4s |
PPG`` tabs per subject (SSBT 2022).

``zero_zero``: how to read a completed match whose score is 0-0 — ``result`` (score simply not
entered; keep the winner) or ``forfeit``.
"""
from __future__ import annotations

import difflib
from collections import defaultdict
from typing import Any

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import load_grids
from .g3_online import _challonge_store


def parse(t: Tournament, w: TournamentWriter, file: str = "challonge_module.html", zero_zero: str = "result",
          rename: dict[str, str] | None = None, stats: str | None = None,
          stats_scope: str = "all") -> None:
    rename = rename or {}
    d = _challonge_store(t.raw(file))
    mbr = d["matches_by_round"]
    matches = [m for ms in mbr.values() for m in ms if m.get("state") == "complete"]
    wmax = max(int(k) for k in mbr if int(k) > 0)
    has_losers = any(int(k) < 0 for k in mbr)

    def name(p: dict[str, Any]) -> str:
        n = clean_name(p["display_name"])
        return rename.get(n, n)

    def order(m: dict[str, Any]) -> tuple[int, int]:
        r = m["round"]
        if has_losers and r == wmax:
            return (2, 0)
        return (0, r) if r > 0 else (1, -r)

    # play order: a game comes after both teams' previous games
    by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for m in matches:
        for pk in ("player1", "player2"):
            by_team[m[pk]["id"]].append(m)
    for ms in by_team.values():
        ms.sort(key=order)
    seq: dict[int, int] = {}

    def seq_of(m: dict[str, Any]) -> int:
        if m["id"] not in seq:
            s = 1
            for pk in ("player1", "player2"):
                ms = by_team[m[pk]["id"]]
                i = ms.index(m)
                if i > 0:
                    s = max(s, seq_of(ms[i - 1]) + 1)
            seq[m["id"]] = s
        return seq[m["id"]]

    for m in sorted(matches, key=lambda m: (seq_of(m), order(m), m["identifier"])):
        a, b = name(m["player1"]), name(m["player2"])
        r = m["round"]
        label = "Grand Final" if has_losers and r == wmax else (f"L{-r}" if r < 0 else f"W{r}")
        res = "1" if m["winner_id"] == m["player1"]["id"] else "2"
        sc = m.get("scores") or []
        note = f"Challonge match {m['identifier']}"
        if len(sc) != 2 or (sc[0] == 0 and sc[1] == 0) or m.get("forfeited"):
            ff = bool(m.get("forfeited")) or (zero_zero == "forfeit" and sc == [0, 0])
            w.game(a, b, stage="playoff", round=label, seq=10 + seq_of(m), result=res, forfeit=ff,
                   notes=note + ("; forfeit" if ff else "; no score entered"))
            continue
        s1, s2 = sc
        exp = "1" if s1 > s2 else "2" if s2 > s1 else "T"
        if exp != res:
            w.warn(f"{label}: {a} vs {b}: score {s1}-{s2} but winner {a if res == '1' else b}")
            w.game(a, b, stage="playoff", round=label, seq=10 + seq_of(m), result=res,
                   notes=f"{note}; source score {s1}-{s2}, winner by tiebreak")
        else:
            w.game(a, b, s1, s2, stage="playoff", round=label, seq=10 + seq_of(m), notes=note)

    if stats:
        _stats(t, w, stats, stats_scope)


def _stats(t: Tournament, w: TournamentWriter, file: str, scope: str) -> None:
    grids = load_grids(t.raw(file))
    real = {}
    if "Discord Username to Real Name" in grids:
        g = grids["Discord Username to Real Name"]
        for r in range(1, g.nrows):
            if g.text(r, 3):
                real[g.text(r, 3)] = g.text(r, 0)
    teams = list(w._teams)  # bracket team names
    warned: set[str] = set()

    def team_name(s: str) -> str:
        if s in teams:
            return s
        m = difflib.get_close_matches(s, teams, n=1, cutoff=0.75)
        if m:
            return m[0]
        if s not in warned:
            warned.add(s)
            w.warn(f"stats team {s!r} not in bracket; kept as its own team")
        return s

    tabs = {"overall": "Player Overall Stats"}
    for title in grids:
        if title.endswith("Unsorted") or title in tabs.values():
            continue
        s = normalize_subject(title)
        if s and s != "overall":
            tabs[s] = title
    for subj, title in tabs.items():
        g = grids[title]
        hdr = [h.lower() for h in g.row_texts(0)]
        col = {k: hdr.index(k) for k in ("player", "discord username", "team", "tu heard", "4s", "0s", "-4s", "ppg") if k in hdr}
        for r in range(1, g.nrows):
            player = g.text(r, col["player"])
            team = g.text(r, col["team"])
            if not player or not team:
                continue
            handle = g.text(r, col["discord username"]) if "discord username" in col else ""
            player = real.get(handle, player)
            c, z, n = (g.num(r, col[k]) for k in ("4s", "0s", "-4s"))
            ppg = g.num(r, col["ppg"])
            pts = None if c is None or n is None else 4 * c - 4 * n
            gp = round(pts / ppg) if pts and ppg else None
            w.player_stat(player, team_name(team), subj, scope=scope, gp=gp if subj == "overall" else None,
                          tuh=g.num(r, col["tu heard"]), correct=c, zeros=z, negs=n, points=pts,
                          ppg=None if pts is not None else ppg)
