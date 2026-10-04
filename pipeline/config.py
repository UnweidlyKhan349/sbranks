"""Shared paths, subject vocabulary and season helpers."""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "sources"
TOURNAMENTS_DIR = SOURCES_DIR / "tournaments"
REFERENCE_DIR = SOURCES_DIR / "reference"
RAW_DIR = ROOT / "raw"
PARSED_DIR = ROOT / "data" / "parsed"
BUILD_DIR = ROOT / "data" / "build"
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"

# Canonical subjects, in display order. "overall" is the player's / team's total.
SUBJECTS = ["math", "physics", "chemistry", "biology", "ess", "energy"]
SUBJECT_LABELS = {
    "overall": "Overall",
    "math": "Math",
    "physics": "Physics",
    "chemistry": "Chemistry",
    "biology": "Biology",
    "ess": "Earth & Space",
    "energy": "Energy",
    "other": "Other",
}
ALL_SUBJECT_KEYS = ["overall", *SUBJECTS, "other"]

_SUBJECT_ALIASES = {
    "math": "math", "maths": "math", "mathematics": "math", "m": "math",
    "phys": "physics", "physics": "physics", "phy": "physics", "p": "physics",
    "chem": "chemistry", "chemistry": "chemistry", "chemstry": "chemistry", "c": "chemistry",
    "bio": "biology", "biology": "biology", "life": "biology", "life science": "biology",
    "life sciences": "biology", "b": "biology",
    "ess": "ess", "es": "ess", "e&s": "ess", "earth": "ess", "space": "ess",
    "earth and space": "ess", "earth & space": "ess", "earth and space science": "ess",
    "earth & space science": "ess", "earth science": "ess", "astronomy": "ess", "astro": "ess",
    "earth/space": "ess", "esci": "ess",
    "energy": "energy", "en": "energy", "e": "energy", "csenergy": "energy",
    "overall": "overall", "all": "overall", "total": "overall", "ovr": "overall",
    "compsci": "other", "computer science": "other", "cs": "other",
    "general science": "other", "gen sci": "other", "general": "other", "other": "other",
}


def normalize_subject(label: str | None) -> str | None:
    """Map a source's category label to a canonical subject key (or None if unknown).

    Single letters are accepted (B/C/E/ES/M/P as used by e.g. Stanford's stats sheets),
    so only call this on strings you already know are category labels.
    """
    if label is None:
        return None
    key = re.sub(r"\s+", " ", str(label).strip().lower())
    key = re.sub(r"\b(stats?|ppg|rr|de|individual|indiv|team|sorted|unsorted|leaderboard)\b", "", key)
    key = re.sub(r"\s+", " ", key).strip(" :-_")
    return _SUBJECT_ALIASES.get(key)


def season_for_date(d: _dt.date) -> str:
    """School-year season label, e.g. 2025-10-04 -> '2025-26'. Seasons start Aug 1.

    The registry stores each tournament's season explicitly (copied from the Stanford
    tournament list, which files summer events under the following season); use this only
    for sources without one (e.g. NSB Nationals, held in late April / May).
    """
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def season_start_year(season: str) -> int:
    return int(season[:4])
