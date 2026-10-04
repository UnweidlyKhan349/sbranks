"""Curation helper: dump every team "base name" with context, to build sources/reference/schools.yaml.

    python -m pipeline.curation > .cache/team_bases.json

For each base name (team name with its A/B/C suffix removed) it lists the raw names, the
tournaments (with location / online flag), school & state hints from the sources, a few
player names, and the school id the current reference data resolves it to (if any).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from . import registry
from .config import PARSED_DIR
from .resolve import Resolver, norm_key, split_team_name
from .schema import load_parsed


def collect() -> list[dict]:
    R = Resolver()
    bases: dict[str, dict] = {}
    for t in registry.all_tournaments():
        if not (PARSED_DIR / t.id / "meta.json").exists() or t.get("individual"):
            continue
        d = load_parsed(t.id)
        for tr in d["teams"]:
            raw = tr["team"]
            base, letter = split_team_name(raw)
            k = norm_key(base) or base.lower()
            b = bases.setdefault(k, {"base": base, "raw_names": set(), "tournaments": [], "school_hints": set(),
                                     "state_hints": set(), "players": set(), "all_players": set(),
                                     "resolved": None})
            b["raw_names"].add(raw)
            b["tournaments"].append(f"{t.id} ({t.get('location') or ''})")
            if tr.get("school"):
                b["school_hints"].add(tr["school"])
            if tr.get("state"):
                b["state_hints"].add(tr["state"])
            for p in (tr.get("players") or "").split(";"):
                if p:
                    b["all_players"].add(p)
                    if len(b["players"]) < 8:
                        b["players"].add(p)
            sid = R.alias_to_school.get(norm_key(base)) or R.alias_to_school.get(norm_key(raw))
            if sid:
                b["resolved"] = sid
            if raw.strip().lower() in R.composite_raw:
                b["resolved"] = "COMPOSITE"
    # roster overlap: which other base names share players with this one (links nicknames to schools)
    from .resolve import norm_person
    player_bases: dict[str, set[str]] = defaultdict(set)
    for k, b in bases.items():
        for p in b["all_players"]:
            player_bases[norm_person(p)].add(k)
    out = []
    for k, b in sorted(bases.items(), key=lambda kv: kv[0]):
        overlap: dict[str, int] = defaultdict(int)
        for p in b["all_players"]:
            for other in player_bases[norm_person(p)]:
                if other != k:
                    overlap[bases[other]["base"]] += 1
        b["overlap"] = dict(sorted(overlap.items(), key=lambda kv: -kv[1])[:8])
        out.append({"key": k, "base": b["base"], "raw_names": sorted(b["raw_names"]),
                    "n_tournaments": len(b["tournaments"]), "tournaments": sorted(set(b["tournaments"]))[:12],
                    "school_hints": sorted(b["school_hints"]), "state_hints": sorted(b["state_hints"]),
                    "players": sorted(b["players"]), "shares_players_with": b["overlap"],
                    "resolved": b["resolved"]})
    return out


if __name__ == "__main__":
    json.dump(collect(), sys.stdout, indent=1)
