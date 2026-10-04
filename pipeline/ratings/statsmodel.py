"""Elo-scaled ratings from tossup statistics (players, and teams per subject).

Players never play one-on-one, so their rating comes from *how much they score, given how
hard it was to score*. For every (entity, tournament, subject) we observe

    y = tossup points per tossup heard in that subject     (weight w = tossups heard)

and fit a weighted fixed-effects model

    y[e, t] = theta[e] - delta[t] + noise

* ``theta[e]`` — the entity's ability (points per tossup heard against an average field/set);
* ``delta[t]`` — how hard tournament t was to score at (question difficulty + field strength).
  Tournaments are linked through players who attend several of them; a weak prior ties
  ``delta`` to the tournament's field strength from the team (Glicko) ratings, which keeps
  isolated events (e.g. novice divisions) honest.

Both sets of parameters get ridge priors (``k_theta`` = prior strength in tossups heard,
``k_delta``). Older tournaments are down-weighted with a half-life (default 1 year) relative
to the snapshot date. The display rating is ``1500 + 200 * theta / spread``, where
``spread`` is the weighted SD of theta among established entities in the final snapshot.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class ModelParams:
    k_theta: float = 20.0
    k_delta: float = 150.0
    half_life_days: float = 365.0
    iters: int = 60
    established_weight: float = 150.0  # effective tossups heard to count toward the spread
    empirical_k: bool = True           # estimate k_theta from the data (empirical Bayes)
    sigma2: float | None = None        # per-tossup sampling variance (set by run_model)


@dataclass
class Obs:
    entity: np.ndarray      # int index
    tourn: np.ndarray       # int index
    y: np.ndarray
    w: np.ndarray
    days: np.ndarray        # tournament end date as ordinal day


def fit(obs: Obs, n_ent: int, n_t: int, delta0: np.ndarray, snapshot_day: int,
        p: ModelParams, mask: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Fit theta/delta on observations up to ``snapshot_day`` (inclusive)."""
    sel = obs.days <= snapshot_day if mask is None else (mask & (obs.days <= snapshot_day))
    e, t, y = obs.entity[sel], obs.tourn[sel], obs.y[sel]
    age = (snapshot_day - obs.days[sel]).astype(float)
    w = obs.w[sel] * np.power(0.5, age / p.half_life_days)
    theta = np.zeros(n_ent)
    delta = delta0.copy()
    W_e = np.bincount(e, weights=w, minlength=n_ent)
    W_t = np.bincount(t, weights=w, minlength=n_t)
    for _ in range(p.iters):
        theta = np.bincount(e, weights=w * (y + delta[t]), minlength=n_ent) / (W_e + p.k_theta)
        delta = (np.bincount(t, weights=w * (theta[e] - y), minlength=n_t) + p.k_delta * delta0) / (W_t + p.k_delta)
    resid = y - theta[e] + delta[t]
    dof = max(1.0, len(y) - 1.0)
    sigma2 = float(np.sum(w * resid ** 2) / dof) if len(y) else 3.0
    if p.sigma2:
        sigma2 = max(sigma2, p.sigma2)
    se = np.sqrt(sigma2 / (W_e + p.k_theta))
    return {"theta": theta, "delta": delta, "se": se, "weight": W_e, "sigma2": np.array(sigma2)}


def field_prior(obs: Obs, n_t: int, field_strength: np.ndarray, snapshot_day: int,
                p: ModelParams) -> tuple[np.ndarray, float]:
    """delta0[t] = beta * (field_strength[t] - 1500) / 100, beta fitted on a prior-free pass."""
    first = fit(obs, int(obs.entity.max()) + 1 if len(obs.entity) else 0, n_t, np.zeros(n_t),
                snapshot_day, p)
    W_t = np.bincount(obs.tourn, weights=obs.w, minlength=n_t)
    x = (field_strength - 1500.0) / 100.0
    ok = np.isfinite(x) & (W_t > 0)
    if ok.sum() < 5:
        return np.zeros(n_t), 0.0
    xw, dw, ww = x[ok], first["delta"][ok], W_t[ok]
    xm = np.average(xw, weights=ww)
    dm = np.average(dw, weights=ww)
    var = np.average((xw - xm) ** 2, weights=ww)
    beta = float(np.average((xw - xm) * (dw - dm), weights=ww) / var) if var > 0 else 0.0
    beta = max(0.0, beta)  # stronger fields can only make scoring harder
    d0 = np.where(np.isfinite(x), beta * (x - xm) + dm, 0.0)
    return d0, beta


