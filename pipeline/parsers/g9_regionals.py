"""DOE National Science Bowl high-school regionals with published game results.

Connecticut (UConn / Vergnano Institute): the organizers' scoring workbook.
    results.xlsx   master sheet; tab ``rr_tab`` holds the round robin: per division, rows of
                   room name + team (col A = room) and the opponent on the next row, with
                   (team, score, verification, points) blocks for rounds 1-5
    de.xlsx        published championship sheet; tab ``de_tab`` lists each double-elimination
                   round as a (team, score, ...) column block, opponents in consecutive rows
                   (rows 5/6, 7/8, ...); team names carry the seed ("4 Greenwich HS - Team 1")
"""
from __future__ import annotations

import re
from typing import Any

import openpyxl

from ..registry import Tournament
from ..schema import TournamentWriter

_ROOM = re.compile(r"^[A-Z]{2,5}\s*\d{2,4}$")
_SEED = re.compile(r"^\d+\s+")


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _ct_name(name: Any) -> str:
    """'Farmington HS - Team 1' -> 'Farmington HS 1' (the letter is taken from the number)."""
    return re.sub(r"\s*-\s*Team\s+(\d+)$", r" \1", _SEED.sub("", str(name).strip()))


def _skip(name: Any) -> bool:
    s = str(name or "").strip()
    return not s or s.upper() == "BYE" or s.lower().startswith("open spot")


def parse_ct(t: Tournament, w: TournamentWriter, rr_file: str = "results.xlsx",
             rr_tab: str = "CT Region ROUND ROBIN Scores (P", de_file: str = "de.xlsx",
             de_tab: str = "CT Championship Scores (Public)", rr_rounds: int = 5,
             canceled: list[str] | None = None) -> None:
    canceled = canceled or []
    ws = openpyxl.load_workbook(t.raw(rr_file), data_only=True)[rr_tab]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    division = ""
    for i, row in enumerate(rows):
        a = str(row[0] or "").strip()
        if a.startswith("Division"):
            division = a
            continue
        if not _ROOM.match(a) or i + 1 >= len(rows) or any(c in division for c in canceled):
            continue
        nxt = rows[i + 1]
        for k in range(rr_rounds):
            c = 1 + 4 * k  # team column of round k+1 (B, F, J, N, R)
            t1, t2 = row[c], nxt[c]
            if _skip(t1) or _skip(t2):
                continue
            s1, s2 = _num(row[c + 1]), _num(nxt[c + 1])
            p1, p2 = _num(row[c + 3]), _num(nxt[c + 3])
            result = ""
            if s1 is not None and s2 is not None and s1 == s2 and p1 is not None and p2 is not None and p1 != p2:
                result = "1" if p1 > p2 else "2"  # tie on points broken by the published match points
            w.game(_ct_name(t1), _ct_name(t2), s1, s2, stage="rr", round=f"Round {k + 1}", seq=k + 1,
                   result=result, notes=f"{division}, {a}")

    ws = openpyxl.load_workbook(t.raw(de_file), data_only=True)[de_tab]
    grid = [list(r) for r in ws.iter_rows(values_only=True)]
    hdr = grid[1]
    blocks = [(j, str(v).strip()) for j, v in enumerate(hdr) if v and "Round" in str(v)]
    for n, (j, title) in enumerate(blocks):
        rd = re.sub(r"^CT\s+", "", title)
        rd = re.sub(r"\s*\((FINAL MATCH|needed)\)", "", rd).strip()
        for r in range(4, len(grid) - 1, 2):
            t1, t2 = grid[r][j], grid[r + 1][j]
            if _skip(t1) or _skip(t2):
                continue
            s1, s2 = _num(grid[r][j + 1]), _num(grid[r + 1][j + 1])
            if s1 is None or s2 is None:
                continue
            w.game(_ct_name(t1), _ct_name(t2), s1, s2, stage="playoff",
                   round=rd, seq=rr_rounds + 1 + n)


def parse_wl_grid(t: Tournament, w: TournamentWriter, file: str = "results.xlsx", rr_tab: str = "Round Robin",
                  de_games: list[list[str]] | None = None) -> None:
    """Round robin published as group cross-tables of match points only (2 = win, 1 = tie,
    0 = loss for the row team), no scores; the bracket comes in as ``de_games``:
    [round, team1, team2, winner] rows transcribed from the bracket tab."""
    ws = openpyxl.load_workbook(t.raw(file), data_only=True)[rr_tab]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    group, teams, seen = "", {}, set()

    def flush() -> None:
        for code, (name, row) in teams.items():
            for j, (ocode, (oname, _)) in enumerate(teams.items()):
                pts = _num(row[2 + j]) if 2 + j < len(row) else None
                key = frozenset((code, ocode))
                if ocode == code or pts is None or key in seen:
                    continue
                seen.add(key)
                res = {2.0: "1", 0.0: "2", 1.0: "T"}.get(pts)
                if res is None:
                    w.warn(f"{group}: {name} vs {oname} has match points {pts}")
                    continue
                w.game(name, oname, stage="rr", round=group, seq=1, result=res)

    for row in rows:
        a = str(row[0] or "").strip()
        if a.startswith("Group "):
            flush()
            group, teams = a, {}
        elif group and re.fullmatch(r"[A-Z]\d+", a) and row[1]:
            teams[a] = (str(row[1]).strip(), row)
    flush()
    order: list[str] = []
    for rd, t1, t2, win in de_games or []:
        if rd not in order:
            order.append(rd)
        w.game(t1, t2, stage="playoff", round=rd, seq=2 + order.index(rd), result="1" if win == t1 else "2")


def parse_transcribed(t: Tournament, w: TournamentWriter, file: str = "bracket_transcribed.yaml") -> None:
    """Games hand-transcribed from a bracket image/PDF: a YAML list of
    {round, seq, stage, team1, score1, team2, score2, note?}."""
    import yaml

    for i, g in enumerate(yaml.safe_load(t.raw(file).read_text())["games"]):
        w.game(g["team1"], g["team2"], g.get("score1"), g.get("score2"), stage=g.get("stage", "playoff"),
               round=str(g["round"]), seq=g["seq"], game_id=f"m{g.get('match', i + 1)}", notes=g.get("note", ""))
