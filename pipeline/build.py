"""Full build: parsed tournaments -> resolved entities -> ratings -> site/data/*.json.

    python -m pipeline.build            # resolve + rate + export
    python -m pipeline.build --tune     # also grid-search Glicko parameters (writes params)
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import statistics
import sys
from collections import defaultdict
from typing import Any

import yaml

from . import registry, resolve
from .config import BUILD_DIR, REFERENCE_DIR, SUBJECTS
from .ratings import glicko, statsmodel

PARAMS_FILE = REFERENCE_DIR / "rating_params.yaml"
DEFAULT_TUH_PER_GAME = 22.0


def load_params() -> tuple[glicko.GlickoParams, statsmodel.ModelParams]:
    gp, mp = glicko.GlickoParams(), statsmodel.ModelParams()
    if PARAMS_FILE.exists():
        d = yaml.safe_load(PARAMS_FILE.read_text()) or {}
        for k, v in (d.get("glicko") or {}).items():
            setattr(gp, k, v)
        for k, v in (d.get("stats") or {}).items():
            setattr(mp, k, v)
    return gp, mp


def team_rated(t: registry.Tournament) -> bool:
    """Tournaments whose games feed the overall team rating."""
    return not t.get("subject_only") and not t.get("individual") and t.get("division", "HS") == "HS"


def build_periods(res: dict[str, Any], tourns: dict[str, registry.Tournament]) -> list[dict[str, Any]]:
    by_t: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in res["games"]:
        by_t[g["tournament_id"]].append(g)
    periods = []
    for tid, t in tourns.items():
        if tid not in by_t or not team_rated(t):
            continue
        periods.append({"id": tid, "date": t.end_date, "start": t.date, "season": t.season,
                        "level": t.get("level") or "standard", "kind": t.get("kind"),
                        "games": sorted(by_t[tid], key=lambda g: (g["seq"], g["game_id"]))})
    periods.sort(key=lambda p: (p["date"], p["start"], p["id"]))
    return periods


def tune(periods: list[dict[str, Any]], team_meta: dict[str, Any]) -> glicko.GlickoParams:
    grid = {
        "mov_weight": [0.0, 0.3, 0.5, 0.7],
        "mov_scale": [60.0, 100.0],
        "rd_per_year": [80.0, 140.0],
        "season_regress": [0.2, 0.4],
        "init_rd": [250.0, 330.0],
    }
    best, best_ll = None, 9e9
    keys = list(grid)
    for combo in itertools.product(*(grid[k] for k in keys)):
        p = glicko.GlickoParams(**dict(zip(keys, combo)))
        m = glicko.run(periods, team_meta, p, record=False)["metrics"]
        if m["log_loss"] is not None and m["log_loss"] < best_ll:
            best_ll, best = m["log_loss"], p
            print(f"  ll={m['log_loss']:.4f} acc={m['accuracy']:.3f} {dict(zip(keys, combo))}", flush=True)
    assert best is not None
    return best


def choose_rows(res: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """One row per (tournament, player, subject): scope 'all' if present, else rr+playoff sums."""
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in res["player_stats"]:
        grouped[(r["tournament_id"], r["player_id"], r["subject"])][r["scope"]] = r
    out = {}
    for k, scopes in grouped.items():
        if "all" in scopes:
            out[k] = dict(scopes["all"])
        elif "rr" in scopes and "playoff" in scopes:
            a, b = scopes["rr"], scopes["playoff"]
            if a["points"] is not None and b["points"] is not None:
                row = dict(a, scope="all")
                for f in ("gp", "tuh", "correct", "zeros", "negs", "points"):
                    row[f] = a[f] + b[f] if a[f] is not None and b[f] is not None else None
                row["ppg"] = None
                out[k] = row
            else:
                out[k] = dict(a)
        else:
            out[k] = dict(scopes.get("rr") or scopes["playoff"])
    return out


def enrich_rows(rows: dict[tuple[str, str, str], dict[str, Any]], res: dict[str, Any],
                tourns: dict[str, registry.Tournament]) -> None:
    """Fill estimated gp / points / tuh (est_* fields) used for weighting the model and display.

    * gp: the player's games, else the team's games in the row's scope (rr / playoff / all).
    * points: tossup points, else ppg * gp. Tournaments whose YAML sets
      ``stats_rate_basis: {overall: 20, subject: 4}`` report ppg as points per N tossups heard;
      those rates are converted with the estimated tossups heard instead.
    * tuh: tossups heard, else gp * (median tossups heard per game for that tournament/subject).
    """
    team_games: dict[tuple[str, str, str], int] = defaultdict(int)
    for g in res["games"]:
        if not g["forfeit"]:
            scope = "rr" if g["stage"] == "rr" else "playoff"
            for t in (g["team1"], g["team2"]):
                team_games[(g["tournament_id"], t, scope)] += 1
                team_games[(g["tournament_id"], t, "all")] += 1
    ratio: dict[tuple[str, str], list[float]] = defaultdict(list)
    gratio: dict[str, list[float]] = defaultdict(list)
    gps: dict[str, list[float]] = defaultdict(list)
    for (tid, pid, subj), r in rows.items():
        if r["gp"]:
            gps[tid].append(r["gp"])
            if r["tuh"]:
                ratio[(tid, subj)].append(r["tuh"] / r["gp"])
                gratio[subj].append(r["tuh"] / r["gp"])
    gdef = {s: statistics.median(v) for s, v in gratio.items() if v}
    for (tid, pid, subj), r in rows.items():
        gp = r["gp"] or team_games.get((tid, r["team_id"], r["scope"])) or team_games.get((tid, r["team_id"], "all")) \
            or (statistics.median(gps[tid]) if gps[tid] else None)
        tuh = r["tuh"]
        if not tuh and gp:
            per = ratio.get((tid, subj))
            rate = statistics.median(per) if per else gdef.get(subj, DEFAULT_TUH_PER_GAME if subj == "overall" else DEFAULT_TUH_PER_GAME / 6)
            tuh = gp * rate
        pts = r["points"]
        basis = tourns[tid].get("stats_rate_basis")
        if pts is None and r["ppg"] is not None:
            if basis and tuh:
                per_n = basis.get("overall" if subj == "overall" else "subject")
                if per_n:
                    pts = r["ppg"] / per_n * tuh
                    r["ppg"] = None  # it was a rate, not points per game
            elif gp:
                pts = r["ppg"] * gp
        r["est_gp"], r["est_points"], r["est_tuh"] = gp, pts, tuh


def sampling_variance(rows: dict[tuple[str, str, str], dict[str, Any]], subj: str) -> float | None:
    """Pooled per-tossup variance of tossup points: E[x^2] - E[x]^2 with x in {+4, -4, 0}."""
    c = n = pts = tuh = 0.0
    for (_, _, s), r in rows.items():
        if s == subj and r["correct"] is not None and r["negs"] is not None and r["tuh"]:
            c += r["correct"]
            n += r["negs"]
            pts += 4 * r["correct"] - 4 * r["negs"]
            tuh += r["tuh"]
    if tuh < 200:
        return None
    return 16.0 * (c + n) / tuh - (pts / tuh) ** 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--no-history", action="store_true", help="skip stats-model history snapshots")
    a = ap.parse_args(argv)

    res = resolve.build()
    print(f"resolved: {len(res['schools'])} schools, {len(res['teams'])} teams, {len(res['players'])} players, "
          f"{len(res['games'])} games", flush=True)
    tourns = {t.id: t for t in registry.all_tournaments() if t.id in set(res["tournament_ids"])}
    team_meta = {tid: {"school_id": t["school_id"], "letter": t["letter"], "composite": t["composite"]}
                 for tid, t in res["teams"].items()}
    gparams, mparams = load_params()
    periods = build_periods(res, tourns)
    if a.tune:
        gparams = tune(periods, team_meta)
        d = yaml.safe_load(PARAMS_FILE.read_text()) if PARAMS_FILE.exists() else {}
        d = d or {}
        d["glicko"] = {k: getattr(gparams, k) for k in ("mov_weight", "mov_scale", "rd_per_year",
                                                         "season_regress", "init_rd")}
        PARAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PARAMS_FILE.write_text(yaml.safe_dump(d, sort_keys=False))
    gres = glicko.run(periods, team_meta, gparams)
    print(f"glicko: {len(gres['teams'])} rated teams, metrics {gres['metrics']}", flush=True)

    # field strength = mean pre-tournament rating of the tournament's top 8 teams
    pre_by_t: dict[str, dict[str, float]] = defaultdict(dict)
    for g in gres["games"]:
        pre_by_t[g["tournament_id"]][g["team1"]] = g["pre1"]
        pre_by_t[g["tournament_id"]][g["team2"]] = g["pre2"]
    strength = {tid: statistics.mean(sorted(v.values(), reverse=True)[:8]) for tid, v in pre_by_t.items()}

    # ---- stats-model ratings
    rows = choose_rows(res)
    enrich_rows(rows, res, tourns)
    tlist = [{"id": tid, "end_day": statsmodel.day(t.end_date), "field_strength": strength.get(tid)}
             for tid, t in tourns.items()]
    snapshot_days = sorted({x["end_day"] for x in tlist})
    player_models: dict[str, Any] = {}
    team_models: dict[str, Any] = {}
    from dataclasses import replace
    for subj in ["overall", *SUBJECTS]:
        sp = mparams if subj == "overall" else replace(mparams, established_weight=mparams.established_weight / 5)
        prow, trow = [], defaultdict(lambda: {"points": 0.0, "tuh": 0.0})
        for (tid, pid, s), r in rows.items():
            if s != subj or r["est_points"] is None or not r["est_tuh"] or r["est_tuh"] < 1:
                continue
            so = tourns[tid].get("subject_only")
            if so and subj == "overall":
                continue  # single-subject events say nothing about overall strength
            prow.append({"entity": pid, "tournament_id": tid, "y": r["est_points"] / r["est_tuh"], "w": r["est_tuh"]})
            if subj != "overall" and r["team_id"]:
                tr = trow[(tid, r["team_id"])]
                tr["points"] += r["est_points"]
                tr["tuh"] = max(tr["tuh"], r["est_tuh"])
        sig2 = sampling_variance(rows, subj)
        player_models[subj] = statsmodel.run_model(prow, tlist, sp, snapshot_days, history=not a.no_history, sigma2=sig2)
        if subj != "overall":
            trows = [{"entity": team, "tournament_id": tid, "y": v["points"] / v["tuh"], "w": v["tuh"]}
                     for (tid, team), v in trow.items() if v["tuh"] >= 1]
            team_models[subj] = statsmodel.run_model(trows, tlist, sp, snapshot_days, history=not a.no_history, sigma2=sig2)
        pm = player_models[subj]
        print(f"stats model {subj}: {len(pm['entities'])} players (k={pm.get('k_theta', 0):.1f}, beta={pm['beta']:.3f}, "
              f"spread={pm['spread']:.3f}), {len(team_models.get(subj, {}).get('entities', {}))} teams", flush=True)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    from . import export
    export.export(res, tourns, gres, gparams, player_models, team_models, rows, strength)
    return 0


if __name__ == "__main__":
    sys.exit(main())
