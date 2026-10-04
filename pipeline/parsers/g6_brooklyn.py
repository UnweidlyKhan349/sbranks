"""Brooklyn Tech Invitational (online) results workbooks.

``parse_2024``
    ``Round Robin Rounds``: game blocks ``Game RR1-3 | Team 7 | Team 1`` with a ``SCORES`` row
    below, and a team table (Team No. | High School Name | Team Name | RR1-RR3 win flags |
    TOTAL PR) used for names, school hints and a W-L cross-check. ``Elimination Rounds``: the
    same block format for the single-elimination games.

``parse_2025``
    ``Round Robin Groups`` (``A1: Cupertino A``), ``Results`` (per group: row team's score vs
    column opponent; RECORD column), ``RR Schedule`` (``A1 vs. A2 - Nuuk (1)`` per round) and
    ``SE Schedule`` (``VC 1: X vs. Y`` with ``a - b`` scores). The final and 3rd-place game
    have no scores in the sheet; their winners come from the organizers' notes on the
    ``Field`` tab (passed as ``se_winners``).
"""
from __future__ import annotations

import re
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import load_grids
from .g6_common import SCORE_RE, Roster, score_matrix_pairs


def _strip_symbols(s: str) -> str:
    return clean_name(re.sub(r"[^\w\s.,'&()\-/]", "", s))


# ---------------------------------------------------------------------------------------
def parse_2024(t: Tournament, w: TournamentWriter, team_names: dict[str, str] | None = None) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    g = grids["Round Robin Rounds"]
    hdr = g.find_first(r"^Team No\.$")
    r0, c0 = hdr
    teams: dict[int, str] = {}
    flags: dict[str, list[str]] = {}
    totals: dict[str, float] = {}
    for r in range(r0 + 1, g.nrows):
        n = g.num(r, c0)
        if n is None or int(n) in teams:
            if n is None:
                break
            continue
        school = clean_name(g.text(r, c0 + 1).rstrip("*"))
        tname = _strip_symbols(g.text(r, c0 + 2))
        name = (team_names or {}).get(str(int(n))) or (
            f"{school} {tname}" if len(tname) <= 2 else tname)
        teams[int(n)] = w.team(name, school=school)
        flags[name] = [g.text(r, c0 + k) for k in (3, 4, 5)]
        totals[name] = g.num(r, c0 + 6) or 0

    def team(cell: str) -> str:
        m = re.match(r"^Team (\d+)$", cell)
        if not m:
            raise ValueError(f"bad team cell {cell!r}")
        return teams[int(m.group(1))]

    wins: dict[str, list[bool]] = {n: [] for n in teams.values()}
    for tab, rx, stage in (("Round Robin Rounds", r"^Game RR(\d+)-(\d+)$", "rr"),
                           ("Elimination Rounds", r"^Game (\d+)-(\d+)$", "playoff")):
        gg = grids[tab]
        for r, c in gg.find(rx):
            m = re.match(rx, gg.text(r, c))
            a, b = team(gg.text(r, c + 1)), team(gg.text(r, c + 2))
            if gg.text(r + 1, c) != "SCORES":
                raise ValueError(f"{tab} {gg.text(r, c)}: no SCORES row")
            sa, sb = gg.num(r + 1, c + 1), gg.num(r + 1, c + 2)
            if stage == "rr":
                rnd, seq = f"RR{m.group(1)}", int(m.group(1))
            else:
                size = int(m.group(1))
                rnd = {10: "Quarterfinals", 8: "Quarterfinals", 4: "Semifinals", 2: "Final"}[size]
                seq = {10: 4, 8: 4, 4: 5, 2: 6}[size]
            notes = ""
            if stage == "rr" and (sa == 0 or sb == 0):
                notes = "0 points in the source"
            w.game(a, b, sa, sb, stage=stage, round=rnd, seq=seq,
                   game_id=gg.text(r, c).replace("Game ", ""), notes=notes)
            if stage == "rr":
                wins[a].append((int(m.group(1)), sa > sb))
                wins[b].append((int(m.group(1)), sb > sa))
    # cross-check RR win flags / TOTAL PR in the team table
    for name, ws in wins.items():
        for rnd, won in ws:
            f = flags[name][rnd - 1]
            if f and (f == "True") != won:
                w.warn(f"{name} RR{rnd}: win flag {f} disagrees with scores")
        if sum(won for _, won in ws) != totals[name]:
            w.warn(f"{name}: TOTAL PR {totals[name]} != computed wins")


