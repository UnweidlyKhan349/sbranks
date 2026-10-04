"""Official DOE National Science Bowl (NSB) National Finals, high-school division.

Sources (science.osti.gov; see each year's YAML):

* Round robin: one table per division (``round_robin.html``; 2024/2025 only as screenshot PDFs, hand
  transcribed to ``rr_transcribed.yaml``). Each pairing is a 2/1/0 (win/tie/loss) cell; there are no game
  scores. The page also gives Total Points, the 1st-4th division place (printed next to the total), the
  Division Team Challenge (DTC) rank and, in 2022, the seed.
* Double elimination: a No-Loss and a One-Loss bracket (``de_no_loss.pdf`` / ``de_one_loss.pdf``; 2022 and
  2023 only as images, hand transcribed to ``de_transcribed.yaml``). Brackets name teams by short names
  ("Lynbrook HS") labelled with their round-robin finish ("Ames-1st") or seed ("Ranking #1"); every later
  slot is labelled "Winner GM-n" or "One-Loss from GM-n". Games are numbered (GM-1.., GM-A..) and placed in
  numbered time-slot rounds. No scores.

Output: one ``rr`` game per round-robin pairing (result only; ``round`` = division name), one ``playoff`` game
per DE game (result only; ``round`` = ``DE<slot>``, ``game_id`` = ``GM-<n>``), teams under their full
round-robin names with school/state hints.

The virtual years (2020, 2021) had no head-to-head play before the championship match: teams answered the
same questions simultaneously and the top scorers advanced. ``parse_virtual`` writes the field (with
city/state) and the single championship match.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name

PLACE_RX = re.compile(r"^(?P<div>.+?)\s*-\s*(?P<place>[1-4])(?:st|nd|rd|th)$")
SEED_RX = re.compile(r"^Ranking\s*#\s*(?P<seed>\d+)$", re.I)
WIN_RX = re.compile(r"^Winner\s+(?:from\s+)?GM\s*-\s*(?P<g>[A-Z0-9]+)$", re.I)
LOSS_RX = re.compile(r"^One\s*-?\s*Loss\s+from\s+GM\s*-\s*(?P<g>[A-Z0-9]+)$", re.I)
GAME_RX = re.compile(r"^GM\s*-\s*(?P<g>[A-Z0-9]+)\s*:?")

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Puerto Rico": "PR", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Virgin Islands": "VI", "U.S. Virgin Islands": "VI", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "Guam": "GU",
}
# AP-style abbreviations used in DOE press releases ("Calif.", "N.Y.")
AP_STATES = {
    "Ala.": "AL", "Ariz.": "AZ", "Ark.": "AR", "Calif.": "CA", "Colo.": "CO", "Conn.": "CT", "Del.": "DE",
    "D.C.": "DC", "Fla.": "FL", "Ga.": "GA", "Ill.": "IL", "Ind.": "IN", "Kan.": "KS", "Kans.": "KS",
    "Ky.": "KY", "La.": "LA", "Md.": "MD", "Mass.": "MA", "Mich.": "MI", "Minn.": "MN", "Miss.": "MS",
    "Mo.": "MO", "Mont.": "MT", "Neb.": "NE", "Nebr.": "NE", "Nev.": "NV", "N.H.": "NH", "N.J.": "NJ",
    "N.M.": "NM", "N.Y.": "NY", "N.C.": "NC", "N.D.": "ND", "Okla.": "OK", "Ore.": "OR", "Pa.": "PA",
    "P.R.": "PR", "R.I.": "RI", "S.C.": "SC", "S.D.": "SD", "Tenn.": "TN", "Tex.": "TX", "Ut.": "UT",
    "Vt.": "VT", "Va.": "VA", "Wash.": "WA", "W.Va.": "WV", "Wis.": "WI", "Wyo.": "WY", "V.I.": "VI",
}


def _state_code(s: str) -> str:
    s = clean_name(s).rstrip(",")
    if s in STATES:
        return STATES[s]
    if s in AP_STATES:
        return AP_STATES[s]
    if s.upper() in STATES.values() and len(s) == 2:
        return s.upper()
    return STATES.get(s.title(), "")


def _key(name: str, loose: bool = False) -> str:
    """Matching key for school names across a year's pages. The strict key keeps school-type words
    ("Lakeside School" != "Lakeside High School"); the loose key drops them ("University High" ==
    "University High School")."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace("`", "").replace(".", " ")
    s = re.sub(r"\((hs|high school)\)", " ", s)
    s = re.sub(r"\bmathematics\b", "math", s)
    s = re.sub(r"\bscience\b", "sci", s)
    s = re.sub(r"\bsenior high\b", "high", s)
    s = re.sub(r"\b(the|of|for|and|campus)\b", " ", s)
    if loose:
        s = re.sub(r"\b(high school|high|school|schools|senior|sr|hs)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def team_name(raw: str) -> str:
    """Full official name as printed, without the '(HS)' / '(High School)' level tag."""
    n = clean_name(raw)
    n = re.sub(r"\s*\((?:HS|High School)\)\s*$", "", n, flags=re.I)
    return n.replace("‘", "'").replace("`", "'")


