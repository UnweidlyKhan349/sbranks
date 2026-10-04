"""Entity resolution: raw team / player names in data/parsed/* -> schools, teams, players.

Reference data (hand-curated, in sources/reference/):

``schools.yaml``
    - id: lynbrook                       # slug, stable forever
      name: Lynbrook High School
      short: Lynbrook                    # display name used in team names ("Lynbrook A")
      city: San Jose
      state: CA
      aliases: [Lynbrook, Lynbrook HS]   # base team names (letter suffix removed) seen in sources

``team_aliases.yaml``  (exceptions the automatic rules get wrong)
    composite:                           # pickup / multi-school / online-only team names
      - Ultimate Uzbeks
      - {name: Gargy Bomy, school: west-windsor-plainsboro-high-school-south-nj}  # affiliated
    overrides:                           # raw team name -> explicit mapping
      "BISV A": {school: basis-independent-silicon-valley, letter: A}
      "<tournament_id>::Some Name": {school: ..., letter: B}   # tournament-specific

``player_aliases.yaml``
    merge:                               # names (any spelling) that are the same person
      - [Theenash Sengupta, Theenash S]
    same_person:                         # same name at different schools IS one person (transfer)
      - Jane Doe
    rename:                              # fix a source's spelling for display
      suzuko ohshima: Suzuko Ohshima

Run ``python -m pipeline.resolve --report`` to list unmatched team bases (for curation).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import registry
from .config import BUILD_DIR, PARSED_DIR, REFERENCE_DIR
from .schema import load_parsed, num

LETTER_RX = re.compile(r"^(?P<base>.*?)[\s\-_]*(?:\(\s*)?\b(?P<letter>[A-Ha-h]|[1-8]|I{1,3}|IV)(?:\s*\))?$")
ROMAN = {"I": "A", "II": "B", "III": "C", "IV": "D"}
_STOPWORDS = r"\b(high school|high|school|hs|h\.s\.|senior|sr|academy of science|the|team|of)\b"


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.replace("&", " and ").replace("'", "").replace("‘", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def norm_key(s: str) -> str:
    """Aggressive normalization for matching school base names."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace(".", " ")
    s = re.sub(_STOPWORDS, " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_person(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z\s\-]", " ", s).replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def split_team_name(raw: str) -> tuple[str, str | None]:
    """'Mission San Jose B' -> ('Mission San Jose', 'B'); 'Lynbrook' -> ('Lynbrook', None)."""
    raw = raw.strip()
    m = LETTER_RX.match(raw)
    if m and m.group("base").strip() and len(m.group("base").strip()) >= 2:
        base, letter = m.group("base").strip(" -_("), m.group("letter").upper()
        # Don't split names whose last token is a real word like "Team 2510" or "School 1"
        if letter.isdigit():
            if re.search(r"\d$", base):
                return raw, None
            letter = "ABCDEFGH"[int(letter) - 1]
        letter = ROMAN.get(letter, letter)
        if len(letter) == 1 and letter in "ABCDEFGH":
            return base, letter
    return raw, None


def display_case(name: str) -> str:
    if name.islower() or name.isupper():
        return " ".join(w.capitalize() if len(w) > 1 else w.upper() for w in name.split())
    return name


@dataclass
class School:
    id: str
    name: str
    short: str
    city: str = ""
    state: str = ""
    aliases: list[str] = field(default_factory=list)
    curated: bool = True
    composite: bool = False
    affiliate: str | None = None        # composite team mostly drawn from this school


