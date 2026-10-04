"""Write the static site's data files (site/data/). See docs/DATA_CONTRACT.md."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from collections import Counter, defaultdict
from typing import Any

import yaml

from . import registry
from .config import REFERENCE_DIR, SITE_DATA_DIR, SUBJECT_LABELS, SUBJECTS
from .ratings import glicko

N_SHARDS = 32
RANKED_RD = 110.0            # team leaderboard: RD at or below this is "ranked"
ACTIVE_DAYS = 400            # active = played within this many days of the snapshot
PLAYER_MIN_WEIGHT = {"overall": 200.0, **{s: 30.0 for s in SUBJECTS}}  # effective tossups heard to be ranked
PLAYER_MIN_TOURNAMENTS = 2                                               # ... and at least this many events


def shard_of(entity_id: str) -> int:
    """djb2 hash mod N_SHARDS (mirrored in site/js/data.js)."""
    h = 5381
    for ch in entity_id:
        h = ((h * 33) + ord(ch)) & 0xFFFFFFFF
    return h % N_SHARDS


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(float(x), nd)


def _date(day: int) -> str:
    return dt.date.fromordinal(day).isoformat()


def _write(name: str, obj: Any) -> None:
    path = SITE_DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


def _rank(items: list[tuple[str, float]]) -> dict[str, int]:
    return {k: i + 1 for i, (k, _) in enumerate(sorted(items, key=lambda kv: -kv[1]))}


def export(res: dict[str, Any], tourns: dict[str, registry.Tournament], gres: dict[str, Any],
           gparams: glicko.GlickoParams, player_models: dict[str, Any], team_models: dict[str, Any],
           rows: dict[tuple[str, str, str], dict[str, Any]], strength: dict[str, float]) -> None:
    if SITE_DATA_DIR.exists():
        shutil.rmtree(SITE_DATA_DIR)
    SITE_DATA_DIR.mkdir(parents=True)
    snapshot = max(t.end_date for t in tourns.values())
    snap_day = snapshot.toordinal()
    schools, teams, players = res["schools"], res["teams"], res["players"]
    tdate = {tid: t.end_date.isoformat() for tid, t in tourns.items()}

    # ------------------------------------------------------------------ tournaments
    games_by_t: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in gres["games"]:
        games_by_t[g["tournament_id"]].append(g)
    logged = {(g["tournament_id"], g["game_id"]) for g in gres["games"]}
    for g in res["games"]:  # games not fed to Glicko (subject-only events, forfeits)
        if (g["tournament_id"], g["game_id"]) not in logged:
            games_by_t[g["tournament_id"]].append({**g, "p1": None, "unrated": True})
    entries_by_t: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in res["entries"]:
        entries_by_t[e["tournament_id"]].append(e)
    rows_by_t: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (tid, pid, subj), r in rows.items():
        rows_by_t[tid].append(r)
    # 1v1 events: raw competitor name -> player id (when the event published player stats)
    pid_by_raw = {(r["tournament_id"], r["raw_player"]): r["player_id"] for r in res["player_stats"] if r["team_id"] is None}

    tournaments_out = []
    team_tourn_summary: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roster: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for tid, t in sorted(tourns.items(), key=lambda kv: (kv[1].end_date, kv[0])):
        gl = sorted(games_by_t.get(tid, []), key=lambda g: (g["seq"], g["game_id"]))
        rec: dict[str, dict[str, float]] = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0, "gs": 0, "g": 0})
        for g in gl:
            if g.get("forfeit"):
                continue
            for me, opp, sm, so in (("team1", "team2", "score1", "score2"), ("team2", "team1", "score2", "score1")):
                r = rec[g[me]]
                r["g"] += 1
                if g["result"] == "T":
                    r["t"] += 1
                elif (g["result"] == "1") == (me == "team1"):
                    r["w"] += 1
                else:
                    r["l"] += 1
                if g[sm] is not None:
                    r["pf"] += g[sm]
                    r["pa"] += g[so]
                    r["gs"] += 1
        champion = _champion(gl)
        competitors = _individual_standings(tid, pid_by_raw) if t.get("individual") else None
        prow: dict[str, dict[str, Any]] = {}
        for r in rows_by_t.get(tid, []):
            pid = r["player_id"]
            pr = prow.setdefault(pid, {"p": pid, "tm": r["team_id"], "s": {}})
            pr["s"][r["subject"]] = {k: _r(v, 2) for k, v in (
                ("gp", r["gp"] if r["gp"] is not None else r["est_gp"]), ("tuh", r["tuh"]), ("c", r["correct"]),
                ("n", r["negs"]), ("pts", r["points"] if r["points"] is not None else r["est_points"]),
                ("ppg", r["ppg"])) if v is not None}
            if r["gp"] is None and r["est_gp"] is not None:
                pr["s"][r["subject"]]["gp_est"] = True
            if r["team_id"]:
                roster[r["team_id"]][t.season].add(pid)
        team_rows = []
        for e in entries_by_t[tid]:
            r = rec.get(e["team_id"], {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0, "gs": 0, "g": 0})
            row = {"tm": e["team_id"], "raw": e["raw_name"], "w": r["w"], "l": r["l"], "t": r["t"], "g": r["g"],
                   "ppg": _r(r["pf"] / r["gs"]) if r["gs"] else None,
                   "papg": _r(r["pa"] / r["gs"]) if r["gs"] else None}
            team_rows.append(row)
            team_tourn_summary[e["team_id"]].append({"t": tid, "d": tdate[tid], "w": row["w"], "l": row["l"], "tie": row["t"],
                                                     "g": row["g"], "ppg": row["ppg"], "champ": champion == e["team_id"]})
        team_rows.sort(key=lambda x: (-(x["w"] + 0.5 * x["t"]), x["l"], -(x["ppg"] or -999)))
        cov = _coverage(tid)
        meta = {
            "id": tid, "name": t.name, "date": t.date.isoformat(), "end": t.end_date.isoformat(),
            "season": t.season, "location": t.get("location") or "", "online": bool(t.get("online")),
            "kind": t.get("kind") or "invitational", "level": t.get("level") or "standard",
            "subject_only": t.get("subject_only"), "status": t.get("status"), "notes": t.get("notes") or "",
            "n_teams": len(team_rows), "n_games": len(gl), "n_scored": sum(1 for g in gl if g.get("score1") is not None),
            "n_players": len(prow), "strength": _r(strength.get(tid)), "champion": champion,
            "rated": not t.get("subject_only") and not t.get("individual"),
            "individual": bool(t.get("individual")),
            "coverage": cov, "set": t.get("question_set"),
            "sources": [{"role": s.get("role"), "kind": s.get("kind"), "url": s.get("url")} for s in t.sources if s.get("url")],
        }
        if competitors is not None:
            # 1v1 events have no team entries: count the competitors and their games instead
            meta.update(n_competitors=len(competitors["rows"]), n_games=competitors["n_games"],
                        n_scored=competitors["n_scored"], champion_name=competitors["champion"],
                        champion_player=pid_by_raw.get((tid, competitors["champion"])))
        tournaments_out.append(meta)
        _write(f"tournaments/{tid}.json", {
            **meta,
            **({"competitors": competitors["rows"]} if competitors is not None else {}),
            "teams": team_rows,
            "games": [{"id": g["game_id"], "st": g["stage"], "rd": g["round"], "seq": g["seq"], "t1": g["team1"], "t2": g["team2"],
                       "s1": g.get("score1"), "s2": g.get("score2"), "res": g["result"], "p1": _r(g.get("p1"), 3),
                       "ff": bool(g.get("forfeit")), "pre1": _r(g.get("pre1")), "pre2": _r(g.get("pre2"))} for g in gl],
            "players": sorted(prow.values(), key=lambda x: -((x["s"].get("overall") or {}).get("pts") or 0)),
        })
    # tournaments that exist in the registry but have no parsed data (listed for completeness)
    for t in registry.all_tournaments(include_excluded=False):
        if t.id not in tourns:
            tournaments_out.append({"id": t.id, "name": t.name, "date": t.date.isoformat(), "end": t.end_date.isoformat(),
                                    "season": t.season, "location": t.get("location") or "", "online": bool(t.get("online")),
                                    "kind": t.get("kind") or "invitational", "level": t.get("level") or "standard",
                                    "subject_only": t.get("subject_only"), "status": t.get("status") or "unavailable",
                                    "notes": t.get("notes") or "", "n_teams": 0, "n_games": 0, "n_scored": 0, "n_players": 0,
                                    "strength": None, "champion": None, "rated": False, "coverage": {}, "set": t.get("question_set"),
                                    "sources": [{"role": s.get("role"), "kind": s.get("kind"), "url": s.get("url")} for s in t.sources if s.get("url")],
                                    "no_data": True})
    tournaments_out.sort(key=lambda x: (x["end"], x["id"]), reverse=True)
    _write("tournaments.json", tournaments_out)

    # ------------------------------------------------------------------ teams
    st = gres["teams"]
    last_by_team: dict[str, str] = {}
    first_by_team: dict[str, str] = {}
    seasons_by_team: dict[str, set[str]] = defaultdict(set)
    for e in res["entries"]:
        d = tdate[e["tournament_id"]]
        tm = e["team_id"]
        last_by_team[tm] = max(last_by_team.get(tm, d), d)
        first_by_team[tm] = min(first_by_team.get(tm, d), d)
        seasons_by_team[tm].add(tourns[e["tournament_id"]].season)
    active_cut = (snapshot - dt.timedelta(days=ACTIVE_DAYS)).isoformat()
    ranked_teams = [(tm, s.r) for tm, s in st.items() if s.rd <= RANKED_RD and last_by_team.get(tm, "") >= active_cut]
    team_rank = _rank(ranked_teams)
    team_rank_all = _rank([(tm, s.r) for tm, s in st.items()])
    subj_rank = {}
    for subj, m in team_models.items():
        ents = m["entities"]
        subj_rank[subj] = _rank([(e, v["rating"]) for e, v in ents.items()
                                 if v["eff_weight"] >= PLAYER_MIN_WEIGHT[subj] and _date(v["last_day"]) >= active_cut])
    teams_out = []
    team_details: dict[int, dict[str, Any]] = defaultdict(dict)
    hist = gres["history"]
    games_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tid, gl in games_by_t.items():
        for g in gl:
            for me, opp, sm, so, p in (("team1", "team2", "score1", "score2", g.get("p1")),
                                       ("team2", "team1", "score2", "score1", None if g.get("p1") is None else 1 - g["p1"])):
                res_ = "T" if g["result"] == "T" else ("W" if (g["result"] == "1") == (me == "team1") else "L")
                games_by_team[g[me]].append({"t": tid, "d": tdate[tid], "seq": g["seq"], "st": g["stage"], "rd": g["round"],
                                             "o": g[opp], "s": g.get(sm), "os": g.get(so), "r": res_, "p": _r(p, 3),
                                             "ff": bool(g.get("forfeit"))})
    rows_by_team: dict[str, list[tuple[tuple[str, str, str], dict[str, Any]]]] = defaultdict(list)
    for k, r in rows.items():
        if r["team_id"]:
            rows_by_team[r["team_id"]].append((k, r))
    for tm, info in teams.items():
        s = st.get(tm)
        h = hist.get(tm, [])
        subj = {}
        for sj, m in team_models.items():
            v = m["entities"].get(tm)
            if v:
                subj[sj] = {"r": _r(v["rating"]), "se": _r(v["se"]), "rank": subj_rank[sj].get(tm), "n": round(v["eff_weight"])}
        sch = schools[info["school_id"]]
        row = {
            "id": tm, "name": info["name"], "school": info["school_id"], "school_name": sch["name"], "state": sch["state"],
            "composite": info["composite"], "letter": info["letter"],
            "affiliate": sch.get("affiliate"),
            "r": _r(s.r) if s else None, "rd": _r(s.rd) if s else None,
            "rank": team_rank.get(tm), "rank_all": team_rank_all.get(tm) if s else None,
            "g": s.games if s else 0, "w": s.wins if s else 0, "l": s.losses if s else 0, "t": s.ties if s else 0,
            "first": first_by_team.get(tm), "last": last_by_team.get(tm), "seasons": sorted(seasons_by_team[tm]),
            "n_t": len(team_tourn_summary[tm]), "peak": _r(max((x["r"] for x in h), default=None)),
            "trend": [x["r"] for x in h[-12:]], "subj": subj,
        }
        teams_out.append(row)
        team_details[shard_of(tm)][tm] = {
            "history": h,
            "games": sorted(games_by_team[tm], key=lambda x: (x["d"], x["t"], x["seq"])),
            "tournaments": sorted(team_tourn_summary[tm], key=lambda x: x["d"]),
            "roster": {season: sorted(p) for season, p in sorted(roster[tm].items())},
            "coverage": _team_coverage(rows_by_team.get(tm, []), tourns),
            "subj_history": {sj: [{"d": _date(x["day"]), "r": x["rating"], "se": x["se"]}
                                  for x in m["history"].get(tm, [])] for sj, m in team_models.items() if m["history"].get(tm)},
        }
    # ties in the rounded rating keep the order of the unrounded one (so ranks read 1, 2, 3...)
    teams_out.sort(key=lambda x: (x["r"] is None, -(x["r"] or 0), x["rank_all"] or 0))
    _write("teams.json", teams_out)
    for sh, d in team_details.items():
        _write(f"teams/{sh}.json", d)

    # ------------------------------------------------------------------ schools
    nsb = _load_ref("nsb_finishes.yaml") or {}
    nsb_by_school = _nsb_by_school(nsb, res)
    teams_by_school: dict[str, list[str]] = defaultdict(list)
    affiliated: dict[str, list[str]] = defaultdict(list)
    for tm, info in teams.items():
        teams_by_school[info["school_id"]].append(tm)
        aff = schools[info["school_id"]].get("affiliate")
        if aff:
            affiliated[aff].append(tm)
    schools_out = []
    for sid, sch in schools.items():
        tms = sorted(teams_by_school[sid])
        rated = [st[t].r for t in tms if t in st]
        schools_out.append({**sch, "teams": tms, "pickup_teams": sorted(affiliated.get(sid, [])),
                            "best": _r(max(rated)) if rated else None,
                            "nsb": nsb_by_school.get(sid, [])})
    schools_out.sort(key=lambda x: (x["best"] is None, -(x["best"] or 0)))
    _write("schools.json", schools_out)

    # ------------------------------------------------------------------ players
    pm = player_models
    p_rank = {}
    for subj, m in pm.items():
        p_rank[subj] = _rank([(e, v["rating"]) for e, v in m["entities"].items()
                              if v["eff_weight"] >= PLAYER_MIN_WEIGHT[subj] and v["tournaments"] >= PLAYER_MIN_TOURNAMENTS
                              and _date(v["last_day"]) >= active_cut])
    rows_by_p: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (tid, pid, subj), r in rows.items():
        rows_by_p[pid].append(r)
    teammates: dict[str, Counter[str]] = defaultdict(Counter)
    team_t_players: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (tid, pid, subj), r in rows.items():
        if r["team_id"]:
            team_t_players[(tid, r["team_id"])].add(pid)
    for (tid, tm), ps in team_t_players.items():
        for a in ps:
            for b in ps:
                if a != b:
                    teammates[a][b] += 1
    players_out = []
    player_details: dict[int, dict[str, Any]] = defaultdict(dict)
    for pid, p in players.items():
        prs = rows_by_p.get(pid, [])
        ov = [r for r in prs if r["subject"] == "overall"]
        tids = sorted({r["tournament_id"] for r in prs}, key=lambda x: tdate[x])
        tot_pts = sum(r["est_points"] or 0 for r in ov if not tourns[r["tournament_id"]].get("subject_only"))
        tot_gp = sum(r["est_gp"] or 0 for r in ov if not tourns[r["tournament_id"]].get("subject_only") and r["est_points"] is not None)
        tot_tuh = sum(r["tuh"] or 0 for r in ov if r["tuh"] and not tourns[r["tournament_id"]].get("subject_only"))
        tot_pts_tuh = sum(r["points"] or 0 for r in ov if r["tuh"] and r["points"] is not None and not tourns[r["tournament_id"]].get("subject_only"))
        subj = {}
        for sj, m in pm.items():
            v = m["entities"].get(pid)
            if v:
                subj[sj] = {"r": _r(v["rating"]), "se": _r(v["se"]), "rank": p_rank[sj].get(pid), "n": round(v["eff_weight"]),
                            "pts": _r(sum(r["est_points"] or 0 for r in prs if r["subject"] == sj), 0)}
        o = subj.get("overall")
        best_subject = max(((sj, v["r"]) for sj, v in subj.items() if sj != "overall" and v["n"] >= 8),
                           key=lambda kv: kv[1], default=(None, None))[0]
        team_ids = sorted({r["team_id"] for r in prs if r["team_id"]})
        sch = schools.get(p.get("school_id")) if p.get("school_id") else None
        last = tdate[tids[-1]] if tids else None
        hist_all = pm["overall"]["history"].get(pid, [])
        players_out.append({
            "id": pid, "name": p["name"], "school": p.get("school_id"), "school_name": sch["name"] if sch else None,
            "state": sch["state"] if sch else None, "teams": team_ids,
            "r": o["r"] if o else None, "se": o["se"] if o else None, "rank": o["rank"] if o else None,
            "n_t": len(tids), "gp": _r(tot_gp, 0), "pts": _r(tot_pts, 0), "ppg": _r(tot_pts / tot_gp) if tot_gp else None,
            "ptuh": _r(tot_pts_tuh / tot_tuh, 3) if tot_tuh else None, "first": tdate[tids[0]] if tids else None, "last": last,
            "best": best_subject, "peak": _r(max((x["rating"] for x in hist_all), default=None)),
            "trend": [_r(x["rating"]) for x in hist_all[-12:]],
            "subj": {k: v for k, v in subj.items() if k != "overall"},
            "aliases": p.get("aliases", []),
        })
        stats = defaultdict(lambda: {"s": {}})
        for r in prs:
            k = (r["tournament_id"], r["team_id"])
            e = stats[k]
            e["t"], e["d"], e["tm"], e["scope"] = r["tournament_id"], tdate[r["tournament_id"]], r["team_id"], r["scope"]
            e["s"][r["subject"]] = {kk: _r(vv, 2) for kk, vv in (
                ("gp", r["gp"] if r["gp"] is not None else r["est_gp"]), ("tuh", r["tuh"]), ("c", r["correct"]),
                ("n", r["negs"]), ("pts", r["points"] if r["points"] is not None else r["est_points"]), ("ppg", r["ppg"])) if vv is not None}
        player_details[shard_of(pid)][pid] = {
            "history": {sj: [{"d": _date(x["day"]), "r": x["rating"], "se": x["se"]} for x in m["history"].get(pid, [])]
                        for sj, m in pm.items() if m["history"].get(pid)},
            "stats": sorted(stats.values(), key=lambda x: x["d"]),
            "teammates": [b for b, _ in teammates[pid].most_common(12)],
        }
    raw_overall = pm["overall"]["entities"]
    players_out.sort(key=lambda x: (x["r"] is None, -(x["r"] or 0),
                                    -raw_overall[x["id"]]["rating"] if x["id"] in raw_overall else 0))
    _write("players.json", players_out)
    for sh, d in player_details.items():
        _write(f"players/{sh}.json", d)

    # ------------------------------------------------------------------ nationals + meta
    winners = _norm_winners(_load_ref("nsb_winners.yaml") or [], schools)
    _write("nationals.json", {"winners": winners, "finishes": _link_finishes(nsb, res),
                              "tournaments": [t["id"] for t in tournaments_out if t.get("kind") == "nationals"]})
    counts = {"tournaments": sum(1 for t in tournaments_out if not t.get("no_data")),
              "tournaments_listed": len(tournaments_out), "games": len(res["games"]),
              "scored_games": sum(1 for g in res["games"] if g["score1"] is not None),
              "teams": len(teams), "schools": len(schools), "players": len(players),
              "player_stat_rows": len(res["player_stats"])}
    _write("meta.json", {
        "generated": dt.date.today().isoformat(), "snapshot": snapshot.isoformat(),
        "counts": counts, "seasons": sorted({t.season for t in tourns.values()}, reverse=True),
        "subjects": [{"key": k, "label": SUBJECT_LABELS[k]} for k in SUBJECTS],
        "glicko": {k: v for k, v in vars(gparams).items()}, "glicko_metrics": gres["metrics"],
        "stats_model": {sj: {"beta": _r(m["beta"], 3), "spread": _r(m["spread"], 4)} for sj, m in pm.items()},
        "thresholds": {"ranked_rd": RANKED_RD, "active_days": ACTIVE_DAYS, "player_min_tuh": PLAYER_MIN_WEIGHT,
                       "player_min_tournaments": PLAYER_MIN_TOURNAMENTS},
        "n_shards": N_SHARDS,
    })
    print(f"exported: {counts}")


_CONSOLATION = re.compile(r"3rd|third|bronze|consolation|\bplace\b|placement", re.I)


def _champion(gl: list[dict[str, Any]]) -> str | None:
    """Winner of the final playoff game, or None when the final is not in the data.

    Forfeit-flagged games count here (their winner still advanced). Third-place / consolation
    games are ignored. The result is rejected (None) when the last playoff round holds games
    between different pairs of teams (the final was not recorded) or when another playoff team finished with fewer
    playoff losses than the would-be champion (e.g. a double-elimination final with no result,
    where the last recorded game is the losers' bracket final)."""
    po = [g for g in gl if g["stage"] == "playoff" and g["result"] in ("1", "2", "T")
          and not _CONSOLATION.search(str(g.get("round") or ""))]
    if not po:
        return None
    top = max(g["seq"] for g in po)
    finals = [g for g in po if g["seq"] == top]
    # one final, or a series between the same two teams (finals played twice, best of three)
    if len({frozenset((g["team1"], g["team2"])) for g in finals}) != 1:
        return None
    last = max(finals, key=lambda g: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", str(g["game_id"]))])
    if last["result"] not in ("1", "2"):
        return None
    champ = last["team1"] if last["result"] == "1" else last["team2"]
    losses: Counter[str] = Counter()
    teams: set[str] = set()
    for g in po:
        teams.update((g["team1"], g["team2"]))
        if g["result"] == "1":
            losses[g["team2"]] += 1
        elif g["result"] == "2":
            losses[g["team1"]] += 1
    if any(losses[t] < losses[champ] for t in teams if t != champ):
        return None
    return champ


def _individual_standings(tid: str, pid_by_raw: dict[tuple[str, str], str]) -> dict[str, Any]:
    """Standings of a 1v1 event from its parsed games (each competitor is a one-person "team").

    Same rules as team standings: forfeit-flagged games are left out of the records; the champion
    is the winner of the final playoff game (see _champion). ``p`` is the competitor's player id
    when the event published player stats under the same name, else null."""
    from .schema import load_parsed
    d = load_parsed(tid)
    num = lambda x: None if x in (None, "") else float(x)  # noqa: E731
    games = [{**g, "seq": int(g["seq"] or 0), "score1": num(g.get("score1")), "score2": num(g.get("score2")),
              "forfeit": g.get("forfeit") in ("1", "true", "True")} for g in d["games"]]
    rec: dict[str, dict[str, float]] = {}
    for tr in d["teams"]:
        rec.setdefault(tr["team"], {"w": 0, "l": 0, "t": 0, "g": 0, "pf": 0.0, "pa": 0.0, "gs": 0})
    for g in games:
        if g["forfeit"]:
            continue
        for me, sm, so in (("team1", "score1", "score2"), ("team2", "score2", "score1")):
            r = rec.setdefault(g[me], {"w": 0, "l": 0, "t": 0, "g": 0, "pf": 0.0, "pa": 0.0, "gs": 0})
            r["g"] += 1
            if g["result"] == "T":
                r["t"] += 1
            elif (g["result"] == "1") == (me == "team1"):
                r["w"] += 1
            else:
                r["l"] += 1
            if g[sm] is not None and g[so] is not None:
                r["pf"] += g[sm]
                r["pa"] += g[so]
                r["gs"] += 1
    champ = _champion(games)
    rows = [{"name": name, "p": pid_by_raw.get((tid, name)), "w": r["w"], "l": r["l"], "t": r["t"], "g": r["g"],
             "ppg": _r(r["pf"] / r["gs"]) if r["gs"] else None, "papg": _r(r["pa"] / r["gs"]) if r["gs"] else None,
             "champ": name == champ} for name, r in rec.items()]
    rows.sort(key=lambda x: (-(x["w"] + 0.5 * x["t"]), x["l"], -(x["ppg"] or -999), x["name"]))
    return {"rows": rows, "n_games": len(games), "n_scored": sum(1 for g in games if g["score1"] is not None),
            "champion": champ}


def _coverage(tid: str) -> dict[str, Any]:
    from .config import PARSED_DIR
    p = PARSED_DIR / tid / "meta.json"
    return json.loads(p.read_text()).get("coverage", {}) if p.exists() else {}


def _load_ref(name: str) -> Any:
    p = REFERENCE_DIR / name
    return yaml.safe_load(p.read_text()) if p.exists() else None


def _nsb_by_school(nsb: dict[str, Any], res: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Map NSB finishes (by team name) to school ids via the resolved Nationals entries."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    raw_to_school = {}
    for e in res["entries"]:
        if "nsb-national-finals" in e["tournament_id"]:
            raw_to_school[(e["tournament_id"][:4], e["raw_name"])] = res["teams"][e["team_id"]]["school_id"]
    for year, items in (nsb or {}).items():
        for it in items or []:
            sid = raw_to_school.get((str(year), it.get("team")))
            if sid:
                out[sid].append({"year": int(year), "finish": it.get("finish")})
    return out


def _team_coverage(team_rows: list[tuple[tuple[str, str, str], dict[str, Any]]],
                   tourns: dict[str, registry.Tournament]) -> dict[str, Any] | None:
    """Roster x subject tossup points for the team's latest season with per-subject player stats.

    ``team_rows`` are the team's (tournament, player, subject) stat rows. Single-subject events
    are left out (they would swamp one column)."""
    by_season: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    subj_seasons: set[str] = set()
    for (tid, pid, subj), r in team_rows:
        if tourns[tid].get("subject_only"):
            continue
        season = tourns[tid].season
        e = by_season[season].setdefault(pid, {"p": pid, "gp": 0.0, "tids": set(), "pts": {}})
        pts = r["points"] if r["points"] is not None else r["est_points"]
        if pts is not None:
            e["pts"][subj] = e["pts"].get(subj, 0.0) + pts
        if subj == "overall":
            e["gp"] += (r["gp"] if r["gp"] is not None else r["est_gp"]) or 0
            e["tids"].add(tid)
        elif subj in SUBJECTS:
            subj_seasons.add(season)
    if not subj_seasons:
        return None
    season = max(subj_seasons)
    players = []
    for e in by_season[season].values():
        players.append({"p": e["p"], "gp": _r(e["gp"], 0), "n_t": len(e["tids"]),
                        "pts": {k: _r(v, 0) for k, v in e["pts"].items() if k in ("overall", *SUBJECTS)}})
    players.sort(key=lambda x: -(x["pts"].get("overall") or sum(x["pts"].values())))
    return {"season": season, "players": players}


def _norm_name(x: Any) -> str:
    import re
    s = str(x or "").lower().replace("&", "and")
    s = re.sub(r"\b(high school|high|school|hs|academy|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _norm_winners(winners: list[dict[str, Any]], schools: dict[str, Any]) -> list[dict[str, Any]]:
    """Pass the reference list through, adding `school` (a school id) when the champion's name
    matches a known school exactly after light normalisation and, when both give one, the state agrees
    (the 1998 champion Valley High School of West Des Moines, IA is not Valley High School, OH)."""
    by_name: dict[str, list[str]] = {}
    for sid, sch in schools.items():
        if sch.get("composite"):
            continue
        for nm in (sch.get("name"), sch.get("short")):
            if nm and sid not in by_name.get(_norm_name(nm), []):
                by_name.setdefault(_norm_name(nm), []).append(sid)
    out = []
    for w in winners or []:
        if not isinstance(w, dict):
            continue
        w = dict(w)
        champ = w.get("champion") or w.get("winner") or w.get("school") or w.get("team")
        champ = champ if isinstance(champ, str) else None
        st = str(w.get("state") or "").upper()
        cands = [s for s in by_name.get(_norm_name(champ), [])
                 if not st or not schools[s].get("state") or str(schools[s]["state"]).upper() == st] if champ else []
        sid = cands[0] if cands else None
        if sid and "school_id" not in w:
            w["school_id"] = sid
        out.append(w)
    out.sort(key=lambda w: -int(w.get("year") or 0))
    return out


def _link_finishes(nsb: dict[str, Any], res: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Add `tm` (team id) and `school_id` to NSB finishes when the Nationals entry resolves."""
    raw_to_team = {}
    for e in res["entries"]:
        if "nsb-national-finals" in e["tournament_id"]:
            raw_to_team[(e["tournament_id"][:4], e["raw_name"])] = e["team_id"]
    out: dict[str, list[dict[str, Any]]] = {}
    for year, items in (nsb or {}).items():
        lst = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            it = dict(it)
            tm = raw_to_team.get((str(year), it.get("team")))
            if tm:
                it["tm"] = tm
                it["school_id"] = res["teams"][tm]["school_id"]
            lst.append(it)
        out[str(year)] = lst
    return out