# ------------------------------------------------------------------------------ round robin
def rr_from_html(path: Path) -> list[dict[str, Any]]:
    """Division tables from a Score Center page -> [{name, teams:[{n, team, row, total, place, dtc, seed}]}]."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
    out = []
    for tab in soup.find_all("table"):
        # the heading names the division; the tables' summary attributes are copy-pasted and unreliable
        head = tab.find_previous(["h2", "h3", "h4"])
        title = clean_name(head.get_text(" ", strip=True)) if head else ""
        if "middle" in title.lower():
            continue
        hdr = [clean_name(c.get_text(" ", strip=True)) for c in tab.find("tr").find_all(["th", "td"])]
        ncols = sum(1 for h in hdr if re.fullmatch(r"\d+", h))
        extra = [h.lower() for h in hdr if h and not re.fullmatch(r"\d+", h) and h.lower() != "team"]
        name = re.sub(r"\s*Division$", "", title).strip()
        if name.lower() in ("high school", ""):
            name = "High School"
        teams = []
        for tr in tab.find_all("tr")[1:]:
            cells = [clean_name(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2 + ncols:
                continue
            n = int(re.sub(r"\D", "", cells[0]))
            row = cells[2:2 + ncols]
            rest = cells[2 + ncols:]
            info = dict(zip(extra, rest))
            tot = info.get("total points", "")
            m = re.match(r"^(\d+(?:\.\d+)?)\*?\s*\(?(?:(\d)(?:st|nd|rd|th))?\)?\s*\*?$", tot)
            if not m:
                raise ValueError(f"{path}: bad total {tot!r}")
            teams.append({
                "n": n, "team": team_name(cells[1]), "raw": cells[1],
                "row": [None if c == "" else int(float(c)) for c in row],
                "total": float(m.group(1)), "place": int(m.group(2)) if m.group(2) else None,
                "dtc": int(info["dtc rank"]) if info.get("dtc rank", "").isdigit() else None,
                "seed": int(info["seed"]) if info.get("seed", "").isdigit() else None,
                "starred": "*" in tot,
            })
        out.append({"name": name, "teams": teams})
    return out


def rr_from_yaml(path: Path) -> list[dict[str, Any]]:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for div, rows in d["divisions"].items():
        teams = []
        for n, raw, row, total, place, dtc in rows:
            teams.append({"n": n, "team": team_name(raw), "raw": raw,
                          "row": [None if c == "x" else int(c) for c in str(row).split()],
                          "total": float(total), "place": place, "dtc": dtc, "seed": None})
        out.append({"name": div, "teams": teams})
    return out


def check_rr(divs: list[dict[str, Any]], w: TournamentWriter | None = None) -> list[str]:
    """Row sums == Total Points; cell(i,j) + cell(j,i) == 2; diagonal blank."""
    problems = []
    for d in divs:
        ts = d["teams"]
        n = len(ts)
        for i, t in enumerate(ts):
            if len(t["row"]) != n or t["n"] != i + 1:
                problems.append(f"{d['name']}: row {t['team']} has {len(t['row'])} cells for {n} teams")
                continue
            if t["row"][i] is not None:
                problems.append(f"{d['name']}: {t['team']} diagonal {t['row'][i]}")
            s = sum(c for c in t["row"] if c is not None)
            if s != t["total"]:
                msg = f"{d['name']}: {t['team']} row sum {s} != total {t['total']}"
                if t.get("starred"):
                    # an asterisked (adjusted) total with no footnote on the page; the pairwise cells agree
                    if w is not None:
                        w.warn(msg + " (total marked '*' on the page; games taken from the grid cells)")
                else:
                    problems.append(msg)
            for j in range(n):
                if j != i and t["row"][j] is not None and ts[j]["row"][i] is not None:
                    if t["row"][j] + ts[j]["row"][i] != 2:
                        problems.append(f"{d['name']}: {t['team']} vs {ts[j]['team']}: "
                                        f"{t['row'][j]}/{ts[j]['row'][i]}")
        places = [t["place"] for t in ts if t["place"]]
        if len(places) != len(set(places)):
            problems.append(f"{d['name']}: duplicate places {places}")
    if w is not None:
        for p in problems:
            w.warn(p)
    return problems


def div_places(div: dict[str, Any]) -> dict[str, int]:
    """Division place for every team: the printed 1st-4th, others by Total Points then DTC rank (the
    official tie-break)."""
    ts = div["teams"]
    printed = {t["team"]: t["place"] for t in ts if t["place"]}
    rest = sorted((t for t in ts if not t["place"]), key=lambda t: (-t["total"], t["dtc"] or 99, t["n"]))
    out = dict(printed)
    k = max(printed.values(), default=0)
    for t in rest:
        k += 1
        out[t["team"]] = k
    return out


# ------------------------------------------------------------------------------ double elimination (PDF)
def _segments(page) -> list[dict[str, Any]]:
    """Group a page's words into text segments: same baseline, small gaps, same font weight."""
    words = page.extract_words(x_tolerance=2, y_tolerance=2, extra_attrs=["fontname", "size"])
    words.sort(key=lambda w: (round(w["top"]), w["x0"]))
    segs: list[dict[str, Any]] = []
    for wd in words:
        bold = "bold" in wd["fontname"].lower()
        last = segs[-1] if segs else None
        if (last and abs(last["top"] - wd["top"]) < 1.5 and 0 <= wd["x0"] - last["x1"] < 6
                and (last["bold"] == bold or wd["text"] in (":",) or GAME_RX.match(last["text"]))):
            last["text"] += " " + wd["text"]
            last["x1"] = wd["x1"]
            last["bottom"] = max(last["bottom"], wd["bottom"])
        else:
            segs.append({"text": wd["text"], "x0": wd["x0"], "x1": wd["x1"], "top": wd["top"],
                         "bottom": wd["bottom"], "bold": bold, "size": wd["size"]})
    for s in segs:
        s["text"] = clean_name(s["text"])
    return segs