class Resolver:
    def __init__(self) -> None:
        def _load(name: str) -> Any:
            p = REFERENCE_DIR / name
            return yaml.safe_load(p.read_text()) if p.exists() else None

        self.schools: dict[str, School] = {}
        self.alias_to_school: dict[str, str] = {}
        for s in _load("schools.yaml") or []:
            sch = School(id=s["id"], name=s["name"], short=s.get("short") or s["name"],
                         city=s.get("city") or "", state=s.get("state") or "",
                         aliases=list(s.get("aliases") or []),
                         composite=bool(s.get("composite", False)))
            self.schools[sch.id] = sch
            for a in [sch.name, sch.short, *sch.aliases]:
                k = norm_key(a)
                if k:
                    prev = self.alias_to_school.get(k)
                    if prev and prev != sch.id:
                        raise ValueError(f"alias {a!r} maps to both {prev} and {sch.id}")
                    self.alias_to_school[k] = sch.id
        ta = _load("team_aliases.yaml") or {}
        self.composite_aff: dict[str, str | None] = {}
        for x in ta.get("composite") or []:
            name, aff = (x, None) if isinstance(x, str) else (x["name"], x.get("school"))
            self.composite_aff[name.strip().lower()] = aff
            self.composite_aff[norm_key(name)] = aff
        self.composite = set(self.composite_aff)
        self.composite_raw = set(self.composite_aff)
        self.overrides: dict[str, dict[str, Any]] = {k: v for k, v in (ta.get("overrides") or {}).items()}
        pa = _load("player_aliases.yaml") or {}
        self.player_merge: dict[str, str] = {}
        for group in pa.get("merge") or []:
            canon = norm_person(group[0])
            for n in group:
                self.player_merge[norm_person(n)] = canon
        self.player_nosplit = {self.player_merge.get(norm_person(n), norm_person(n)) for n in pa.get("same_person") or []}
        self.player_rename = {norm_person(k): v for k, v in (pa.get("rename") or {}).items()}
        self.unmatched: Counter[str] = Counter()

    # ---- teams --------------------------------------------------------------------------
    def resolve_team(self, tid: str, raw: str, school_hint: str = "", state_hint: str = "") -> tuple[str, str, bool]:
        """Return (school_id, letter, composite) for a raw team name in tournament ``tid``."""
        ov = self.overrides.get(f"{tid}::{raw}") or self.overrides.get(raw)
        if ov:
            if ov.get("composite"):
                sid = self._composite_school(ov.get("name") or raw, ov.get("school"))
                return sid, "A", True
            return ov["school"], ov.get("letter", "A"), False
        for k in (raw.strip().lower(), norm_key(raw)):
            if k in self.composite_aff:
                return self._composite_school(raw, self.composite_aff[k]), "A", True
        base, letter = split_team_name(raw)
        for candidate in (base, raw, school_hint):
            if not candidate:
                continue
            sid = self.alias_to_school.get(norm_key(candidate))
            if sid:
                if candidate == raw and letter and base != raw:
                    letter = letter  # raw itself is an alias that includes the letter
                return sid, (letter or "A"), self.schools[sid].composite
        # Unknown: create an uncurated school named after the base name.
        self.unmatched[base] += 1
        sid = "u-" + slugify(base)
        if sid not in self.schools:
            self.schools[sid] = School(id=sid, name=base, short=base, state=state_hint, curated=False)
        return sid, (letter or "A"), False

    def _composite_school(self, name: str, affiliate: str | None = None) -> str:
        sid = "x-" + slugify(name)
        if sid not in self.schools:
            if affiliate and affiliate not in self.schools:
                raise ValueError(f"composite team {name!r}: unknown affiliated school {affiliate!r}")
            self.schools[sid] = School(id=sid, name=name, short=name, curated=False, composite=True,
                                       affiliate=affiliate)
        return sid

    # ---- players ------------------------------------------------------------------------
    def player_key(self, raw: str) -> str:
        k = norm_person(raw)
        if "," in raw and len(raw.split(",")) == 2:  # "Last, First"
            last, first = (x.strip() for x in raw.split(","))
            k = norm_person(f"{first} {last}")
        return self.player_merge.get(k, k)


