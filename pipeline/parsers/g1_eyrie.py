"""Eyrie tournament hub (eyrieshub.fly.dev), used by AVES 2.

Raw files (raw/<id>/):
    rrscores.html        RR grids per pool (row team's score, cell links to /game/<n>)
    results.html         DE bracket (/debracket) match cards: code (WB_R1_1, LB_R3_2, CHAMP_1),
                         game number, both teams + scores, winner flag
    sebracket.html       SE bracket for places 17-32 (codes SE_R1_1 ...)
    schedule.xlsx        organiser's schedule sheet (linked from /schedule): "RR Schedule" gives
                         the round of every RR pairing
    eyrie/games/<n>.html scoresheet per game; embeds ``let questions = [...]`` (per tossup:
                         category B/M/C/E/P, {player id: 4|0|-4} per side, bonus_a/bonus_b 10|0)
                         and the rosters ``teamAPlayers`` / ``teamBPlayers``
    eyrie/players/<uid>.html  player page: full name, team and RR-only totals per category
                         (PPG, NPG, Total Points, Halves Played)
    (fetched by pipeline/parsers/tools/g1_fetch_eyrie.py)

Scoring: tossup +4, neg -4 to the negging team, bonus +10; recomputed game scores match the
RR grid and bracket cards exactly. Category E is Earth & Space (the site's stats say "ESS").

Player stats: scope ``rr`` reproduces the site's player pages exactly (points per category
recomputed from the scoresheets, plus 4s/0s/-4s); gp = halves played / 2 and tuh = 10 per half
(2 per category per half - each half cycles B,M,C,E,P twice). Scope ``playoff`` comes from the
DE/SE scoresheets; gp = playoff games on the roster; tuh only when every one of the player's
playoff games had at most 4 rostered players on that side (or participation was recorded).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name
from ..util.grid import load_grids

CATS = {"B": "biology", "M": "math", "C": "chemistry", "E": "ess", "P": "physics", "EN": "energy"}


def _soup(p: Path) -> BeautifulSoup:
    return BeautifulSoup(p.read_text(encoding="utf-8"), "lxml")


def _load_game(p: Path) -> dict | None:
    if not p.exists():
        return None
    h = p.read_text(encoding="utf-8")
    m = re.search(r"let questions = (\[.*?\]);\n", h, re.S)
    if not m:
        return None
    ta = json.loads(re.search(r"const teamAPlayers = (\[.*?\]);", h).group(1))
    tb = json.loads(re.search(r"const teamBPlayers = (\[.*?\]);", h).group(1))
    pm = re.search(r"let participation = (.*?);\n", h)
    part = json.loads(pm.group(1)) if pm else {}
    title = BeautifulSoup(h, "lxml").find("h2").get_text(" ", strip=True)
    a, b = [clean_name(x) for x in title.split(" vs ", 1)]
    return {"questions": json.loads(m.group(1)), "a": a, "b": b, "roster_a": ta, "roster_b": tb,
            "participation": part}


def _score(g: dict) -> tuple[int, int]:
    sc = {"a": 0, "b": 0}
    for q in g["questions"]:
        for s in "ab":
            sc[s] += sum((q.get(f"team_{s}") or {}).values()) + (q.get(f"bonus_{s}") or 0)
    return sc["a"], sc["b"]


def _rr_grid(raw: Path) -> list[dict]:
    """[{pool, teams: [...], games: {gid: {team: score}}}]"""
    s = _soup(raw / "rrscores.html")
    pools = []
    for hdr in s.find_all("div", class_="group-header"):
        table = hdr.find_next("table")
        teams, games = [], {}
        for tr in table.find("tbody").find_all("tr"):
            name = clean_name(re.sub(r"^\s*\d+\.\s*", "", tr.find("td").get_text(" ", strip=True)))
            teams.append(name)
            for a in tr.find_all("a", class_="score-link"):
                v = a.get_text(strip=True)
                gid = int(a["href"].rsplit("/", 1)[-1])
                games.setdefault(gid, {})[name] = None if v == "-" else int(v)
        pools.append({"pool": clean_name(hdr.get_text()), "teams": teams, "games": games})
    return pools


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _rr_rounds(raw: Path, schedule_file: str, pools: list[dict], w: TournamentWriter) -> dict[frozenset, int]:
    """{frozenset({teamA, teamB}): round} from the organiser's RR Schedule tab."""
    p = raw / schedule_file
    if not p.exists():
        return {}
    g = load_grids(p)["RR Schedule"]
    by_pool = {pl["pool"]: pl["teams"] for pl in pools}
    out: dict[frozenset, int] = {}
    for hr, hc in g.find(r"^Team 1$"):
        pool = g.text(hr - 1, hc)
        teams = by_pool.get(pool)
        if not teams:
            continue
        pairs, rnd = [], None
        r = hr + 1
        while r < g.nrows and (g.text(r, hc) or g.text(r, hc - 1)):
            m = re.match(r"Round (\d+)", g.text(r, 1))
            if m:
                rnd = int(m.group(1))
            if g.text(r, hc) and rnd:
                pairs.append((rnd, g.text(r, hc), g.text(r, hc + 1)))
            r += 1
        # map schedule names -> grid names (exact, normalised, prefix, then elimination)
        names = {x for _, a, b in pairs for x in (a, b)}
        mp: dict[str, str] = {}
        for n in names:
            cands = [t for t in teams if t == n] or [t for t in teams if _norm(t) == _norm(n)] or \
                    [t for t in teams if _norm(t).startswith(_norm(n)) or _norm(n).startswith(_norm(t))]
            if len(cands) == 1:
                mp[n] = cands[0]
        left_s = [n for n in names if n not in mp]
        left_t = [t for t in teams if t not in mp.values()]
        if len(left_s) == 1 and len(left_t) == 1:
            mp[left_s[0]] = left_t[0]
        for n in left_s:
            if n not in mp:
                w.warn(f"RR schedule: cannot map {n!r} in pool {pool}")
        for rnd, a, b in pairs:
            if a in mp and b in mp:
                out[frozenset((mp[a], mp[b]))] = rnd
    return out