def _page_bracket(page) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """-> (entries, game labels, round headers, summary box)."""
    segs = _segments(page)
    labels, subs, names, rounds = [], [], [], []
    box: dict[str, str] = {}
    for s in segs:
        t = s["text"]
        if s["size"] > 11 or "Double Elimination" in t:
            continue  # page title
        m = GAME_RX.match(t)
        if m and s["bold"] and not WIN_RX.match(t) and not LOSS_RX.match(t):
            labels.append({**s, "g": m.group("g").upper()})
            continue
        mr = re.match(r"^Round (\d+)$", t)
        if mr:
            rounds.append({**s, "round": int(mr.group(1))})
            continue
        if re.match(r"^\d{1,2}:\d\d [AP]M$", t) or t in ("Champions", "Champions!"):
            if t == "Champions!":
                subs.append({**s, "kind": "champion"})
            continue
        mb = re.match(r"^(Champions|Second Place|Third Place):\s*(.*)$", t)
        if mb:
            box[mb.group(1)] = mb.group(2)
            continue
        if not s["bold"] and (WIN_RX.match(t) or LOSS_RX.match(t) or PLACE_RX.match(t) or SEED_RX.match(t)):
            subs.append({**s, "kind": "sub"})
            continue
        names.append(s)
    # summary box values may be separate segments to the right of their captions
    for k in list(box):
        if not box[k]:
            cap = next(s for s in segs if s["text"].startswith(k + ":"))
            right = [s for s in segs if abs(s["top"] - cap["top"]) < 2 and s["x0"] > cap["x1"]]
            if right:
                box[k] = min(right, key=lambda s: s["x0"])["text"]
                names = [n for n in names if n is not min(right, key=lambda s: s["x0"])]
    entries = []
    for sb in subs:
        cands = [n for n in names if 0 < sb["top"] - n["top"] < 16 and n["x0"] < sb["x1"] + 8 and n["x1"] > sb["x0"] - 40]
        if not cands:
            continue
        nm = min(cands, key=lambda n: (sb["top"] - n["top"], abs(n["x1"] - sb["x1"])))
        entries.append({"name": nm["text"], "label": sb["text"], "kind": sb["kind"],
                        "x0": min(nm["x0"], sb["x0"]), "x1": max(nm["x1"], sb["x1"]), "sx1": sb["x1"],
                        "y": (nm["bottom"] + sb["top"]) / 2})
    return entries, labels, rounds, box


