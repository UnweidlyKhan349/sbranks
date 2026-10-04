"""scibowl.live stats exports (MoSS scoresheets): clean per-game, per-category CSVs.

Uses the ``combined`` report in raw/<id>/scibowl_live/combined/:
games.csv, game_teams.csv, game_teams_by_category.csv, game_players.csv,
game_players_by_category.csv.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, num


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _stage(round_name: str) -> str:
    n = round_name.lower()
    if "consol" in n:
        return "consolation"
    if "tiebreak" in n:
        return "tiebreaker"
    if re.search(r"elim|playoff|final|semi|quarter|bracket", n):
        return "playoff"
    return "rr"


def parse(t: Tournament, w: TournamentWriter, report: str = "combined") -> None:
    d = t.raw_dir / "scibowl_live" / report
    games = {g["game_id"]: g for g in _rows(d / "games.csv")}
    slots: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in _rows(d / "game_teams.csv"):
        slots[r["game_id"]].append(r)

    for p in _rows(d / "players.csv"):
        w.team(p["team_name"], players=[p["player_name"]])

    for gid, g in sorted(games.items(), key=lambda kv: (int(kv[1]["round_number"]), kv[0])):
        if g.get("status") and g["status"] != "COMPLETED":
            w.warn(f"game {gid} status {g['status']}")
            continue
        s = sorted(slots.get(gid, []), key=lambda r: r["slot"])
        if len(s) != 2:
            w.warn(f"game {gid}: {len(s)} team rows")
            continue
        w.game(s[0]["team_name"], s[1]["team_name"], s[0]["score"], s[1]["score"],
               stage=_stage(g["round_name"]), round=g["round_name"], seq=int(g["round_number"]),
               game_id=gid)

    for r in _rows(d / "game_teams_by_category.csv"):
        subj = normalize_subject(r["category"]) or "other"
        tp, bp = num(r["tossup_points"]) or 0, num(r["bonus_points"]) or 0
        w.team_game_subject(r["game_id"], r["team_name"], subj, tp + bp, tossup_points=tp,
                            bonus_points=bp, tossups_correct=r["tossups_correct"],
                            negs=r["tossups_incorrect"])

    # Per-game player rows -> tournament totals. pairs_heard is the number of tossups the
    # player was on the buzzer for; per-category tossups heard come from the team's category rows.
    cat_heard: dict[tuple[str, str, str], float] = {}
    for r in _rows(d / "game_teams_by_category.csv"):
        heard = sum(num(r[k]) or 0 for k in ("bonuses_correct", "bonuses_incorrect", "bonuses_unheard"))
        cat_heard[(r["game_id"], r["team_name"], normalize_subject(r["category"]) or "other")] = heard
    tot: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games_by_player: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in _rows(d / "game_players.csv"):
        key = (r["player_name"], r["team_name"], "overall")
        a = tot[key]
        a["tuh"] += num(r["pairs_heard"]) or 0
        a["correct"] += num(r["tossups_correct"]) or 0
        a["negs"] += num(r["tossups_incorrect"]) or 0
        a["zeros"] += num(r["tossups_no_penalty"]) or 0
        a["points"] += num(r["tossup_points"]) or 0
        games_by_player[(r["player_name"], r["team_name"])].add(r["game_id"])
        w.player_game_stat(r["game_id"], r["player_name"], r["team_name"], "overall",
                           correct=r["tossups_correct"], negs=r["tossups_incorrect"],
                           points=r["tossup_points"])
    for r in _rows(d / "game_players_by_category.csv"):
        subj = normalize_subject(r["category"]) or "other"
        a = tot[(r["player_name"], r["team_name"], subj)]
        a["correct"] += num(r["tossups_correct"]) or 0
        a["negs"] += num(r["tossups_incorrect"]) or 0
        a["zeros"] += num(r["tossups_no_penalty"]) or 0
        a["points"] += num(r["tossup_points"]) or 0
        w.player_game_stat(r["game_id"], r["player_name"], r["team_name"], subj,
                           correct=r["tossups_correct"], negs=r["tossups_incorrect"],
                           points=r["tossup_points"])
    # subject TUH: tossups of that category heard in games the player played
    for (player, team), gids in games_by_player.items():
        subj_heard: dict[str, float] = defaultdict(float)
        for (gid, tm, subj), h in cat_heard.items():
            if tm == team and gid in gids:
                subj_heard[subj] += h
        for subj, h in subj_heard.items():
            if (player, team, subj) in tot:
                tot[(player, team, subj)]["tuh"] = h

    for (player, team, subj), a in tot.items():
        gp = len(games_by_player.get((player, team), ()))
        w.player_stat(player, team, subj, gp=gp, tuh=a.get("tuh"), correct=a["correct"],
                      zeros=a["zeros"], negs=a["negs"], points=a["points"])
