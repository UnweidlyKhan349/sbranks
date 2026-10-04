"""Canonical per-tournament parsed output.

Every parser writes the same set of files into ``data/parsed/<tournament_id>/`` through
:class:`TournamentWriter`. Downstream stages (resolution, ratings, export) only read these
files, never the raw sources.

Files (all CSV, UTF-8, header row; empty string = unknown):

``teams.csv``
    team            Team name exactly as used in this tournament's other files.
    school          Optional school name hint from the source (e.g. a registration tab).
    state           Optional US state hint.
    players         Optional ``;``-separated roster (names as written in the source).
    notes           Free text.

``games.csv``  one row per game played
    game_id         Unique within the tournament (any string).
    stage           ``rr`` (round robin / pools / swiss / league), ``playoff`` (DE/SE/finals),
                    ``consolation``, ``tiebreaker`` or ``other``.
    round           Round label or number as in the source (e.g. ``3``, ``DE5``, ``Final``).
    seq             Integer giving play order within the tournament (round order). Games in
                    the same round share a value.
    team1, team2    Team names (must appear in teams.csv).
    score1, score2  Final scores, if known.
    result          ``1`` (team1 won), ``2`` (team2 won), ``T`` (tie). Required when scores
                    are unknown; when scores are known it is derived if left blank.
    forfeit         ``1`` if the game was a forfeit / bye-like result (excluded from ratings).
    notes           Free text.

``team_game_subjects.csv``  optional: per game, per team, per subject points
    game_id, team, subject, points, tossup_points, bonus_points, tossups_correct, negs

``player_stats.csv``  per-player tournament totals
    player          Player name as written in the source.
    team            Team name (must appear in teams.csv).
    scope           ``all`` (whole tournament), ``rr`` or ``playoff``.
    subject         ``overall`` or one of config.SUBJECTS or ``other``.
    gp              Games played.
    tuh             Tossups heard (for subject rows: tossups of that subject heard).
    correct         Correct tossups (4s).
    zeros           Incorrect answers without penalty (0s), if reported.
    negs            Interrupt penalties (-4s).
    points          Tossup points (normally 4*correct - 4*negs).
    ppg             Points per game, only if points/gp are not both available.

``player_game_stats.csv``  optional: per game, per player, per subject
    game_id, player, team, subject, correct, negs, points

``meta.json`` is written by :meth:`TournamentWriter.close` (counts + coverage flags +
parser warnings).
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import ALL_SUBJECT_KEYS, PARSED_DIR

TEAM_COLS = ["team", "school", "state", "players", "notes"]
GAME_COLS = ["game_id", "stage", "round", "seq", "team1", "team2", "score1", "score2",
             "result", "forfeit", "notes"]
TGS_COLS = ["game_id", "team", "subject", "points", "tossup_points", "bonus_points",
            "tossups_correct", "negs"]
PLAYER_COLS = ["player", "team", "scope", "subject", "gp", "tuh", "correct", "zeros", "negs",
               "points", "ppg"]
PGS_COLS = ["game_id", "player", "team", "subject", "correct", "negs", "points"]

STAGES = {"rr", "playoff", "consolation", "tiebreaker", "other"}
SCOPES = {"all", "rr", "playoff"}

FILES = {
    "teams": ("teams.csv", TEAM_COLS),
    "games": ("games.csv", GAME_COLS),
    "team_game_subjects": ("team_game_subjects.csv", TGS_COLS),
    "player_stats": ("player_stats.csv", PLAYER_COLS),
    "player_game_stats": ("player_game_stats.csv", PGS_COLS),
}


def clean_name(value: Any) -> str:
    """Collapse whitespace / strip a team or player name. Returns '' for None/NaN."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    s = str(value).replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def num(value: Any) -> float | None:
    """Parse a numeric cell ('12', '12.0', ' -4 ', '45%') -> float, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    s = str(value).strip().replace(",", "")
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        if v.is_integer():
            return str(int(v))
        return f"{v:.6g}"
    return str(v)


@dataclass
class TournamentWriter:
    """Collects canonical rows for one tournament and writes them to data/parsed/<id>/."""

    tournament_id: str
    out_dir: Path | None = None
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {k: [] for k in FILES})
    warnings: list[str] = field(default_factory=list)
    _teams: dict[str, dict[str, Any]] = field(default_factory=dict)
    _seq_counter: int = 0

    def __post_init__(self) -> None:
        if self.out_dir is None:
            self.out_dir = PARSED_DIR / self.tournament_id

    # ---- teams -------------------------------------------------------------------------
    def team(self, name: Any, school: str = "", state: str = "", players: Iterable[str] = (),
             notes: str = "") -> str:
        """Register a team (idempotent). Returns the cleaned team name."""
        n = clean_name(name)
        if not n:
            raise ValueError("empty team name")
        t = self._teams.get(n)
        if t is None:
            t = {"team": n, "school": clean_name(school), "state": clean_name(state),
                 "players": [], "notes": notes}
            self._teams[n] = t
        else:
            if school and not t["school"]:
                t["school"] = clean_name(school)
            if state and not t["state"]:
                t["state"] = clean_name(state)
        for p in players:
            p = clean_name(p)
            if p and p not in t["players"]:
                t["players"].append(p)
        return n

    # ---- games -------------------------------------------------------------------------
    def game(self, team1: Any, team2: Any, score1: Any = None, score2: Any = None, *,
             stage: str = "rr", round: Any = "", seq: int | None = None, result: str = "",
             forfeit: bool = False, game_id: str | None = None, notes: str = "") -> str:
        if stage not in STAGES:
            raise ValueError(f"bad stage {stage!r}")
        t1, t2 = self.team(team1), self.team(team2)
        if t1 == t2:
            raise ValueError(f"team plays itself: {t1}")
        s1, s2 = num(score1), num(score2)
        res = str(result or "").strip().upper()
        if res in ("T1", "W1"):
            res = "1"
        elif res in ("T2", "W2"):
            res = "2"
        if not res and s1 is not None and s2 is not None:
            res = "1" if s1 > s2 else "2" if s2 > s1 else "T"
        if res not in ("1", "2", "T"):
            raise ValueError(f"game {t1} vs {t2}: need scores or a result (got {result!r})")
        if seq is None:
            seq = self._seq_counter
        self._seq_counter = max(self._seq_counter, seq)
        gid = game_id or f"g{len(self.rows['games']) + 1}"
        self.rows["games"].append({
            "game_id": gid, "stage": stage, "round": clean_name(round), "seq": seq,
            "team1": t1, "team2": t2, "score1": s1, "score2": s2, "result": res,
            "forfeit": 1 if forfeit else 0, "notes": notes,
        })
        return gid

    # ---- subjects per game -------------------------------------------------------------
    def team_game_subject(self, game_id: str, team: Any, subject: str, points: Any = None, *,
                          tossup_points: Any = None, bonus_points: Any = None,
                          tossups_correct: Any = None, negs: Any = None) -> None:
        self._check_subject(subject)
        self.rows["team_game_subjects"].append({
            "game_id": game_id, "team": self.team(team), "subject": subject,
            "points": num(points), "tossup_points": num(tossup_points),
            "bonus_points": num(bonus_points), "tossups_correct": num(tossups_correct),
            "negs": num(negs),
        })

    # ---- players -----------------------------------------------------------------------
    def player_stat(self, player: Any, team: Any, subject: str = "overall", *, scope: str = "all",
                    gp: Any = None, tuh: Any = None, correct: Any = None, zeros: Any = None,
                    negs: Any = None, points: Any = None, ppg: Any = None) -> None:
        p = clean_name(player)
        if not p:
            raise ValueError("empty player name")
        if scope not in SCOPES:
            raise ValueError(f"bad scope {scope!r}")
        self._check_subject(subject)
        t = self.team(team)
        if p not in self._teams[t]["players"]:
            self._teams[t]["players"].append(p)
        row = {"player": p, "team": t, "scope": scope, "subject": subject, "gp": num(gp),
               "tuh": num(tuh), "correct": num(correct), "zeros": num(zeros), "negs": num(negs),
               "points": num(points), "ppg": num(ppg)}
        if row["points"] is None and row["correct"] is not None and row["negs"] is not None:
            row["points"] = 4 * row["correct"] - 4 * row["negs"]
        self.rows["player_stats"].append(row)

    def player_game_stat(self, game_id: str, player: Any, team: Any, subject: str = "overall", *,
                         correct: Any = None, negs: Any = None, points: Any = None) -> None:
        self._check_subject(subject)
        p = clean_name(player)
        t = self.team(team)
        if p and p not in self._teams[t]["players"]:
            self._teams[t]["players"].append(p)
        c, n, pts = num(correct), num(negs), num(points)
        if pts is None and c is not None and n is not None:
            pts = 4 * c - 4 * n
        self.rows["player_game_stats"].append({
            "game_id": game_id, "player": p, "team": t, "subject": subject,
            "correct": c, "negs": n, "points": pts})

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @staticmethod
    def _check_subject(subject: str) -> None:
        if subject not in ALL_SUBJECT_KEYS:
            raise ValueError(f"bad subject {subject!r}; use config.normalize_subject()")

    # ---- output ------------------------------------------------------------------------
    def close(self, extra_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.out_dir is not None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for f in self.out_dir.glob("*.csv"):
            f.unlink()
        self.rows["teams"] = [
            {**t, "players": ";".join(t["players"])} for t in self._teams.values()
        ]
        for key, (fname, cols) in FILES.items():
            rows = self.rows[key]
            if not rows and key not in ("teams", "games", "player_stats"):
                continue
            with open(self.out_dir / fname, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                w.writeheader()
                for r in rows:
                    w.writerow({c: _fmt(r.get(c)) for c in cols})
        ps = self.rows["player_stats"]
        meta = {
            "tournament_id": self.tournament_id,
            "counts": {
                "teams": len(self._teams),
                "games": len(self.rows["games"]),
                "games_with_scores": sum(1 for g in self.rows["games"] if g["score1"] is not None),
                "player_stat_rows": len(ps),
                "players": len({(r["player"], r["team"]) for r in ps}),
                "team_game_subject_rows": len(self.rows["team_game_subjects"]),
                "player_game_stat_rows": len(self.rows["player_game_stats"]),
            },
            "coverage": {
                "games": bool(self.rows["games"]),
                "scores": any(g["score1"] is not None for g in self.rows["games"]),
                "player_stats": bool(ps),
                "player_subject_stats": any(r["subject"] not in ("overall",) for r in ps),
                "player_tuh": any(r["tuh"] is not None for r in ps),
                "team_game_subjects": bool(self.rows["team_game_subjects"]),
                "player_game_stats": bool(self.rows["player_game_stats"]),
            },
            "warnings": self.warnings,
        }
        if extra_meta:
            meta.update(extra_meta)
        with open(self.out_dir / "meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        return meta


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_parsed(tournament_id: str) -> dict[str, Any]:
    d = PARSED_DIR / tournament_id
    out: dict[str, Any] = {k: read_csv(d / fname) for k, (fname, _) in FILES.items()}
    meta_path = d / "meta.json"
    out["meta"] = json.loads(meta_path.read_text()) if meta_path.exists() else None
    return out