def _bracket_cards(p: Path) -> list[dict]:
    if not p.exists():
        return []
    cards = []
    for card in _soup(p).find_all("div", class_="match-card"):
        code = card.find("div", class_="match-header").find("span").get_text(strip=True)
        a = card.find("a")
        rows = []
        for r in card.find_all("div", class_="team-row"):
            link = r.find("a")
            sc = r.find("span", class_="score-span")
            rows.append((clean_name(link.get_text(" ", strip=True)) if link else "",
                         sc.get_text(strip=True) if sc else "", "winner" in (r.get("class") or [])))
        cards.append({"code": code, "gid": int(a["href"].rsplit("/", 1)[-1]) if a else None, "rows": rows})
    return cards


def _round_label(code: str) -> str:
    m = re.match(r"^([A-Z]+)_R(\d+)_\d+$", code)
    if m:
        return f"{m.group(1)} R{m.group(2)}"
    if code.startswith("CHAMP"):
        return "Grand Final"
    return code


def _player_pages(raw: Path) -> dict[int, dict]:
    out = {}
    for p in (raw / "eyrie" / "players").glob("*.html"):
        s = _soup(p)
        h1 = s.find("h1", class_="user-name")
        role = s.find("div", class_="user-role")
        rows = {}
        for tr in s.find_all("tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) == 5:
                rows[tds[0]] = tds[1:]
        out[int(p.stem)] = {"name": clean_name(h1.get_text(" ", strip=True)) if h1 else "",
                            "team": clean_name(role.get_text(" ", strip=True)) if role else "",
                            "rows": rows}
    return out


def parse(t: Tournament, w: TournamentWriter, schedule_file: str = "schedule.xlsx",
          min_active_questions: int = 2) -> None:
    raw = t.raw_dir
    gdir = raw / "eyrie" / "games"
    pools = _rr_grid(raw)
    rounds = _rr_rounds(raw, schedule_file, pools, w)
    players = _player_pages(raw)

    games: list[tuple[int, dict]] = []  # (gid, info)
    for pl in pools:
        for gid, sc in sorted(pl["games"].items()):
            if len(sc) != 2:
                w.warn(f"RR game {gid}: {len(sc)} teams in grid")
                continue
            (ta, sa), (tb, sb) = sc.items()
            if sa is None or sb is None:
                w.warn(f"RR game {gid} {ta} vs {tb} not played (grid shows '-')")
                continue
            w.team(ta)
            w.team(tb)
            rnd = rounds.get(frozenset((ta, tb)))
            if rnd is None:
                w.warn(f"RR game {gid} {ta} vs {tb}: round not found in schedule")
            games.append((gid, {"stage": "rr", "round": f"RR{rnd}" if rnd else "", "seq": rnd or 1,
                                "teams": (ta, tb), "scores": (sa, sb), "pool": pl["pool"]}))

    po = []
    for fname, stage in (("results.html", "playoff"), ("sebracket.html", "consolation")):
        for c in _bracket_cards(raw / fname):
            if c["gid"] is None or len(c["rows"]) != 2:
                continue
            (ta, sa, wa), (tb, sb, wb) = c["rows"]
            po.append((c["gid"], {"stage": stage, "round": _round_label(c["code"]), "code": c["code"],
                                  "teams": (ta, tb), "scores": (int(sa), int(sb)),
                                  "winner": ta if wa else tb if wb else None}))
    first_gid: dict[tuple[str, str], int] = {}
    for gid, g in po:
        k = (g["stage"], g["round"])
        first_gid[k] = min(first_gid.get(k, gid), gid)
    seq_of = {k: 6 + i for i, k in enumerate(sorted(first_gid, key=first_gid.get))}
    for gid, g in po:
        g["seq"] = seq_of[(g["stage"], g["round"])]
    games += po

    # per-player accumulators keyed by (name, team): accounts with the same name on one team
    # are merged (the site lists a few players twice under two accounts).
    acc = {s: defaultdict(lambda: defaultdict(float)) for s in ("rr", "playoff")}
    po_games: dict[tuple[str, str], set[int]] = defaultdict(set)
    po_heard: dict[tuple[str, str], set[tuple[int, int]]] = defaultdict(set)
    po_unknown: set[tuple[str, str]] = set()
    rr_games_by_uid: dict[tuple[int, str], set[int]] = defaultdict(set)
    cat_of: dict[tuple[int, int], str] = {}

    for gid, g in sorted(games, key=lambda x: (x[1]["seq"], x[0])):
        page = _load_game(gdir / f"{gid}.html")
        ta, tb = g["teams"]
        sa, sb = g["scores"]
        notes, forfeit, short = [], False, False
        if page is None:
            w.warn(f"game {gid}: no scoresheet page")
        else:
            if (page["a"], page["b"]) != (ta, tb):
                if (page["b"], page["a"]) == (ta, tb):
                    page = {**page, "a": page["b"], "b": page["a"], "roster_a": page["roster_b"],
                            "roster_b": page["roster_a"], "questions": [
                                {**q, "team_a": q.get("team_b"), "team_b": q.get("team_a"),
                                 "bonus_a": q.get("bonus_b"), "bonus_b": q.get("bonus_a")}
                                for q in page["questions"]]}
                else:
                    w.warn(f"game {gid}: page teams {page['a']}/{page['b']} != {ta}/{tb}")
            if _score(page) != (sa, sb):
                w.warn(f"game {gid}: scoresheet {_score(page)} != listed {sa}-{sb}")
            active = sum(1 for q in page["questions"] if q.get("team_a") or q.get("team_b"))
            empty = [x for x, r in ((ta, page["roster_a"]), (tb, page["roster_b"])) if not r]
            if empty:
                forfeit = True
                notes.append(f"{', '.join(empty)} had no players on the scoresheet and scored 0; "
                             "treated as forfeit")
            elif active < min_active_questions:
                forfeit = short = True
                notes.append(f"only {active} tossup recorded ({sa}-{sb}); treated as forfeit")
            elif active < 12:
                notes.append(f"only {active} tossups with a buzz recorded (shortened game)")
        if g.get("winner") and sa == sb:
            notes.append(f"tied; bracket advanced {g['winner']}")
        elif g["stage"] != "rr" and sa == sb:
            later = {x for gid2, g2 in po if gid2 > gid and g2["stage"] == g["stage"] for x in g2["teams"]}
            adv = [x for x in (ta, tb) if x in later]
            notes.append(f"tied; bracket advanced {adv[0]}" if len(adv) == 1 else "tied")
        if g.get("pool"):
            notes.insert(0, f"pool {g['pool']}")
        gw = w.game(ta, tb, sa, sb, stage=g["stage"], round=g["round"], seq=g["seq"],
                    game_id=str(gid), forfeit=forfeit, notes="; ".join(notes))
        if page is None:
            continue
        scope = "rr" if g["stage"] == "rr" else "playoff"
        # RR player stats keep every game (they must match the site's RR totals and halves
        # played); 1-tossup playoff "games" are left out of the playoff player stats.
        count_players = not (scope == "playoff" and forfeit)
        side_team = {"a": ta, "b": tb}
        tgs = defaultdict(lambda: defaultdict(float))
        pgs = defaultdict(lambda: defaultdict(float))
        buzzed: dict[tuple[str, str], set[int]] = defaultdict(set)
        for i, q in enumerate(page["questions"]):
            subj = CATS.get(str(q.get("category", "")).upper(), "other")
            cat_of[(gid, i)] = subj
            for s in "ab":
                tg = tgs[(side_team[s], subj)]
                tg["bonus_points"] += q.get(f"bonus_{s}") or 0
                for u, v in (q.get(f"team_{s}") or {}).items():
                    k = {4: "correct", 0: "zeros", -4: "negs"}.get(v)
                    if k is None:
                        w.warn(f"game {gid}: odd tossup value {v}")
                        continue
                    tg["tossup_points"] += v
                    if k != "zeros":
                        tg[k] += 1
                    pk = (_pname(players, u), side_team[s])
                    for sj in ("overall", subj):
                        pgs[(*pk, sj)][k] += 1
                        if count_players:
                            acc[scope][(*pk, sj)][k] += 1
                    buzzed[pk].add(i)
        for (team, subj), v in sorted(tgs.items()):
            tp, bp = v.get("tossup_points", 0), v.get("bonus_points", 0)
            w.team_game_subject(gw, team, subj, tp + bp, tossup_points=tp, bonus_points=bp,
                                tossups_correct=v.get("correct", 0), negs=v.get("negs", 0))
        for (name, team, subj), v in pgs.items():
            w.player_game_stat(gw, name, team, subj, correct=v.get("correct", 0), negs=v.get("negs", 0))
        if not count_players:
            continue
        part = page.get("participation") or {}
        part_ok = all(part.get(h) for h in ("H1", "H2"))
        nq = len(page["questions"])
        for s in "ab":
            roster = page[f"roster_{s}"]
            for uid in roster:
                pk = (_pname(players, uid), side_team[s])
                if scope == "rr":
                    rr_games_by_uid[(uid, side_team[s])].add(gid)
                    continue
                po_games[pk].add(gid)
                if part_ok:
                    qs = {i for i in range(nq) if uid in part["H1" if i < 10 else "H2"]}
                elif len(roster) <= 4:
                    qs = set(range(nq))
                else:
                    po_unknown.add(pk)
                    continue
                po_heard[pk] |= {(gid, i) for i in qs | buzzed.get(pk, set())}

    # ---- RR rows (site player pages: halves played; points re-derived from scoresheets) ----
    uids_by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for uid, team in rr_games_by_uid:
        uids_by_key[(_pname(players, uid), team)].append(uid)
    for name, team in {(n, tm) for (n, tm, _) in acc["rr"]}:
        if (name, team) not in uids_by_key:
            w.warn(f"player {name} ({team}) buzzed in RR but is on no RR roster")
    for (name, team), uids in sorted(uids_by_key.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if len(uids) > 1:
            w.warn(f"merged {len(uids)} accounts named {name!r} on {team}")
        hps, site_pts = [], defaultdict(float)
        for uid in uids:
            pg = players.get(uid, {})
            rows = pg.get("rows", {})
            hps.append(_f(rows.get("Overall", [None] * 4)[3]))
            if pg.get("team") and pg["team"] != team:
                w.warn(f"player {name}: page team {pg['team']!r} != game team {team!r}")
            for lab, (ppg, npg, pts, hp) in rows.items():
                site_pts[lab] += _f(pts) or 0
        gsets = [rr_games_by_uid[(u, team)] for u in uids]
        overlap = len(set().union(*gsets)) < sum(len(x) for x in gsets)
        if any(h is None for h in hps):
            hp = None
        else:
            hp = max(hps) if overlap else sum(hps)
        gp = hp / 2 if hp is not None else len(set().union(*gsets))
        for subj, lab in (("overall", "Overall"), ("biology", "Biology"), ("math", "Math"),
                          ("chemistry", "Chemistry"), ("ess", "ESS"), ("physics", "Physics")):
            a = acc["rr"].get((name, team, subj), {})
            c, z, n = a.get("correct", 0), a.get("zeros", 0), a.get("negs", 0)
            pts = 4 * c - 4 * n
            if lab in site_pts and not overlap and site_pts[lab] != pts:
                w.warn(f"player {name} {subj}: site RR points {site_pts[lab]} != scoresheets {pts}")
            tuh = None if hp is None else hp * 10 if subj == "overall" else hp * 2
            w.player_stat(name, team, subj, scope="rr", gp=gp, tuh=tuh, correct=c, zeros=z,
                          negs=n, points=pts)

    # ---- playoff rows (DE + SE scoresheets) ----
    for name, team in sorted(po_games, key=lambda k: (k[1], k[0])):
        known = (name, team) not in po_unknown
        heard = defaultdict(float)
        for key in po_heard[(name, team)]:
            heard["overall"] += 1
            heard[cat_of[key]] += 1
        for subj in ("overall", "biology", "math", "chemistry", "ess", "physics"):
            a = acc["playoff"].get((name, team, subj), {})
            c, z, n = a.get("correct", 0), a.get("zeros", 0), a.get("negs", 0)
            w.player_stat(name, team, subj, scope="playoff", gp=len(po_games[(name, team)]),
                          tuh=heard.get(subj, 0) if known else None, correct=c, zeros=z, negs=n,
                          points=4 * c - 4 * n)


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pname(players: dict[int, dict], uid: int) -> str:
    p = players.get(int(uid))
    return p["name"] if p and p.get("name") else f"eyrie user {uid}"
