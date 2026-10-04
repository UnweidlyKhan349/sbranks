"""Prometheus 2022 (prometheus.science/2022), online, 26-27 March 2022.

The results and statistics pages embed published Google Sheets whose whole-workbook xlsx
export fails (HTTP 400), so raw/<id>/results_sheet/ and raw/<id>/stats_sheet/ hold per-tab
CSV snapshots made by tools/g2_fetch_pubsheet.py.

results: "RR Scores" (16 divisions; each row = a team's score and W/L/T against each
         column opponent), "DE Results" (32-team double-elimination bracket).
stats:   "Total Stats" (prelim player totals with the player's Google account id) and one
         tab per category (Longtermism, Math, Chemistry, Earth and Space, Biology, Physics).
         GP equals the number of round-robin games, so the stats are scope "rr".

Players are listed by first name only. ``name_lookup`` lists other Prometheus-platform
tournaments whose stats workbooks have a "Users" tab (Google id -> full name); a player gets
that full name when the Google id matches and the first names agree.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..registry import Tournament, get as get_tournament
from ..schema import TournamentWriter, clean_name
from ..util.grid import header_index, load_grids
from .g2_common import alias, bracket_games, csv_grids, rr_matrix

SUBJECT_TABS = {"Longtermism": "other", "Math": "math", "Chemistry": "chemistry",
                "Earth and Space": "ess", "Biology": "biology", "Physics": "physics"}


def _full_names(ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for tid in ids:
        t = get_tournament(tid)
        users = load_grids(t.raw("stats_sheet.xlsx"))["Users"]
        h = users.row_texts(0)
        gi, fi = header_index(h, r"^googleId$"), header_index(h, r"^fullName$")
        for r in range(1, users.nrows):
            gid = users.text(r, gi)
            full = re.sub(r"^[\[(][^\])]*[\])]\s*", "", users.text(r, fi))
            full = clean_name(re.sub(r"\s*\[[^\]]*\]\s*$", "", full))
            if gid and full:
                out.setdefault(gid, full)
    return out


def parse(t: Tournament, w: TournamentWriter, aliases: dict[str, str] | None = None,
          schools: dict[str, str] | None = None, states: dict[str, str] | None = None,
          name_lookup: list[str] | None = None) -> None:
    aliases = aliases or {}
    res = csv_grids(t.raw_dir / "results_sheet")
    st = csv_grids(t.raw_dir / "stats_sheet")
    for team, school in (schools or {}).items():
        w.team(team, school=school, state=(states or {}).get(team, ""))

    # ---- round robin ----------------------------------------------------------------------
    rgames, standings, warns = rr_matrix(res["RR Scores"], aliases)
    for m in warns:
        w.warn(m)
    games: list[dict[str, Any]] = []
    for g in rgames:
        games.append({"t1": g.t1, "t2": g.t2, "s1": g.s1, "s2": g.s2, "stage": "rr",
                      "round": "", "seq": 1, "result": g.result, "forfeit": g.forfeit,
                      "notes": "; ".join(x for x in (f"division {g.division}", g.notes) if x)})
    # ---- double elimination ------------------------------------------------------------------
    bgames, bw = bracket_games(res["DE Results"], 0, aliases)
    for m in bw:
        w.warn(m)
    cols = sorted({g.col for g in bgames})
    for g in bgames:
        games.append({"t1": g.t1, "t2": g.t2, "s1": g.s1, "s2": g.s2, "stage": "playoff",
                      "round": f"DE {g.round_label.title()}", "seq": 2 + cols.index(g.col),
                      "notes": g.notes})
    for gm in games:
        w.game(gm["t1"], gm["t2"], gm["s1"], gm["s2"], stage=gm["stage"], round=gm["round"],
               seq=gm["seq"], result=gm.get("result", ""), forfeit=gm.get("forfeit", False),
               notes=gm["notes"])
    # standings cross-check
    rec: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for gm in games:
        if gm["stage"] != "rr":
            continue
        res_ = gm["result"] or ("1" if gm["s1"] > gm["s2"] else "2" if gm["s2"] > gm["s1"] else "T")
        if res_ == "T":
            rec[gm["t1"]][1] += 1
            rec[gm["t2"]][1] += 1
        else:
            win, lose = (gm["t1"], gm["t2"]) if res_ == "1" else (gm["t2"], gm["t1"])
            rec[win][0] += 1
            rec[lose][2] += 1
    for team, s in standings.items():
        src = (s.get("W"), s.get("T"), s.get("L"))
        if src[0] is not None and tuple(rec[team]) != src:
            w.warn(f"standings: {team} source W-T-L {src}, parsed {tuple(rec[team])}")

    # ---- player stats (prelims) ------------------------------------------------------------
    names = _full_names(name_lookup or [])
    tot = st["Total Stats"]
    h = tot.row_texts(0)
    c = {k: header_index(h, rf"^{re.escape(k)}$") for k in
         ("Player Name", "Team Name", "Player ID", "GP", "TUH", "TU", "X", "Neg", "Points")}
    display: dict[str, str] = {}
    n_full = 0
    rows = []
    for r in range(1, tot.nrows):
        first = tot.text(r, c["Player Name"])
        pid = tot.text(r, c["Player ID"])
        if not first or first == "#N/A" or pid in ("", "NULL"):
            continue
        team = alias(tot.text(r, c["Team Name"]), aliases)
        full = names.get(pid, "")
        if len(full.split()) >= 2 and full.split()[0].lower() == first.split()[0].lower():
            n_full += 1
        else:
            full = ""
        rows.append((r, first, team, pid, full))
    dup = defaultdict(list)
    for r, first, team, pid, full in rows:
        if not full:
            dup[(first, team)].append(pid)
    for r, first, team, pid, full in rows:
        pname = full or first
        if not full and len(dup[(first, team)]) > 1:
            # two players with the same first name on one team: keep them apart
            pname = f"{first} ({dup[(first, team)].index(pid) + 1})"
        display[pid] = pname
        w.player_stat(pname, team, "overall", scope="rr", gp=tot.num(r, c["GP"]),
                      tuh=tot.num(r, c["TUH"]), correct=tot.num(r, c["TU"]),
                      zeros=tot.num(r, c["X"]), negs=tot.num(r, c["Neg"]),
                      points=tot.num(r, c["Points"]))
    for tab, subj in SUBJECT_TABS.items():
        g = st[tab]
        h = g.row_texts(0)
        sc = {k: header_index(h, rf"^{re.escape(k)}$") for k in
              ("Player Name", "Team Name", "Player ID", "GP", "TUH", "TU", "X", "Neg", "Points")}
        for r in range(1, g.nrows):
            pid = g.text(r, sc["Player ID"])
            if not g.text(r, sc["Player Name"]) or g.text(r, sc["Player Name"]) == "#N/A":
                continue
            pname = display.get(pid)
            if pname is None:
                w.warn(f"{tab}: player {g.text(r, sc['Player Name'])} not in Total Stats")
                continue
            # the category tabs' TUH column repeats the player's overall TUH (24 per game),
            # not tossups heard in that category, so it is not used for subject rows
            w.player_stat(pname, alias(g.text(r, sc["Team Name"]), aliases), subj, scope="rr",
                          gp=g.num(r, sc["GP"]), tuh=None,
                          correct=g.num(r, sc["TU"]), zeros=g.num(r, sc["X"]),
                          negs=g.num(r, sc["Neg"]), points=g.num(r, sc["Points"]))
    if names:
        w.warn(f"info: {n_full} of {len(display)} players named via Google-account lookup")
