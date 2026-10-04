"""Consistency checks for parsed tournament output.

    python -m pipeline.validate [--only ID ...]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict

from . import registry
from .config import PARSED_DIR
from .schema import load_parsed, num


def validate_tournament(tid: str) -> list[str]:
    d = load_parsed(tid)
    problems: list[str] = []
    if d["meta"] is None:
        return ["not parsed (no meta.json)"]
    teams = {r["team"] for r in d["teams"]}
    games = d["games"]
    gids = Counter(g["game_id"] for g in games)
    for gid, n in gids.items():
        if n > 1:
            problems.append(f"duplicate game_id {gid}")
    played = defaultdict(int)
    for g in games:
        for k in ("team1", "team2"):
            if g[k] not in teams:
                problems.append(f"game {g['game_id']}: unknown team {g[k]!r}")
            played[g[k]] += 1
        s1, s2 = num(g["score1"]), num(g["score2"])
        if (s1 is None) != (s2 is None):
            problems.append(f"game {g['game_id']}: only one score")
        if s1 is not None and s2 is not None:
            exp = "1" if s1 > s2 else "2" if s2 > s1 else "T"
            if g["result"] != exp:
                problems.append(f"game {g['game_id']}: result {g['result']} disagrees with score {s1}-{s2}")
            for s in (s1, s2):
                if s < -200 or s > 600:
                    problems.append(f"game {g['game_id']}: implausible score {s}")
    # The same pairing twice in one round is almost always a parsing error.
    pair_round = Counter((g["stage"], g["round"], frozenset((g["team1"], g["team2"]))) for g in games)
    for (stage, rnd, pair), n in pair_round.items():
        if n > 1 and rnd:
            problems.append(f"pairing {sorted(pair)} appears {n}x in {stage} round {rnd}")
    # Each team should play at most once per round.
    team_round = Counter((g["stage"], g["round"], t) for g in games if g["round"] for t in (g["team1"], g["team2"]))
    for (stage, rnd, team), n in team_round.items():
        if n > 1:
            problems.append(f"{team!r} plays {n}x in {stage} round {rnd}")
    for r in d["player_stats"]:
        if r["team"] not in teams:
            problems.append(f"player {r['player']!r}: unknown team {r['team']!r}")
        c, n, p, gp, tuh = (num(r[k]) for k in ("correct", "negs", "points", "gp", "tuh"))
        if c is not None and n is not None and p is not None and abs(4 * c - 4 * n - p) > 0.51:
            problems.append(f"player {r['player']!r} {r['subject']}: points {p} != 4*{c} - 4*{n}")
        if gp is not None and (gp < 0 or gp > 60):
            problems.append(f"player {r['player']!r}: implausible gp {gp}")
        if tuh is not None and c is not None and c > tuh:
            problems.append(f"player {r['player']!r} {r['subject']}: correct {c} > tuh {tuh}")
        if p is None and num(r["ppg"]) is None:
            problems.append(f"player {r['player']!r} {r['subject']}: no points or ppg")
    keys = Counter((r["player"], r["team"], r["scope"], r["subject"]) for r in d["player_stats"])
    for k, n in keys.items():
        if n > 1:
            problems.append(f"duplicate player stat row {k}")
    for t in teams:
        if games and played[t] == 0 and not any(r["team"] == t for r in d["player_stats"]):
            problems.append(f"team {t!r} has no games and no player stats")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    ids = a.only or [t.id for t in registry.all_tournaments() if (PARSED_DIR / t.id).exists()]
    bad = 0
    for tid in ids:
        probs = validate_tournament(tid)
        print(f"{'OK ' if not probs else 'BAD'} {tid}" + (f" ({len(probs)} problems)" if probs else ""))
        for p in probs[:30]:
            print("   -", p)
        bad += bool(probs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
