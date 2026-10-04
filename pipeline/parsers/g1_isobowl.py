"""ISOBowl (isobowl.com) tournaments: tournament JSON + per-question score logs.

Raw files (raw/<id>/isobowl/):
    tournament.json   field (teams), playerMap (user id -> account name), rounds, games
                      (final scores, players), pools, playoff stages (bracket slots)
    scorelogs.json    per game, per question: subject, active players per side, tossup
                      attempts (user, outcome correct / incorrect / interruptIncorrect, points)
                      and the bonus result
    stats_page.txt    rendered https://isobowl.com/premier/tournaments/<slug>/stats (team and
                      individual tables), kept only for cross-checking

ISOBowl "isobowl-standard" scoring: tossup +4, interrupt penalty -4 *to the negging team*,
bonus +10. Final scores recomputed from the logs match ``finalScore`` exactly.

Player names: ISOBowl accounts carry a handle (playerMap) and each game records the display
name typed into the room. We pick the most name-like of these per account (e.g. "Veeraj S"
over "vegetables", "Maxwell Tsai" over "Max T") and strip team tags like "[SOG]"; accounts
that only ever used handles keep the handle.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter

_SUBJECTS = {
    "biology": "biology", "chemistry": "chemistry", "physics": "physics", "math": "math",
    "earth_and_space": "ess", "earth_space": "ess", "energy": "energy",
    "computer_science": "other",
}

_TAG = re.compile(r"\s*[\[(][^\])]*([\])]|$)")
_NAMEY = re.compile(r"^[A-Z][a-zA-Z'\-]+(?: [A-Z][a-zA-Z'\-]*\.?)+$")


def _clean_display(s: str) -> str:
    s = _TAG.sub("", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _name_score(s: str) -> tuple:
    """Rank candidate names: real-name-looking (Capitalized First + Last/initial) first,
    then longer last names, then capitalised single words, then anything else."""
    toks = s.split()
    namey = bool(_NAMEY.match(s))
    lower_namey = bool(re.match(r"^[a-z][a-z'\-]+(?: [a-z][a-z'\-]*\.?)+$", s)) and len(toks) == 2
    cap_single = bool(re.match(r"^[A-Z][a-z'\-]+$", s))
    lower_single = bool(re.match(r"^[a-z][a-z'\-]+$", s))
    has_digit = any(c.isdigit() for c in s)
    last_len = len(toks[-1].rstrip(".")) if len(toks) > 1 else 0
    tier = 4 if namey else 3 if lower_namey else 2 if cap_single else 1 if lower_single else 0
    if has_digit:
        tier = 0
    return (tier, last_len, len(s))


def choose_name(account_name: str, displays: set[str], overrides: dict[str, str] | None = None) -> str:
    if overrides and account_name in overrides:
        return overrides[account_name]
    cands = {_clean_display(x) for x in [account_name, *displays] if x}
    cands = {c for c in cands if c}
    if not cands:
        return account_name
    best = max(sorted(cands), key=_name_score)
    # Prefer the account name when it is as good as the best candidate.
    acc = _clean_display(account_name)
    if acc and _name_score(acc)[:2] >= _name_score(best)[:2]:
        return acc
    return best


def _subject(raw: str, t: Tournament, subject_override: str | None) -> str:
    if subject_override:
        return subject_override
    s = _SUBJECTS.get(raw) or normalize_subject((raw or "").replace("_", " "))
    if s:
        return s
    return t.get("subject_only") or "other"


def _clean_round(name: str) -> str:
    name = re.sub(r"\bDE DE\b", "DE", name.strip())
    return name


def parse(t: Tournament, w: TournamentWriter, subject_override: str | None = None,
          name_overrides: dict[str, str] | None = None, stage_map: dict[str, str] | None = None,
          team_names: dict[str, str] | None = None, extra_games: list[dict[str, Any]] | None = None) -> None:
    """``team_names`` renames ISOBowl team names (e.g. to the spelling used by other sources);
    ``extra_games`` adds games missing from ISOBowl (taken from another source), as dicts with
    team1, team2, score1, score2, stage, round, seq and a note naming the source."""
    d = t.raw_dir / "isobowl"
    tour = json.loads((d / "tournament.json").read_text())["tournament"]
    logs = {lg["gameId"]: lg["scorelog"] for lg in json.loads((d / "scorelogs.json").read_text())["logs"]}

    team_name = {tm["id"]: (team_names or {}).get(tm["name"].strip(), tm["name"].strip()) for tm in tour["teams"]}
    for tm in tour["teams"]:
        w.team(team_name[tm["id"]])
    rounds = {r["id"]: r for r in tour["rounds"]}
    stage_of = {"pool": "rr", "playoff": "playoff", "consolation": "consolation"}
    stage_of.update(stage_map or {})

    # Display names seen per account (from tossup attempts).
    displays: dict[str, set[str]] = defaultdict(set)
    for log in logs.values():
        for q in log:
            for r in q["results"]:
                for a in r["attempts"]:
                    if a.get("displayName"):
                        displays[a["userId"]].add(a["displayName"])
    pm = tour.get("playerMap") or {}

    def pname(uid: str) -> str:
        return choose_name(pm.get(uid, ""), displays.get(uid, set()), name_overrides) or uid

    # accumulate player stats keyed by (uid, team)
    acc: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games_by_player: dict[tuple[str, str], set[str]] = defaultdict(set)

    slot_of = {s["gameId"]: s for st in tour.get("stages") or [] for s in st.get("slots") or []
               if s.get("gameId")}

    games = sorted(tour["games"], key=lambda g: (rounds[g["roundId"]]["roundNumber"], g["id"]))
    for g in games:
        rnd = rounds[g["roundId"]]
        t1, t2 = team_name[g["teamAId"]], team_name[g["teamBId"]]
        fs = g.get("finalScore") or {}
        forfeit = bool(g.get("forfeitSide"))
        log = logs.get(g["id"])
        if not log and not forfeit:
            w.warn(f"game {g['id']} ({t1} vs {t2}) has no score log")
        note = ""
        slot = slot_of.get(g["id"])
        sa, sb = fs.get("a"), fs.get("b")
        if slot and slot.get("winnerTeamId") and sa is not None and sb is not None:
            by_score = g["teamAId"] if sa > sb else g["teamBId"] if sb > sa else None
            if by_score != slot["winnerTeamId"]:
                note = (f"bracket advanced {team_name.get(slot['winnerTeamId'], slot['winnerTeamId'])}"
                        f" ({slot.get('winnerSource')} decision)")
                w.warn(f"game {g['id'][:8]} {t1} {sa}-{sb} {t2}: {note}")
        gid = w.game(t1, t2, sa, sb, stage=stage_of.get(rnd["stage"], "other"),
                     round=_clean_round(rnd["name"]), seq=rnd["roundNumber"], forfeit=forfeit,
                     game_id=g["id"][:8], notes=note)
        if not log:
            continue
        side_team = {"a": t1, "b": t2}
        tgs: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        pgs: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        bonus_pts = {q["questionNumber"]: next((s["pointsForCorrect"] for s in q["slots"]
                                                if s["role"] == "bonus"), 10) for q in log}
        for q in log:
            subj = _subject(q["subject"], t, subject_override)
            # older logs have no per-question active lists: everyone in the game's lineup heard it
            active = q.get("activePlayers") or {"a": g.get("userIdsA") or [], "b": g.get("userIdsB") or []}
            heard = {(uid, side) for side in ("a", "b") for uid in active.get(side) or []}
            # a player who buzzed without being listed as active evidently heard it too
            heard |= {(a["userId"], a["teamId"]) for r in q["results"] if r["playedAs"] == "tossup"
                      for a in r["attempts"]}
            for uid, side in heard:
                games_by_player[(uid, side_team[side])].add(gid)
                acc[(uid, side_team[side], "overall")]["tuh"] += 1
                acc[(uid, side_team[side], subj)]["tuh"] += 1
            for side in ("a", "b"):
                tgs[(side_team[side], subj)]  # touch so every subject gets a row
            for r in q["results"]:
                if r["playedAs"] == "bonus":
                    if r.get("isCorrect") and r.get("answeredBy") in side_team:
                        tgs[(side_team[r["answeredBy"]], subj)]["bonus_points"] += bonus_pts[q["questionNumber"]]
                    continue
                for a in r["attempts"]:
                    team = side_team[a["teamId"]]
                    out = a["outcome"]
                    # interruptCorrect = early correct buzz (newer logs); some events score it as a
                    # 6-point power, but player stats keep the standard +4 so events stay comparable
                    k = {"correct": "correct", "interruptCorrect": "correct", "incorrect": "zeros",
                         "interruptIncorrect": "negs"}.get(out)
                    if k is None:
                        w.warn(f"game {gid}: unknown outcome {out!r}")
                        continue
                    for s in ("overall", subj):
                        acc[(a["userId"], team, s)][k] += 1
                        pgs[(a["userId"], team, s)][k] += 1
                    games_by_player[(a["userId"], team)].add(gid)
                    tg = tgs[(team, subj)]
                    tg["tossup_points"] += a["points"]
                    if k == "correct":
                        tg["tossups_correct"] += 1
                    elif k == "negs":
                        tg["negs"] += 1
        for (team, subj), v in sorted(tgs.items()):
            tp, bp = v.get("tossup_points", 0), v.get("bonus_points", 0)
            w.team_game_subject(gid, team, subj, tp + bp, tossup_points=tp, bonus_points=bp,
                                tossups_correct=v.get("tossups_correct", 0), negs=v.get("negs", 0))
        for (uid, team, subj), v in pgs.items():
            w.player_game_stat(gid, pname(uid), team, subj, correct=v.get("correct", 0),
                               negs=v.get("negs", 0))

    for i, eg in enumerate(extra_games or []):
        w.game(eg["team1"], eg["team2"], eg.get("score1"), eg.get("score2"), stage=eg.get("stage", "rr"),
               round=eg.get("round", ""), seq=eg.get("seq", 0), forfeit=bool(eg.get("forfeit")),
               game_id=f"extra{i + 1}", notes=eg.get("note", ""))

    # Two accounts with the same chosen name on one team are merged (same person
    # re-joining under a new account); the stats page lists them separately.
    merged: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    merged_games: dict[tuple[str, str], set[str]] = defaultdict(set)
    uids_for: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (uid, team, subj), v in acc.items():
        n = pname(uid)
        uids_for[(n, team)].add(uid)
        for k, x in v.items():
            merged[(n, team, subj)][k] += x
    for (uid, team), gids in games_by_player.items():
        merged_games[(pname(uid), team)] |= gids
    for (n, team), uids in uids_for.items():
        if len(uids) > 1:
            w.warn(f"merged {len(uids)} accounts named {n!r} on {team}")
    for (n, team, subj), v in sorted(merged.items()):
        c, z, ng = v.get("correct", 0), v.get("zeros", 0), v.get("negs", 0)
        if subj != "overall" and not (c or z or ng or v.get("tuh")):
            continue
        w.player_stat(n, team, subj, gp=len(merged_games[(n, team)]), tuh=v.get("tuh", 0),
                      correct=c, zeros=z, negs=ng, points=4 * c - 4 * ng)
