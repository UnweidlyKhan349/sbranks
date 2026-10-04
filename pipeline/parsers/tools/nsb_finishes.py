"""Derive every team's finish at each parsed NSB National Finals -> sources/reference/nsb_finishes.yaml.

    python -m pipeline.parsers.tools.nsb_finishes

* Double-elimination years: the champion is 1st, the loser of the last game 2nd; every other
  bracket team is placed by when it was eliminated (its last game, a loss); teams eliminated
  in the same round share a range such as "5-6" or "9-12".
* Teams that did not reach the bracket get finish "RR" with their division and round-robin
  record (2 points per win, 1 per tie) and the place implied by points within the division.
* Virtual years (2020, 2021): the published top-N lists.
"""
from __future__ import annotations

import csv
import re
import subprocess
from collections import defaultdict

import yaml

from ...config import PARSED_DIR, RAW_DIR, REFERENCE_DIR
from ..nsb_virtual import _bullets


def _range(a: int, b: int) -> str | int:
    return a if a == b else f"{a}-{b}"


def bracket_finishes(games: list[dict]) -> list[dict]:
    de = sorted([g for g in games if g["stage"] == "playoff" and g["result"] in ("1", "2")],
                key=lambda g: (int(g["seq"] or 0), g["game_id"]))
    if not de:
        return []
    last_game: dict[str, tuple[int, bool]] = {}
    for i, g in enumerate(de):
        w, l = (g["team1"], g["team2"]) if g["result"] == "1" else (g["team2"], g["team1"])
        last_game[w] = (i, True)
        last_game[l] = (i, False)
    final = de[-1]
    champ = final["team1"] if final["result"] == "1" else final["team2"]
    runner = final["team2"] if champ == final["team1"] else final["team1"]
    out = [{"team": champ, "finish": 1}, {"team": runner, "finish": 2}]
    # group the rest by the round (seq) of their last game
    seq_of = {i: int(g["seq"] or 0) for i, g in enumerate(de)}
    groups: dict[int, list[str]] = defaultdict(list)
    for team, (i, won) in last_game.items():
        if team in (champ, runner):
            continue
        groups[seq_of[i]].append(team)
    place = 3
    for seq in sorted(groups, reverse=True):
        teams = sorted(groups[seq])
        for t in teams:
            out.append({"team": t, "finish": _range(place, place + len(teams) - 1)})
        place += len(teams)
    return out


def rr_finishes(games: list[dict], teams: list[dict], in_bracket: set[str]) -> list[dict]:
    div_of = {}
    for g in games:
        if g["stage"] == "rr":
            div_of[g["team1"]] = div_of[g["team2"]] = g["round"]
    pts: dict[str, float] = defaultdict(float)
    rec: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for g in games:
        if g["stage"] != "rr":
            continue
        for me, other, k in ((g["team1"], g["team2"], "1"), (g["team2"], g["team1"], "2")):
            if g["result"] == "T":
                pts[me] += 1
                rec[me][2] += 1
            elif g["result"] == k:
                pts[me] += 2
                rec[me][0] += 1
            else:
                rec[me][1] += 1
    by_div: dict[str, list[str]] = defaultdict(list)
    for t, d in div_of.items():
        by_div[d].append(t)
    place = {}
    for d, ts in by_div.items():
        for t in ts:
            place[t] = 1 + sum(1 for o in ts if pts[o] > pts[t])
    out = []
    for tr in teams:
        t = tr["team"]
        if t in in_bracket or t not in div_of:
            continue
        w, l, ti = rec[t]
        out.append({"team": t, "finish": "RR", "division": div_of[t], "division_place": place[t],
                    "record": f"{w}-{l}" + (f"-{ti}" if ti else "")})
    return out


def main() -> None:
    result: dict[int, list[dict]] = {}
    for d in sorted(PARSED_DIR.glob("*-nsb-national-finals")):
        year = int(d.name[:4])
        games = list(csv.DictReader(open(d / "games.csv")))
        teams = list(csv.DictReader(open(d / "teams.csv")))
        if year == 2020:
            raw = RAW_DIR / d.name
            tiers = [("top2.pdf", 2), ("top4.pdf", 4), ("top8.pdf", 8), ("top16.pdf", 16)]
            seen: dict[str, str | int] = {}
            prev = 0
            for f, n in tiers:
                for school, _, _ in _bullets(raw / f):
                    if school not in seen:
                        seen[school] = _range(prev + 1, n)
                prev = n
            final = next(g for g in games if g["stage"] == "playoff")
            champ = final["team1"] if final["result"] == "1" else final["team2"]
            runner = final["team2"] if champ == final["team1"] else final["team1"]
            seen[champ], seen[runner] = 1, 2
            result[year] = [{"team": t, "finish": f} for t, f in sorted(seen.items(), key=lambda kv: str(kv[1]))]
            continue
        br = bracket_finishes(games)
        in_bracket = {x["team"] for x in br}
        result[year] = br + rr_finishes(games, teams, in_bracket)
    with open(REFERENCE_DIR / "nsb_finishes.yaml", "w") as fh:
        fh.write("# Finish of every team at each parsed NSB National Finals (HS), derived from the official\n"
                 "# brackets and round-robin grids. Generated by: python -m pipeline.parsers.tools.nsb_finishes\n")
        yaml.safe_dump(result, fh, sort_keys=False, allow_unicode=True, width=120)
    for y, items in result.items():
        print(y, len(items), [(x["team"], x["finish"]) for x in items[:6]])


if __name__ == "__main__":
    main()
