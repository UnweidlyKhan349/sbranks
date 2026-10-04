import datetime as dt
import math

import numpy as np

from pipeline.ratings import glicko, statsmodel


def _period(i, games, season="2024-25", kind="invitational", level="standard"):
    return {"id": f"t{i}", "date": dt.date(2024, 10, 1) + dt.timedelta(days=7 * i), "season": season,
            "level": level, "kind": kind, "games": games}


def _g(a, b, s1, s2):
    return {"team1": a, "team2": b, "score1": s1, "score2": s2,
            "result": "1" if s1 > s2 else "2" if s2 > s1 else "T", "game_id": f"{a}-{b}", "seq": 0}


META = {t: {"school_id": t, "letter": "A", "composite": False} for t in "ABCD"}


def test_glicko2_reference_example():
    """Glickman's worked example: 1500/200 vs 1400/30 (W), 1550/100 (L), 1700/300 (L) -> 1464.06/151.52."""
    p = glicko.GlickoParams(mov_weight=0.0, init_rd=200.0, rd_per_year=0.0, min_rd=1.0)
    meta = {t: {"school_id": t, "letter": "A"} for t in "PXYZ"}
    seeded = {}
    for t, (r, rd) in {"X": (1400, 30), "Y": (1550, 100), "Z": (1700, 300)}.items():
        seeded[t] = glicko.TeamState(r, rd, last_date=dt.date(2024, 10, 1), season="2024-25", prior=r)
    per = _period(0, [_g("P", "X", 1, 0), _g("P", "Y", 0, 1), _g("P", "Z", 0, 1)])
    out = glicko.run([per], meta, p, initial=seeded)
    P = out["teams"]["P"]
    assert abs(P.r - 1464.06) < 0.1, P.r
    assert abs(P.rd - 151.52) < 0.1, P.rd


def test_stronger_team_rises():
    periods = [_period(i, [_g("A", "B", 200, 50), _g("A", "C", 180, 60), _g("B", "C", 120, 100),
                           _g("A", "D", 220, 20), _g("B", "D", 150, 80), _g("C", "D", 130, 90)]) for i in range(4)]
    out = glicko.run(periods, META)
    r = {t: s.r for t, s in out["teams"].items()}
    assert r["A"] > r["B"] > r["C"] > r["D"]
    assert out["metrics"]["accuracy"] > 0.9
    assert all(s.rd < 200 for s in out["teams"].values())


def test_margin_matters_only_with_mov_weight():
    close = [_period(0, [_g("A", "B", 101, 100)])]
    blow = [_period(0, [_g("A", "B", 300, 0)])]
    p0 = glicko.GlickoParams(mov_weight=0.0)
    assert abs(glicko.run(close, META, p0)["teams"]["A"].r - glicko.run(blow, META, p0)["teams"]["A"].r) < 1e-9
    p1 = glicko.GlickoParams(mov_weight=0.5)
    assert glicko.run(blow, META, p1)["teams"]["A"].r > glicko.run(close, META, p1)["teams"]["A"].r


def test_b_team_prior_below_sibling():
    meta = {"A": {"school_id": "s", "letter": "A"}, "B": {"school_id": "s", "letter": "B"},
            "X": {"school_id": "x", "letter": "A"}}
    periods = [_period(0, [_g("A", "X", 200, 50)]), _period(1, [_g("B", "X", 100, 100)])]
    out = glicko.run(periods, meta)
    assert out["teams"]["B"].prior < out["teams"]["A"].r


def test_season_regression_pulls_toward_prior():
    p = glicko.GlickoParams(season_regress=0.5, rd_per_year=0.0)
    periods = [_period(i, [_g("A", "B", 250, 20)]) for i in range(5)]
    out1 = glicko.run(periods, META, p)
    rA = out1["teams"]["A"].r
    periods2 = periods + [_period(60, [_g("C", "D", 100, 90)], season="2025-26"),
                          _period(61, [_g("A", "B", 100, 100)], season="2025-26")]
    out2 = glicko.run(periods2, META, p)
    pre = [h for h in out2["history"]["A"] if h["tournament_id"] == "t61"][0]["pre"]
    assert abs(pre - (rA + 0.5 * (1500 - rA))) < 1.0


def test_win_prob_symmetry():
    assert abs(glicko.win_prob(1600, 80, 1500, 80) + glicko.win_prob(1500, 80, 1600, 80) - 1) < 1e-12
    assert glicko.win_prob(1700, 50, 1500, 50) > glicko.win_prob(1700, 300, 1500, 300) > 0.5


def test_statsmodel_recovers_order_and_difficulty():
    rng = np.random.default_rng(0)
    true = {f"p{i}": 0.2 * i for i in range(10)}
    tourns = [{"id": f"t{j}", "end_day": 738000 + 10 * j, "field_strength": None} for j in range(6)]
    diff = {f"t{j}": (0.5 if j % 2 else -0.3) for j in range(6)}
    rows = []
    for j in range(6):
        for i in range(10):
            if (i + j) % 3 == 0:
                continue
            tuh = 80
            y = true[f"p{i}"] - diff[f"t{j}"] + rng.normal(0, 1.5 / math.sqrt(tuh))
            rows.append({"entity": f"p{i}", "tournament_id": f"t{j}", "y": y, "w": tuh})
    out = statsmodel.run_model(rows, tourns, statsmodel.ModelParams(k_theta=5, k_delta=20), [738050])
    ratings = [out["entities"][f"p{i}"]["rating"] for i in range(10)]
    assert np.corrcoef(ratings, list(true.values()))[0, 1] > 0.97
    hard = np.mean([out["delta"][f"t{j}"] for j in range(6) if j % 2])
    easy = np.mean([out["delta"][f"t{j}"] for j in range(6) if not j % 2])
    assert hard > easy + 0.5


def test_statsmodel_shrinks_small_samples():
    tourns = [{"id": "t0", "end_day": 738000, "field_strength": None}]
    rows = [{"entity": "big", "tournament_id": "t0", "y": 2.0, "w": 400},
            {"entity": "small", "tournament_id": "t0", "y": 2.0, "w": 5}]
    rows += [{"entity": f"x{i}", "tournament_id": "t0", "y": 0.0, "w": 100} for i in range(10)]
    out = statsmodel.run_model(rows, tourns, statsmodel.ModelParams(), [738000], history=False)
    assert out["entities"]["big"]["rating"] > out["entities"]["small"]["rating"]
    assert out["entities"]["small"]["se"] > out["entities"]["big"]["se"]
