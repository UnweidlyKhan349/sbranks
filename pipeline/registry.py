"""Tournament registry: one YAML file per tournament in sources/tournaments/.

Schema (keys not listed are allowed and ignored):

    id: 2026-03-08-stanford-science-bowl     # == file stem
    name: Stanford Science Bowl
    date: 2026-03-08                         # start date (ISO)
    end_date: null                           # for multi-day / multi-week events
    season: 2025-26
    location: Palo Alto, CA
    online: false
    division: HS                             # HS | MS | College+
    include: true                            # false => not parsed / not rated
    exclude_reason: null
    kind: invitational                       # invitational | league | nationals | scrimmage
    level: standard                          # novice | standard | advanced
    subject_only: null                       # e.g. chemistry for a ChemBowl
    question_set: null                       # shared set id for mirrors (e.g. stanford-2026)
    sources:                                 # see pipeline/fetch.py for kinds
      - {kind: gsheet, role: results, sheet_id: ..., url: ..., file: results.xlsx}
    parser: null                             # "module:function" under pipeline/parsers
    parser_options: {}
    status: todo                             # todo | parsed | partial | unavailable
    notes: ""
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import RAW_DIR, TOURNAMENTS_DIR


@dataclass
class Tournament:
    id: str
    name: str
    date: dt.date
    season: str
    data: dict[str, Any] = field(repr=False)
    path: Path = field(repr=False)

    @property
    def end_date(self) -> dt.date:
        e = self.data.get("end_date")
        return _as_date(e) if e else self.date

    @property
    def include(self) -> bool:
        return bool(self.data.get("include", True))

    @property
    def sources(self) -> list[dict[str, Any]]:
        return list(self.data.get("sources") or [])

    @property
    def raw_dir(self) -> Path:
        return RAW_DIR / self.id

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def raw(self, filename: str) -> Path:
        return self.raw_dir / filename

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.data, fh, sort_keys=False, allow_unicode=True, width=120)


def _as_date(v: Any) -> dt.date:
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def load(path: Path) -> Tournament:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data.get("id") != path.stem:
        raise ValueError(f"{path}: id {data.get('id')!r} != file name")
    return Tournament(id=data["id"], name=data["name"], date=_as_date(data["date"]),
                      season=str(data["season"]), data=data, path=path)


def all_tournaments(include_excluded: bool = False) -> list[Tournament]:
    ts = [load(p) for p in sorted(TOURNAMENTS_DIR.glob("*.yaml"))]
    if not include_excluded:
        ts = [t for t in ts if t.include]
    return sorted(ts, key=lambda t: (t.end_date, t.date, t.id))


def get(tournament_id: str) -> Tournament:
    return load(TOURNAMENTS_DIR / f"{tournament_id}.yaml")