def build() -> dict[str, Any]:
    """Resolve every parsed, included tournament into combined tables (data/build/*.json)."""
    R = Resolver()
    tournaments = [t for t in registry.all_tournaments() if (PARSED_DIR / t.id / "meta.json").exists()]
    teams: dict[str, dict[str, Any]] = {}
    games: list[dict[str, Any]] = []
    pstats: list[dict[str, Any]] = []
    tgs: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    player_obs: list[dict[str, Any]] = []   # (tournament, raw player, team id, school, season)
    tinfo = []
    conflicts: list[dict[str, Any]] = []

    for t in tournaments:
        d = load_parsed(t.id)
        team_map: dict[str, str] = {}
        if t.get("individual"):
            # 1v1 events: competitors are people, not teams. Keep only their player stats.
            for r in d["player_stats"]:
                player_obs.append({"tournament_id": t.id, "season": t.season, "raw": r["player"],
                                   "team_id": None, "school_id": "x-individual", "composite": True})
                pstats.append({"tournament_id": t.id, "raw_player": r["player"], "team_id": None,
                               "scope": r["scope"], "subject": r["subject"],
                               **{k: num(r[k]) for k in ("gp", "tuh", "correct", "zeros", "negs", "points", "ppg")}})
            tinfo.append(t)
            continue
        for tr in d["teams"]:
            sid, letter, comp = R.resolve_team(t.id, tr["team"], tr.get("school", ""), tr.get("state", ""))
            sch = R.schools[sid]
            team_id = sid if comp else f"{sid}-{letter.lower()}"
            if team_id in team_map.values():
                # two different raw names resolved to the same team in one tournament: keep them apart
                clash = next(k for k, v in team_map.items() if v == team_id)
                conflicts.append({"tournament_id": t.id, "team_id": team_id, "raw": [clash, tr["team"]]})
                team_id = f"{team_id}--{slugify(tr['team'])}"
            team_map[tr["team"]] = team_id
            if team_id not in teams:
                teams[team_id] = {"id": team_id, "school_id": sid, "letter": None if comp else letter,
                                  "name": sch.short if comp else f"{sch.short} {letter}",
                                  "composite": comp, "raw_names": []}
            if tr["team"] not in teams[team_id]["raw_names"]:
                teams[team_id]["raw_names"].append(tr["team"])
            if tr.get("state") and not sch.state:
                sch.state = tr["state"]
            entries.append({"tournament_id": t.id, "team_id": team_id, "raw_name": tr["team"]})
        for g in d["games"]:
            games.append({
                "tournament_id": t.id, "game_id": g["game_id"], "stage": g["stage"], "round": g["round"],
                "seq": int(num(g["seq"]) or 0), "team1": team_map[g["team1"]], "team2": team_map[g["team2"]],
                "score1": num(g["score1"]), "score2": num(g["score2"]), "result": g["result"],
                "forfeit": g["forfeit"] == "1",
            })
        for r in d["team_game_subjects"]:
            tgs.append({"tournament_id": t.id, "game_id": r["game_id"], "team_id": team_map[r["team"]],
                        "subject": r["subject"], **{k: num(r[k]) for k in
                        ("points", "tossup_points", "bonus_points", "tossups_correct", "negs")}})
        for r in d["player_stats"]:
            team_id = team_map[r["team"]]
            player_obs.append({"tournament_id": t.id, "season": t.season, "raw": r["player"],
                               "team_id": team_id, "school_id": teams[team_id]["school_id"],
                               "composite": teams[team_id]["composite"]})
            pstats.append({"tournament_id": t.id, "raw_player": r["player"], "team_id": team_id,
                           "scope": r["scope"], "subject": r["subject"],
                           **{k: num(r[k]) for k in ("gp", "tuh", "correct", "zeros", "negs", "points", "ppg")}})
        tinfo.append(t)

    players, raw_to_pid = _resolve_players(R, player_obs)
    for r in pstats:
        r["player_id"] = raw_to_pid[(r["tournament_id"], r["raw_player"], r["team_id"])]

    schools_out = {}
    used_schools = {tm["school_id"] for tm in teams.values()}
    for sid in sorted(used_schools):
        s = R.schools[sid]
        schools_out[sid] = {"id": sid, "name": s.name, "short": s.short, "city": s.city,
                            "state": s.state, "curated": s.curated, "composite": s.composite,
                            "affiliate": s.affiliate}
        if s.affiliate and s.affiliate not in schools_out:
            a = R.schools[s.affiliate]
            schools_out[a.id] = {"id": a.id, "name": a.name, "short": a.short, "city": a.city, "state": a.state,
                                 "curated": a.curated, "composite": a.composite, "affiliate": None}
    out = {
        "schools": schools_out, "teams": teams, "players": players, "games": games,
        "player_stats": pstats, "team_game_subjects": tgs, "entries": entries,
        "unmatched_team_bases": R.unmatched.most_common(),
        "tournament_ids": [t.id for t in tinfo],
        "conflicts": conflicts,
    }
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "resolved.json").write_text(json.dumps(out))
    return out


