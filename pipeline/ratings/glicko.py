"""Team ratings: Glicko-2 over game results, shown on the Elo scale (1500 = average).

* Each tournament is one rating period (all its games use pre-tournament ratings).
* Outcome: ``s = (1 - mov_weight) * win + mov_weight * sigmoid(margin / mov_scale)`` when both
  scores are known, otherwise the plain win/tie/loss (e.g. NSB Nationals, Challonge).
* Rating deviation grows with time away (``rd_per_year``), not per period, because most
  teams skip most tournaments.
* At a team's first tournament of a new season its rating is pulled ``season_regress`` of the
  way back to its prior (rosters turn over).
* New teams start from a prior: 1500, minus ``letter_step`` per letter after A (B teams are
  usually weaker), adjusted by event level; a school's existing sibling team anchors the prior.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

SCALE = 173.7178


@dataclass
class GlickoParams:
    tau: float = 0.5
    init_rd: float = 300.0
    min_rd: float = 40.0
    max_rd: float = 350.0
    init_vol: float = 0.06
    rd_per_year: float = 120.0
    mov_weight: float = 0.5
    mov_scale: float = 80.0
    season_regress: float = 0.3
    letter_step: float = 100.0
    sibling_gap: float = 120.0
    level_offset: dict[str, float] = field(default_factory=lambda: {"novice": -150.0, "standard": 0.0, "advanced": 75.0})
    nationals_prior: float = 1600.0


@dataclass
class TeamState:
    r: float
    rd: float
    vol: float = 0.06
    last_date: Any = None
    season: str | None = None
    prior: float = 1500.0
    games: int = 0
    wins: float = 0
    losses: float = 0
    ties: float = 0


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi ** 2))


def win_prob(r1: float, rd1: float, r2: float, rd2: float) -> float:
    """P(team 1 beats team 2) from ratings and deviations (combined uncertainty)."""
    phi = math.sqrt(rd1 ** 2 + rd2 ** 2) / SCALE
    return 1.0 / (1.0 + math.exp(-_g(phi) * (r1 - r2) / SCALE))


def _new_vol(sigma: float, phi: float, v: float, delta: float, tau: float) -> float:
    a = math.log(sigma * sigma)
    eps = 1e-6

    def f(x: float) -> float:
        ex = math.exp(x)
        return (ex * (delta * delta - phi * phi - v - ex)) / (2 * (phi * phi + v + ex) ** 2) - (x - a) / (tau * tau)

    A = a
    if delta * delta > phi * phi + v:
        B = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau
    fA, fB = f(A), f(B)
    for _ in range(100):
        if abs(B - A) <= eps:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2
        B, fB = C, fC
    return math.exp(A / 2)


def outcome(g: dict[str, Any], p: GlickoParams) -> float:
    """Outcome for team1 in [0, 1]."""
    win = {"1": 1.0, "2": 0.0, "T": 0.5}[g["result"]]
    s1, s2 = g.get("score1"), g.get("score2")
    if s1 is None or s2 is None or p.mov_weight <= 0:
        return win
    soft = 1.0 / (1.0 + math.exp(-(s1 - s2) / p.mov_scale))
    return (1 - p.mov_weight) * win + p.mov_weight * soft


def run(periods: Iterable[dict[str, Any]], team_meta: dict[str, dict[str, Any]],
        p: GlickoParams | None = None, record: bool = True,
        initial: dict[str, TeamState] | None = None) -> dict[str, Any]:
    """Run Glicko-2 over periods.

    periods: chronological list of {id, date (datetime.date), season, level, kind, games:[{...,
             team1, team2, score1, score2, result}]}
    team_meta: team_id -> {school_id, letter}
    Returns {"teams": {id: TeamState}, "history": {id: [..]}, "games": [...], "metrics": {...}}
    """
    p = p or GlickoParams()
    st: dict[str, TeamState] = dict(initial or {})
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    game_log: list[dict[str, Any]] = []
    by_school: dict[str, list[str]] = defaultdict(list)
    ll_sum, ll_n, correct = 0.0, 0, 0

    for per in periods:
        games = [g for g in per["games"] if not g.get("forfeit")]
        if not games:
            continue
        teams = sorted({g["team1"] for g in games} | {g["team2"] for g in games})
        # --- bring every participant up to date (create / inflate RD / season regression)
        for t in teams:
            s = st.get(t)
            if s is None:
                prior = _prior(t, team_meta, per, st, by_school, p)
                s = st[t] = TeamState(r=prior, rd=p.init_rd, vol=p.init_vol, prior=prior)
                by_school[team_meta[t]["school_id"]].append(t)
            else:
                days = (per["date"] - s.last_date).days if s.last_date else 0
                s.rd = min(p.max_rd, math.sqrt(s.rd ** 2 + (p.rd_per_year ** 2) * max(days, 0) / 365.0))
                if s.season != per["season"]:
                    s.r = s.r + p.season_regress * (s.prior - s.r)
                    s.rd = min(p.max_rd, math.sqrt(s.rd ** 2 + (0.5 * p.rd_per_year) ** 2))
            s.season = per["season"]
        pre = {t: (st[t].r, st[t].rd) for t in teams}
        # --- predictions (for backtest metrics) with pre-period ratings
        for g in games:
            (r1, d1), (r2, d2) = pre[g["team1"]], pre[g["team2"]]
            pr = win_prob(r1, d1, r2, d2)
            if g["result"] in ("1", "2") and st[g["team1"]].games and st[g["team2"]].games:
                y = 1.0 if g["result"] == "1" else 0.0
                q = min(max(pr, 1e-6), 1 - 1e-6)
                ll_sum += -(y * math.log(q) + (1 - y) * math.log(1 - q))
                ll_n += 1
                correct += int((pr >= 0.5) == (y == 1.0))
            if record:
                game_log.append({**g, "tournament_id": per["id"], "pre1": r1, "pre_rd1": d1,
                                 "pre2": r2, "pre_rd2": d2, "p1": pr})
        # --- Glicko-2 update
        opp: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
        for g in games:
            s1 = outcome(g, p)
            opp[g["team1"]].append((pre[g["team2"]][0], pre[g["team2"]][1], s1))
            opp[g["team2"]].append((pre[g["team1"]][0], pre[g["team1"]][1], 1 - s1))
        delta_by_team: dict[str, float] = {}
        for t in teams:
            s = st[t]
            mu, phi = (s.r - 1500) / SCALE, s.rd / SCALE
            v_inv, dsum = 0.0, 0.0
            for (ro, rdo, sc) in opp[t]:
                muj, phij = (ro - 1500) / SCALE, rdo / SCALE
                gj = _g(phij)
                E = 1.0 / (1.0 + math.exp(-gj * (mu - muj)))
                v_inv += gj * gj * E * (1 - E)
                dsum += gj * (sc - E)
            v = 1.0 / v_inv
            delta = v * dsum
            sigma = _new_vol(s.vol, phi, v, delta, p.tau)
            phi_star = math.sqrt(phi * phi + sigma * sigma)
            phi_new = 1.0 / math.sqrt(1.0 / (phi_star ** 2) + 1.0 / v)
            mu_new = mu + phi_new * phi_new * dsum
            new_r = 1500 + SCALE * mu_new
            delta_by_team[t] = new_r - s.r
            s.r, s.rd, s.vol = new_r, max(p.min_rd, SCALE * phi_new), sigma
            s.last_date = per["date"]
        for g in games:
            res = g["result"]
            for t, me in ((g["team1"], "1"), (g["team2"], "2")):
                s = st[t]
                s.games += 1
                if res == "T":
                    s.ties += 1
                elif res == me:
                    s.wins += 1
                else:
                    s.losses += 1
        if record:
            for t in teams:
                history[t].append({"tournament_id": per["id"], "date": per["date"].isoformat(),
                                   "r": round(st[t].r, 1), "rd": round(st[t].rd, 1),
                                   "pre": round(pre[t][0], 1), "delta": round(delta_by_team[t], 1)})
    metrics = {"games_scored": ll_n, "log_loss": ll_sum / ll_n if ll_n else None,
               "accuracy": correct / ll_n if ll_n else None}
    return {"teams": st, "history": history, "games": game_log, "metrics": metrics}


def _prior(t: str, team_meta: dict[str, dict[str, Any]], per: dict[str, Any], st: dict[str, TeamState],
           by_school: dict[str, list[str]], p: GlickoParams) -> float:
    meta = team_meta[t]
    letter = meta.get("letter") or "A"
    li = max(0, "ABCDEFGH".find(letter))
    sibs = [s for s in by_school.get(meta["school_id"], []) if s in st]
    if sibs and not meta.get("composite"):
        best = max(sibs, key=lambda s: st[s].r)
        bl = max(0, "ABCDEFGH".find(team_meta[best].get("letter") or "A"))
        return st[best].r - p.sibling_gap * (li - bl)
    base = p.nationals_prior if per.get("kind") == "nationals" else 1500.0
    return base - p.letter_step * li + p.level_offset.get(per.get("level") or "standard", 0.0)
