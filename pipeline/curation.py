"""Curation helper: dump every team "base name" with context, to build sources/reference/schools.yaml.

    python -m pipeline.curation > .cache/team_bases.json     # dump base names for curators
    python -m pipeline.curation merge                         # curator fragments -> reference files

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




def merge(parts: list[str]) -> dict:
    """Merge curator fragments (sources/reference/curation/*.yaml) into schools.yaml and
    team_aliases.yaml. Same id, or same normalized name + state, => one school (union of
    aliases). An alias claimed by two schools is reported and kept only on the school whose
    own name/short matches it best."""
    import yaml
    from .config import REFERENCE_DIR
    from .resolve import norm_key, slugify

    schools: dict[str, dict] = {}
    by_name_state: dict[tuple[str, str], str] = {}
    composite: dict[str, dict] = {}
    overrides: dict[str, dict] = {}
    unknown: list[dict] = []
    log: list[str] = []
    id_map: dict[str, str] = {}
    for path in parts:
        d = yaml.safe_load(open(path)) or {}
        for s in d.get("schools") or []:
            sid = s["id"]
            key = (norm_key(s["name"]), (s.get("state") or "").upper())
            target = sid if sid in schools else by_name_state.get(key)
            if target and target != sid:
                log.append(f"merged {sid} into {target} (same name+state)")
                id_map[sid] = target
            if target:
                t = schools[target]
                for a in s.get("aliases") or []:
                    if a not in t["aliases"]:
                        t["aliases"].append(a)
                for k in ("city", "state", "short"):
                    if not t.get(k) and s.get(k):
                        t[k] = s[k]
                continue
            schools[sid] = {"id": sid, "name": s["name"], "short": s.get("short") or s["name"],
                            "city": s.get("city") or "", "state": (s.get("state") or "").upper(),
                            "aliases": list(dict.fromkeys(s.get("aliases") or []))}
            by_name_state[key] = sid
        for c in d.get("composite") or []:
            c = {"name": c, "school": None} if isinstance(c, str) else c
            composite[c["name"]] = {"name": c["name"], "school": c.get("school")}
        for k, v in (d.get("overrides") or {}).items():
            overrides[k] = v
        unknown += d.get("unknown") or []
    # alias conflicts
    owner: dict[str, list[str]] = {}
    for sid, s in schools.items():
        for a in [s["name"], s["short"], *s["aliases"]]:
            k = norm_key(a)
            if k:
                owner.setdefault(k, [])
                if sid not in owner[k]:
                    owner[k].append(sid)
    for k, sids in owner.items():
        if len(sids) > 1:
            best = max(sids, key=lambda i: (norm_key(schools[i]["short"]) == k, norm_key(schools[i]["name"]) == k))
            log.append(f"alias {k!r} claimed by {sids}; kept on {best}")
            for i in sids:
                if i != best:
                    s = schools[i]
                    s["aliases"] = [a for a in s["aliases"] if norm_key(a) != k]
                    if norm_key(s["short"]) == k:
                        s["short"] = s["name"]
                    if norm_key(s["name"]) == k:
                        log.append(f"  !! {i} name itself conflicts; please fix by hand")
    # remap / validate references
    for c in composite.values():
        if c["school"]:
            c["school"] = id_map.get(c["school"], c["school"])
            if c["school"] not in schools:
                log.append(f"composite {c['name']!r}: unknown affiliate {c['school']!r} -> null")
                c["school"] = None
    for k, v in list(overrides.items()):
        if v.get("school"):
            v["school"] = id_map.get(v["school"], v["school"])
            if v["school"] not in schools:
                log.append(f"override {k!r}: unknown school {v['school']!r} -> dropped")
                del overrides[k]
    # names that are both composite and a school alias: the explicit school wins
    alias_keys = set(owner)
    for name in list(composite):
        if norm_key(name) in alias_keys and not composite[name]["school"]:
            log.append(f"{name!r} listed as composite and as a school alias; kept as school")
            del composite[name]
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    hdr = "# Generated by `python -m pipeline.curation merge` from sources/reference/curation/*.yaml; edit those.\n"
    with open(REFERENCE_DIR / "schools.yaml", "w") as fh:
        fh.write(hdr)
        yaml.safe_dump(sorted(schools.values(), key=lambda s: s["id"]), fh, sort_keys=False, allow_unicode=True, width=140)
    with open(REFERENCE_DIR / "team_aliases.yaml", "w") as fh:
        fh.write(hdr)
        yaml.safe_dump({"composite": [c if c["school"] else c["name"] for c in sorted(composite.values(), key=lambda c: c["name"].lower())],
                        "overrides": dict(sorted(overrides.items()))}, fh, sort_keys=False, allow_unicode=True, width=140)
    return {"schools": len(schools), "composite": len(composite), "overrides": len(overrides),
            "unknown": len(unknown), "log": log}


def _main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        from .config import REFERENCE_DIR
        parts = sorted(str(p) for p in (REFERENCE_DIR / "curation").glob("*.yaml"))
        res = merge(parts)
        for line in res.pop("log"):
            print(line)
        print(res)
    else:
        json.dump(collect(), sys.stdout, indent=1)


if __name__ == "__main__":
    _main()
