"""NSB National Finals 2020 and 2021 (virtual).

In the virtual years teams answered the same questions simultaneously and the top scorers
advanced; the only head-to-head game was the championship match. We record the field that
DOE published (2020: the top 16, 8, 4 and 2 press releases; 2021: the two finalists) and the
championship match (result only). Finish places for these years are written to
sources/reference/nsb_finishes.yaml by pipeline/parsers/tools/nsb_finishes.py.
"""
from __future__ import annotations

import re
import subprocess

from ..registry import Tournament
from ..schema import TournamentWriter
from .tools.nsb_winners import STATES

BULLET = re.compile(r"^\s*[•\-•]\s*(?P<school>.+?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Za-z .]+?),?\s*$")


def _bullets(pdf) -> list[tuple[str, str, str]]:
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
    out = []
    for line in text.splitlines():
        m = BULLET.match(line)
        if m:
            school = re.sub(r"\s*\(High School\)", "", m.group("school")).strip()
            out.append((school, m.group("city").strip(), STATES.get(m.group("state").strip().lower(), "")))
    return out


def parse(t: Tournament, w: TournamentWriter, final: list[str], field_pdfs: list[str] | None = None,
          field: list[list[str]] | None = None) -> None:
    """final: [winner, runner_up] (exact names used for teams)."""
    for name in field_pdfs or []:
        for school, city, state in _bullets(t.raw(name)):
            w.team(school, school=school, state=state, notes=f"{city}, {state}; reached the {name.split('.')[0]}")
    for school, city, state in field or []:
        w.team(school, school=school, state=state, notes=f"{city}, {state}")
    winner, runner_up = final
    w.game(winner, runner_up, stage="playoff", round="Championship", seq=1, result="1",
           game_id="final", notes="virtual championship match; result only")