def _resolve_players(R: Resolver, obs: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[tuple, str]]:
    """Group raw player names into people.

    Rules: same normalized full name => same person, except when the name appears at two
    different real (non-composite) schools, which are then treated as different people
    (unless listed under ``same_person`` in player_aliases.yaml).
    Appearances on composite/pickup teams attach to the unique same-name person, if any.
    Abbreviated names ("Theenash S") attach to the unique full-name person at the same school
    whose first name and last initial match; otherwise they stay separate.
    """
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in obs:
        o["key"] = R.player_key(o["raw"])
        by_name[o["key"]].append(o)

    # person id = (key, school or None)
    person_of: dict[int, tuple[str, str | None]] = {}
    for key, os_ in by_name.items():
        real_schools = {o["school_id"] for o in os_ if not o["composite"] and not o["school_id"].startswith("x-")}
        # Same full name at two real schools: assume two different people unless curated.
        split = len(real_schools) > 1 and key not in R.player_nosplit
        for o in os_:
            if split and not o["composite"]:
                person_of[id(o)] = (key, o["school_id"])
            elif split:
                person_of[id(o)] = (key, "?")
            else:
                person_of[id(o)] = (key, None)

    # abbreviated names
    full_by_school_first: dict[tuple[str, str, str], set[tuple[str, str | None]]] = defaultdict(set)
    for o in obs:
        toks = o["key"].split()
        if len(toks) >= 2 and len(toks[-1]) > 1:
            full_by_school_first[(o["school_id"], toks[0], toks[-1][0])].add(person_of[id(o)])
    full_by_first: dict[tuple[str, str], set[tuple[str, str | None]]] = defaultdict(set)
    for (sch, first, initial), people_ in full_by_school_first.items():
        full_by_first[(first, initial)] |= people_
    for o in obs:
        toks = o["key"].split()
        if len(toks) == 2 and len(toks[-1]) == 1:
            cands = full_by_school_first.get((o["school_id"], toks[0], toks[-1]), set())
            if not cands and o["composite"]:
                # pickup / individual events: accept a unique match anywhere
                cands = full_by_first.get((toks[0], toks[-1]), set())
            if len(cands) == 1:
                person_of[id(o)] = next(iter(cands))

    pid_of_person: dict[tuple[str, str | None], str] = {}
    people: dict[str, dict[str, Any]] = {}
    raw_to_pid: dict[tuple, str] = {}
    names: dict[str, Counter[str]] = defaultdict(Counter)
    schools: dict[str, Counter[str]] = defaultdict(Counter)
    for o in sorted(obs, key=lambda o: (o["tournament_id"], o["raw"])):
        person = person_of[id(o)]
        pid = pid_of_person.get(person)
        if pid is None:
            base = slugify(person[0]) or "player"
            pid = base if person[1] in (None, "?") else f"{base}--{person[1]}"
            n = 2
            while pid in people:
                pid = f"{base}-{n}"
                n += 1
            pid_of_person[person] = pid
            people[pid] = {"id": pid, "aliases": []}
        raw_to_pid[(o["tournament_id"], o["raw"], o["team_id"])] = pid
        names[pid][o["raw"]] += 1
        if not o["composite"]:
            schools[pid][o["school_id"]] += 1
    for pid, p in people.items():
        variants = names[pid]
        full = [v for v in variants if not re.search(r"\s\w\.?$", v)] or list(variants)
        best = max(full, key=lambda v: (not v.islower() and not v.isupper(), variants[v], len(v)))
        renamed = R.player_rename.get(norm_person(best))
        p["name"] = renamed or display_case(best)
        p["aliases"] = sorted(v for v in variants if v != p["name"])
        p["school_id"] = schools[pid].most_common(1)[0][0] if schools[pid] else None
    return people, raw_to_pid


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print unmatched team bases")
    a = ap.parse_args(argv)
    out = build()
    print(f"{len(out['schools'])} schools, {len(out['teams'])} teams, {len(out['players'])} players, "
          f"{len(out['games'])} games, {len(out['player_stats'])} player stat rows")
    for c in out["conflicts"]:
        print("CONFLICT", c)
    if a.report:
        for base, n in out["unmatched_team_bases"]:
            print(f"{n:4d}  {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