def _empirical_k(obs: Obs, n_ent: int, n_t: int, snapshot_day: int, p: ModelParams,
                 sigma2: float | None) -> ModelParams:
    """k_theta = sigma^2 / tau^2 (empirical Bayes, method of moments).

    sigma^2 is the per-tossup sampling variance (from tossup counts, passed in by the caller);
    tau^2 is the between-entity variance of true ability: the weighted variance of entities'
    raw mean rates minus their average sampling variance.
    """
    from dataclasses import replace
    if not sigma2:
        return p
    W = np.bincount(obs.entity, weights=obs.w, minlength=n_ent)
    S = np.bincount(obs.entity, weights=obs.w * obs.y, minlength=n_ent)
    est = W >= p.established_weight
    if est.sum() < 20:
        return p
    m = S[est] / W[est]
    w = W[est]
    var_m = float(np.average((m - np.average(m, weights=w)) ** 2, weights=w))
    samp = float(np.average(sigma2 / w, weights=w))
    tau2 = var_m - samp
    if tau2 <= 1e-4:
        return p
    return replace(p, k_theta=float(np.clip(sigma2 / tau2, 3.0, 300.0)))


def to_elo(theta: np.ndarray, spread: float) -> np.ndarray:
    return 1500.0 + 200.0 * theta / spread


def spread_of(fitres: dict[str, np.ndarray], p: ModelParams) -> float:
    est = fitres["weight"] >= p.established_weight
    th, w = fitres["theta"][est], fitres["weight"][est]
    if len(th) < 5:
        return 0.4
    m = np.average(th, weights=w)
    return float(np.sqrt(np.average((th - m) ** 2, weights=w))) or 0.4


def day(d: dt.date | str) -> int:
    if isinstance(d, str):
        d = dt.date.fromisoformat(d)
    return d.toordinal()


def run_model(rows: list[dict[str, Any]], tournaments: list[dict[str, Any]], p: ModelParams,
              snapshot_days: list[int], history: bool = True, sigma2: float | None = None) -> dict[str, Any]:
    """rows: [{entity, tournament_id, y, w}] for ONE subject.
    tournaments: [{id, end_day, field_strength}] (all tournaments, any order).
    Returns current ratings + per-snapshot history for entities that played at that snapshot.
    """
    if not rows:
        return {"entities": {}, "history": {}, "beta": 0.0, "spread": None, "delta": {}}
    ent_ids = sorted({r["entity"] for r in rows})
    eidx = {e: i for i, e in enumerate(ent_ids)}
    t_ids = [t["id"] for t in tournaments]
    tidx = {t: i for i, t in enumerate(t_ids)}
    tday = np.array([t["end_day"] for t in tournaments])
    fs = np.array([t.get("field_strength") if t.get("field_strength") is not None else np.nan
                   for t in tournaments], dtype=float)
    obs = Obs(
        entity=np.array([eidx[r["entity"]] for r in rows]),
        tourn=np.array([tidx[r["tournament_id"]] for r in rows]),
        y=np.clip(np.array([r["y"] for r in rows], dtype=float), -4, 4),
        w=np.array([r["w"] for r in rows], dtype=float),
        days=np.array([tday[tidx[r["tournament_id"]]] for r in rows]),
    )
    final_day = max(snapshot_days)
    if sigma2:
        from dataclasses import replace as _replace
        p = _replace(p, sigma2=sigma2)
    if p.empirical_k:
        p = _empirical_k(obs, len(ent_ids), len(t_ids), final_day, p, sigma2)
    delta0, beta = field_prior(obs, len(t_ids), fs, final_day, p)
    final = fit(obs, len(ent_ids), len(t_ids), delta0, final_day, p)
    spread = spread_of(final, p)
    elo = to_elo(final["theta"], spread)
    se = 200.0 * final["se"] / spread
    last_day = np.zeros(len(ent_ids), dtype=int)
    np.maximum.at(last_day, obs.entity, obs.days)
    raw_w = np.bincount(obs.entity, weights=obs.w, minlength=len(ent_ids))
    n_t = np.bincount(obs.entity, minlength=len(ent_ids))
    entities = {e: {"rating": float(elo[i]), "se": float(se[i]), "theta": float(final["theta"][i]),
                    "eff_weight": float(final["weight"][i]), "weight": float(raw_w[i]),
                    "tournaments": int(n_t[i]), "last_day": int(last_day[i])}
                for e, i in eidx.items()}
    hist: dict[str, list[dict[str, Any]]] = {}
    if history:
        played_at: dict[int, set[int]] = {}
        for ei, d in zip(obs.entity, obs.days):
            played_at.setdefault(int(d), set()).add(int(ei))
        for d in sorted(set(snapshot_days) & set(played_at)):
            f = fit(obs, len(ent_ids), len(t_ids), delta0, d, p) if d != final_day else final
            el = to_elo(f["theta"], spread)
            sev = 200.0 * f["se"] / spread
            for ei in played_at[d]:
                hist.setdefault(ent_ids[ei], []).append({"day": d, "rating": round(float(el[ei]), 1),
                                                         "se": round(float(sev[ei]), 1)})
    deltas = {t_ids[i]: float(final["delta"][i]) for i in range(len(t_ids))}
    return {"entities": entities, "history": hist, "beta": beta, "spread": spread, "delta": deltas,
            "k_theta": p.k_theta}