# ---------------------------------------------------------------------------------------
def parse_2025(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
               se_winners: dict[str, str] | None = None, team_notes: dict[str, str] | None = None) -> None:
    grids = load_grids(t.raw("results.xlsx"))
    code: dict[str, str] = {}
    gg = grids["Round Robin Groups"]
    group_of: dict[str, str] = {}
    for r in range(gg.nrows):
        for c in range(gg.ncols):
            m = re.match(r"^([A-Z]\d+):\s*(.+)$", gg.text(r, c))
            if m:
                raw = m.group(2)
                name = re.sub(r"\s*\(.*\)$", "", raw)
                note = (team_notes or {}).get(name, "")
                if raw != name:
                    note = (note + f"; listed as '{raw}'").strip("; ")
                code[m.group(1)] = w.team(name, notes=note)
                group_of[m.group(1)] = gg.text(0, c)
    roster = Roster(code.values(), aliases)
    # Field tab: registered names with nicknames in parentheses, e.g. 'BISV B | (Ligma)'
    if "Field" in grids:
        fg = grids["Field"]
        for r in range(fg.nrows):
            nick = fg.text(r, 1)
            if not nick.startswith("("):
                continue
            try:
                tm = roster.resolve(fg.text(r, 0))
            except KeyError:
                continue
            w._teams[tm]["notes"] = (w._teams[tm]["notes"] + f"; also called {nick.strip('()')}").strip("; ")

    # rounds from the RR schedule
    sch = grids["RR Schedule"]
    round_of: dict[frozenset, int] = {}
    for c in range(sch.ncols):
        m = re.match(r"^RR(\d+)$", sch.text(0, c))
        if not m:
            continue
        for r in range(1, sch.nrows):
            mm = re.match(r"^([A-Z]\d+) vs\. ([A-Z]\d+)", sch.text(r, c))
            if mm:
                round_of[frozenset((mm.group(1), mm.group(2)))] = int(m.group(1))

    res = grids["Results"]
    rec_col = None
    for r in range(res.nrows):
        heads = [res.text(r, c) for c in range(1, res.ncols)]
        if not heads or not re.match(r"^[A-Z]1$", heads[0]):
            continue
        cols = [h for h in heads if re.match(r"^[A-Z]\d+$", h)]
        rec_col = 1 + heads.index("RECORD") if "RECORD" in heads else rec_col
        rows = []
        rr = r + 1
        while rr < res.nrows and re.match(r"^[A-Z]\d+$", res.text(rr, 0)):
            rows.append(rr)
            rr += 1
        ids = [res.text(x, 0) for x in rows]
        if ids != cols[:len(ids)]:
            raise ValueError(f"Results row {r}: rows {ids} vs cols {cols}")
        present = [i for i in ids if i in code]
        idx = {i: k for k, i in enumerate(ids)}
        rec: dict[str, list[int]] = {i: [0, 0, 0] for i in present}
        for i, j, si, sj in score_matrix_pairs(
                present, lambda a, b: res.cell(rows[idx[present[a]]], 1 + idx[present[b]]), w, "Results"):
            a, b = present[i], present[j]
            rnd = round_of.get(frozenset((a, b)))
            if rnd is None:
                w.warn(f"no RR round for {a} vs {b}")
            w.game(code[a], code[b], si, sj, stage="rr", round=f"RR{rnd}" if rnd else "",
                   seq=rnd or 1, notes=group_of.get(a, ""))
            k = 0 if si > sj else 1 if si < sj else 2
            rec[a][k] += 1
            rec[b][{0: 1, 1: 0, 2: 2}[k]] += 1
        # RECORD column cross-check (Sheets turned "2-3" into a date: month-day)
        for x in rows:
            i = res.text(x, 0)
            v = res.cell(x, rec_col) if rec_col else None
            if i not in rec or v is None:
                continue
            if hasattr(v, "month"):
                exp = [v.month, v.day, 0]
            else:
                exp = [int(p) for p in str(v).split("-")] + [0]
            if rec[i][:2] != exp[:2] or (len(exp) > 3 and rec[i][2] != exp[2]):
                w.warn(f"{code[i]}: record {v} != computed {rec[i]}")

    # single elimination
    se = grids["SE Schedule"]
    seq0 = max(round_of.values(), default=0)
    rounds = {}
    for c in range(se.ncols):
        h = se.text(0, c)
        m = re.match(r"^(QUARTERFINALS|SEMIFINALS|FINALS)", h)
        if m:
            rounds[c] = m.group(1).title()
    for r in range(1, se.nrows):
        for c in range(se.ncols):
            txt = se.text(r, c)
            m = re.match(r"^(VC \d+|3rd place):\s*(.+?)\s+vs\.\s+(.+?)\s*$", txt)
            if not m:
                continue
            label = "3rd Place" if m.group(1) == "3rd place" else rounds[max(k for k in rounds if k <= c)]
            right = m.group(3)
            sm = re.search(r"\.?\s+(\d+\s*-\s*\d+)$", right)
            score = None
            if sm:
                right, score = right[:sm.start()], sm.group(1)
            else:
                for cc in range(c + 1, min(c + 3, se.ncols)):
                    if SCORE_RE.match(se.text(r, cc)):
                        score = se.text(r, cc)
                        break
            a, b = roster.resolve(m.group(2).rstrip(". ")), roster.resolve(right.rstrip(". "))
            seq = seq0 + {"Quarterfinals": 1, "Semifinals": 2, "Finals": 3, "3rd Place": 3}[label]
            if score:
                sa, sb = (num(x) for x in SCORE_RE.match(score).groups())
                w.game(a, b, sa, sb, stage="playoff", round=label, seq=seq,
                       game_id=f"{label}-{m.group(1)}")
            else:
                win = (se_winners or {}).get(label)
                if not win:
                    w.warn(f"{label}: {a} vs {b} has no score and no winner")
                    continue
                win = roster.resolve(win)
                w.game(a, b, stage="playoff", round=label, seq=seq, result="1" if win == a else "2",
                       game_id=f"{label}-{m.group(1)}",
                       notes="no score in source; winner from the organizers' note on the Field tab")