def de_from_pdfs(paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Reconstruct every DE game from the bracket PDFs.

    A game label "GM-n" sits between its two input slots, right-aligned with them; the slot entries are a
    bold team name over a label line. The game's winner is the entry labelled "Winner GM-n" (or, for the
    final, the "Champions" box)."""
    import pdfplumber

    games: dict[str, dict[str, Any]] = {}
    winners: dict[str, set[str]] = defaultdict(set)
    losers_named: dict[str, set[str]] = defaultdict(set)
    box: dict[str, str] = {}
    for path in paths:
        bracket = "one-loss" if "one" in path.name.lower() else "no-loss"
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                entries, labels, rounds, b = _page_bracket(page)
                box.update({k: v for k, v in b.items() if v})
                for e in entries:
                    m = WIN_RX.match(e["label"])
                    if m:
                        winners[m.group("g").upper()].add(e["name"])
                    m = LOSS_RX.match(e["label"])
                    if m:
                        losers_named[m.group("g").upper()].add(e["name"])
                for lb in labels:
                    col = [e for e in entries if e["kind"] == "sub" and abs(e["sx1"] - lb["x1"]) < 14]
                    above = [e for e in col if e["y"] < lb["top"]]
                    below = [e for e in col if e["y"] > lb["bottom"]]
                    if not above or not below:
                        continue
                    a = max(above, key=lambda e: e["y"])
                    c = min(below, key=lambda e: e["y"])
                    rnd = None
                    if rounds:
                        rnd = min(rounds, key=lambda r: abs(r["x1"] - lb["x1"]))["round"]
                    g = lb["g"]
                    rec = {"game": g, "round": rnd, "bracket": bracket, "team1": a["name"], "label1": a["label"],
                           "team2": c["name"], "label2": c["label"]}
                    if g in games and (games[g]["team1"], games[g]["team2"]) != (rec["team1"], rec["team2"]):
                        raise ValueError(f"{path.name}: GM-{g} read twice with different teams")
                    games[g] = rec
    out = []
    for g, rec in games.items():
        ws = winners.get(g, set())
        if len(ws) > 1:
            raise ValueError(f"GM-{g}: several winners {ws}")
        rec["winner"] = next(iter(ws)) if ws else None
        if rec["winner"] is None and box.get("Champions") in (rec["team1"], rec["team2"]):
            rec["winner"] = box["Champions"]
        # the championship game joins the no-loss winner and the one-loss (lettered) winner
        srcs = [WIN_RX.match(rec[f"label{k}"]) for k in ("1", "2")]
        if all(srcs) and {s.group("g").isdigit() for s in srcs} == {True, False}:
            rec["bracket"] = "final"
        lost = losers_named.get(g)
        rec["loser_named"] = next(iter(lost)) if lost else None
        out.append(rec)
    return out, box


def de_from_yaml(path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    games = []
    for g in d["games"]:
        games.append({**g, "game": str(g["game"]), "loser_named": None})
    # losers named in "One-Loss from GM-n" slots
    lost = {}
    for g in games:
        for k in ("1", "2"):
            m = LOSS_RX.match(g[f"label{k}"])
            if m:
                lost[m.group("g").upper()] = g[f"team{k}"]
    for g in games:
        g["loser_named"] = lost.get(g["game"])
    return games, {"Champions": d.get("champion") or ""}


def _game_sort_key(g: dict[str, Any]) -> tuple:
    gid = g["game"]
    return (g["round"] or 0, 0 if gid.isdigit() else 1, int(gid) if gid.isdigit() else (len(gid), gid))


def check_de(games: list[dict[str, Any]], champion: str | None, w: TournamentWriter) -> None:
    losses: Counter[str] = Counter()
    for g in sorted(games, key=_game_sort_key):
        if g["winner"] not in (g["team1"], g["team2"]):
            raise ValueError(f"GM-{g['game']}: winner {g['winner']!r} not in ({g['team1']!r}, {g['team2']!r})")
        loser = g["team2"] if g["winner"] == g["team1"] else g["team1"]
        if g.get("loser_named") and g["loser_named"] != loser:
            raise ValueError(f"GM-{g['game']}: loser {loser!r} but one-loss slot names {g['loser_named']!r}")
        for k in ("1", "2"):
            m = WIN_RX.match(g[f"label{k}"])
            if m:
                src = next((x for x in games if x["game"] == m.group("g").upper()), None)
                if src is None or src["winner"] != g[f"team{k}"]:
                    raise ValueError(f"GM-{g['game']}: slot {g[f'label{k}']} = {g[f'team{k}']!r} "
                                     f"but that game's winner is {src and src['winner']!r}")
            m = LOSS_RX.match(g[f"label{k}"])
            if m:
                src = next((x for x in games if x["game"] == m.group("g").upper()), None)
                if src is None or g[f"team{k}"] not in (src["team1"], src["team2"]) or src["winner"] == g[f"team{k}"]:
                    raise ValueError(f"GM-{g['game']}: slot {g[f'label{k}']} = {g[f'team{k}']!r} did not lose that game")
        losses[loser] += 1
    over = [t for t, n in losses.items() if n > 2]
    if over:
        raise ValueError(f"teams with more than two DE losses: {over}")
    if champion:
        final = max(games, key=_game_sort_key)
        if final["winner"] != champion:
            raise ValueError(f"last DE game GM-{final['game']} won by {final['winner']!r}, champion is {champion!r}")
        if losses[champion] > 1:
            w.warn(f"champion {champion} has {losses[champion]} DE losses")


def de_finishes(games: list[dict[str, Any]]) -> dict[str, str]:
    """Final placing of every DE team from the elimination order: champion 1, final loser 2, then teams
    grouped by the time slot of their second loss (later = better), e.g. '5-6', '9-12'."""
    losses: Counter[str] = Counter()
    elim_round: dict[str, int] = {}
    teams: set[str] = set()
    last = max(games, key=_game_sort_key)
    for g in sorted(games, key=_game_sort_key):
        teams.update((g["team1"], g["team2"]))
        loser = g["team2"] if g["winner"] == g["team1"] else g["team1"]
        losses[loser] += 1
        if losses[loser] == 2 or g is last:
            elim_round[loser] = g["round"] or 0
    champ = last["winner"]
    out = {champ: "1"}
    groups: dict[int, list[str]] = defaultdict(list)
    for t, r in elim_round.items():
        if t != champ:
            groups[r].append(t)
    pos = 2
    for r in sorted(groups, reverse=True):
        ts = sorted(groups[r])
        lab = str(pos) if len(ts) == 1 else f"{pos}-{pos + len(ts) - 1}"
        for t in ts:
            out[t] = lab
        pos += len(ts)
    missing = teams - set(out)
    if missing:
        raise ValueError(f"no finish for {missing}")
    return out


# ------------------------------------------------------------------------------ hints
def regional_winners(path: Path) -> list[tuple[str, str, str]]:
    """'School, City, State' lines from a Press Releases of Regional Winners page (or a finals teams
    list) -> [(name, city, ST)]."""
    if not path.exists():
        return []
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
    art = soup.find("article") or soup
    out = []
    for line in art.get_text("\n").split("\n"):
        t = clean_name(line)
        parts = [p.strip() for p in t.split(",")]
        if len(parts) >= 3 and _state_code(parts[-1]) and "middle" not in t.lower():
            out.append((", ".join(parts[:-2]), parts[-2], _state_code(parts[-1])))
    return out


def match_hint(name: str, hints: list[tuple[str, str, str]]) -> tuple[str, str, str] | None:
    """Strict key match first, then a loose key match if it is unique."""
    for loose in (False, True):
        k = _key(name, loose)
        cands = {h for h in hints if _key(h[0], loose) == k}
        if len(cands) == 1:
            return next(iter(cands))
        if len(cands) > 1:
            return None
    return None


# ------------------------------------------------------------------------------ main parser
def parse(t: Tournament, w: TournamentWriter, rr: str = "round_robin.html", de: list[str] | None = None,
          de_transcribed: str | None = None, champion: str | None = None, hints: str | None = "regional_winners.html",
          teams_page: str | None = None, short_names: dict[str, str] | None = None,
          school_states: dict[str, str] | None = None) -> None:
    """In-person Finals (2022-): round-robin divisions + double-elimination brackets.

    rr: round_robin.html (Score Center page) or rr_transcribed.yaml.
    de: bracket PDFs; de_transcribed: hand transcription (YAML) for image-only brackets.
    champion: expected champion's full name (checked against the last DE game).
    hints: regional-winners page for city/state; teams_page: an alternative 'School, City, State' list.
    short_names: manual short->full name map for bracket names not labelled with a division place.
    school_states: manual {full name: state} hints for teams no page lists.
    """
    rrp = t.raw(rr)
    divs = rr_from_yaml(rrp) if rrp.suffix in (".yaml", ".yml") else rr_from_html(rrp)
    probs = check_rr(divs, w)
    if probs:
        raise ValueError(f"{t.id}: round-robin grid inconsistent: {probs[:5]}")

    hint_list: list[tuple[str, str, str]] = []
    for h in (hints, teams_page):
        if h:
            hint_list += regional_winners(t.raw(h))
    state_of: dict[str, str] = {}
    for d in divs:
        for tm in d["teams"]:
            h = match_hint(tm["team"], hint_list)
            st = h[2] if h else ""
            if not st and school_states:
                st = school_states.get(tm["team"], "")
            if not st:
                w.warn(f"no city/state found for {tm['team']}")
            state_of[tm["team"]] = st
            w.team(tm["team"], school=tm["team"], state=st,
                   notes=f"{d['name']} division" + (f", {h[1]}, {h[2]}" if h else ""))

    # ---- round-robin games: one per pairing
    for d in divs:
        ts = d["teams"]
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                c = ts[i]["row"][j]
                res = {2: "1", 0: "2", 1: "T"}[c]
                w.game(ts[i]["team"], ts[j]["team"], stage="rr", round=d["name"], seq=1, result=res,
                       game_id=f"RR-{_slug(d['name'])}-{ts[i]['n']}-{ts[j]['n']}",
                       notes=f"{d['name']} division; 2/1/0 grid (no scores)")

    # ---- double elimination
    if de_transcribed:
        games, box = de_from_yaml(t.raw(de_transcribed))
    else:
        games, box = de_from_pdfs([t.raw(f) for f in (de or [])])
    by_place = {(d["name"].lower(), tm["place"]): tm["team"] for d in divs for tm in d["teams"] if tm["place"]}
    by_seed = {tm["seed"]: tm["team"] for d in divs for tm in d["teams"] if tm["seed"]}
    short: dict[str, str] = dict(short_names or {})
    for g in games:
        for k in ("1", "2"):
            nm, lab = g[f"team{k}"], g[f"label{k}"]
            m, ms = PLACE_RX.match(lab), SEED_RX.match(lab)
            full = None
            if m:
                full = by_place.get((m.group("div").lower(), int(m.group("place"))))
                if full is None:
                    raise ValueError(f"GM-{g['game']}: no round-robin team for {lab!r}")
            elif ms:
                full = by_seed.get(int(ms.group("seed")))
            if full:
                if short.get(nm, full) != full:
                    raise ValueError(f"short name {nm!r} maps to {short[nm]!r} and {full!r}")
                short[nm] = full
    unknown = {g[f"team{k}"] for g in games for k in ("1", "2") if g[f"team{k}"] not in short}
    if unknown:
        raise ValueError(f"{t.id}: bracket names without a round-robin team: {sorted(unknown)}")
    for g in games:
        for k in ("1", "2", ""):
            key = f"team{k}" if k else "winner"
            g[key] = short[g[key]]
        if g.get("loser_named"):
            g["loser_named"] = short.get(g["loser_named"], g["loser_named"])
    champ_full = short.get(box.get("Champions") or "", box.get("Champions") or None)
    if champion and champ_full and champion != champ_full:
        raise ValueError(f"bracket champion {champ_full!r} != expected {champion!r}")
    check_de(games, champion or champ_full, w)
    for g in sorted(games, key=_game_sort_key):
        res = "1" if g["winner"] == g["team1"] else "2"
        w.game(g["team1"], g["team2"], stage="playoff", round=f"DE{g['round']}", seq=10 + (g["round"] or 0),
               result=res, game_id=f"GM-{g['game']}",
               notes=f"{g['bracket']} bracket; {g['label1']} vs {g['label2']}")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
