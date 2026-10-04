"""Build sources/reference/nsb_winners.yaml from the official Past HS Winners page.

    python -m pipeline.parsers.tools.nsb_winners

Input: raw/2026-04-30-nsb-national-finals/past_hs_winners.html (snapshot of
https://science.osti.gov/wdts/nsb/About/Historical-Information/Past-National-Science-Bowl-Winners/Past-HS-Winners).
Years not yet on that page are filled from parsed National Finals brackets (the DE champion).
"""
from __future__ import annotations

import json
import re

import yaml
from bs4 import BeautifulSoup

from ...config import PARSED_DIR, RAW_DIR, REFERENCE_DIR

STATES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
          "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
          "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
          "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
          "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
          "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
          "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
          "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
          "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
          "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC"}


def _place(text: str) -> tuple[str, str, str]:
    """'Lexington High School in Lexington, Massachusetts' -> (school, city, state)."""
    text = re.sub(r"\s+", " ", text).strip(" ;.")
    m = re.match(r"^(.*?)(?:,| - | of | in | from | team of )\s*([A-Za-z .'\-]+?),\s*([A-Za-z .]+)$", text)
    if not m:
        return text, "", ""
    school, city, st = (x.strip() for x in m.groups())
    school = re.sub(r"\s+(team|of|in|from)$", "", school).strip(" ,")
    st_code = STATES.get(st.lower(), st.upper() if len(st) == 2 else st)
    return school, city, st_code


def main() -> None:
    html = (RAW_DIR / "2026-04-30-nsb-national-finals" / "past_hs_winners.html").read_text(errors="replace")
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tr in soup.find_all("tr"):
        cells = [c for c in tr.find_all(["td", "th"]) if c.get_text(strip=True)]
        if len(cells) < 2:
            continue
        year = cells[0].get_text(" ", strip=True)
        if not re.fullmatch(r"(19|20)\d\d", year):
            continue
        body = cells[1].get_text("\n", strip=True).replace("\xa0", " ")
        body = re.sub(r"[ \t]+", " ", body)
        # the page capitalises inconsistently ("Team members:" in 1991-1997)
        m = re.search(r"First Place(?: High School)? Team\s*:?\s*(.+?)(?:\n|Team Members)", body, re.S | re.I)
        school, city, state = _place(m.group(1)) if m else ("", "", "")
        roster, coach = [], None
        mm = re.search(r"Team Members\s*:?\s*(.+?)(?:\n(?:Prize|Other Participants|Winners of)|$)", body,
                       re.S | re.I)
        if mm:
            names = re.split(r",|\band\b|\n", mm.group(1))
            for n in names:
                n = n.strip(" .;")
                if not n:
                    continue
                if "coach" in n.lower():
                    coach = re.sub(r"\(?\s*coach\s*\)?", "", n, flags=re.I).strip(" ()")
                    continue
                if n not in roster:
                    roster.append(n)
        if coach in roster:
            roster.remove(coach)
        out.append({"year": int(year), "school": school, "city": city, "state": state,
                    "roster": roster, "coach": coach})
    years = {w["year"] for w in out}
    # add Finals parsed in this repo but not yet on the official page (champion = winner of last DE game)
    for d in sorted(PARSED_DIR.glob("*-nsb-national-finals")):
        y = int(d.name[:4])
        if y in years:
            continue
        games = [r for r in __import__("csv").DictReader(open(d / "games.csv")) if r["stage"] == "playoff"]
        if not games:
            continue
        last = max(games, key=lambda g: (int(g["seq"] or 0), g["game_id"]))
        champ = last["team1"] if last["result"] == "1" else last["team2"]
        teams = {r["team"]: r for r in __import__("csv").DictReader(open(d / "teams.csv"))}
        t = teams.get(champ, {})
        city = {"Mission San Jose High School": "Fremont"}.get(champ, "")  # not stated in the bracket
        out.append({"year": y, "school": champ, "city": city, "state": t.get("state", ""), "roster": [],
                    "coach": None, "source": "derived from the official double-elimination bracket"})
    out.sort(key=lambda w: -w["year"])
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(REFERENCE_DIR / "nsb_winners.yaml", "w") as fh:
        fh.write("# High-school National Science Bowl champions (official list:\n"
                 "# https://science.osti.gov/wdts/nsb/About/Historical-Information/Past-National-Science-Bowl-Winners/Past-HS-Winners)\n"
                 "# Generated by: python -m pipeline.parsers.tools.nsb_winners\n")
        yaml.safe_dump(out, fh, sort_keys=False, allow_unicode=True, width=120)
    print(json.dumps(out[:4], indent=1))
    print(len(out), "years")
    for w in out:
        if not w["state"] or not w["city"]:
            print("CHECK", w["year"], w["school"], w["city"], w["state"])


if __name__ == "__main__":
    main()
