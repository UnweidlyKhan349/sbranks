"""Earth and Space Scrimmages 1-3 (online, Discord): individual 1v1 Earth & Space competitions.

Every competitor is an individual; we record each one as a "team" named after the person and
as that team's only player. The organisers' sheets share one template family:

* "RR Schedule (Table)" / "RR Schedule (Adv|Novice)": per group a crosstable whose cells are the
  date window of the pairing; the "RR k: <dates>" headers turn a window into a round number.
* "RR Results": per group, each competitor's W/L/T and own score in every round.
* "RR Crosstables (...)" (ESS3): row competitor's score against the column competitor.
* Brackets ("SE Results", "DE Results", "Advanced DE", "Novice SE"): numbered games; the game
  number cell is followed by name/score on that row and the next row. "58+T" = won the
  tiebreaker at 58. "BYE" entries are skipped.

Scoring: correct interrupt 6, correct 4, incorrect interrupt -4. Player stats are converted to
standard counts: correct = interrupts + non-interrupt corrects, negs = incorrect interrupts and
points = 4*correct - 4*negs (the 6-point interrupt bonus is not kept).
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, load_grids

_DATE = re.compile(r"^\d{1,2}/\d{1,2}\s*-\s*\d{1,2}/\d{1,2}$")
_EMOJI = re.compile(r"[^\w\s.'\-]")


def _name(s) -> str:
    return clean_name(_EMOJI.sub("", clean_name(s)))


def _norm_date(s: str) -> str:
    return re.sub(r"\s+", "", s)


def schedule_rounds(g: Grid) -> dict[frozenset, int]:
    """Crosstable of date windows -> {frozenset({p, q}): round}."""
    date_round: dict[str, int] = {}
    for r, c in g.find(r"^RR\s*\d+\s*:"):
        for m in re.finditer(r"RR\s*(\d+)\s*:\s*(\d{1,2}/\d{1,2}\s*-\s*\d{1,2}/\d{1,2})", g.text(r, c)):
            date_round[_norm_date(m.group(2))] = int(m.group(1))
    out: dict[frozenset, int] = {}
    for r in range(g.nrows):
        for c in range(g.ncols):
            t = g.text(r, c)
            if not _DATE.match(t):
                continue
            rnd = date_round.get(_norm_date(t))
            if rnd is None:
                continue
            cc = c - 1
            while cc >= 0 and (not g.text(r, cc) or _DATE.match(g.text(r, cc))):
                cc -= 1
            rr = r - 1
            while rr >= 0 and (not g.text(rr, c) or _DATE.match(g.text(rr, c))):
                rr -= 1
            if cc < 0 or rr < 0:
                continue
            out[frozenset((_name(g.text(r, cc)), _name(g.text(rr, c))))] = rnd
    return out


def rr_results(g: Grid) -> dict[str, dict[str, list[tuple[str, float | None]]]]:
    """{group: {player: [(W|L|T, own score) per round]}}"""
    out: dict[str, dict[str, list]] = {}
    for r, c in g.find(r"^RR\s*1$"):
        lab = c - 1
        group = g.text(r - 1, lab) or f"group@{r},{lab}"
        nr = 0
        while g.text(r, c + 2 * nr).replace(" ", "").upper() == f"RR{nr + 1}":
            nr += 1
        players = {}
        rr = r + 1
        while rr < g.nrows and g.text(rr, lab):
            res = []
            for k in range(nr):
                res.append((g.text(rr, c + 2 * k).upper(), g.num(rr, c + 2 * k + 1)))
            players[_name(g.text(rr, lab))] = res
            rr += 1
        out[group] = players
    return out


def crosstable_scores(g: Grid) -> dict[tuple[str, str], float]:
    """{(row player, col player): row player's score}."""
    def is_label(r: int, c: int) -> bool:
        return bool(g.text(r, c)) and g.num(r, c) is None

    out = {}
    for r in range(g.nrows):
        for c in range(g.ncols):
            v = g.num(r, c)
            if v is None:
                continue
            cc = c - 1
            while cc >= 0 and not is_label(r, cc):
                cc -= 1
            rr = r - 1
            while rr >= 0 and not is_label(rr, c):
                rr -= 1
            if cc < 0 or rr < 0:
                continue
            out[(_name(g.text(r, cc)), _name(g.text(rr, c)))] = v
    return out


def bracket_games(g: Grid) -> list[dict]:
    """Numbered bracket games: [{no, p1, s1, p2, s2, tb_winner}]"""
    games = []
    for r in range(g.nrows - 1):
        for c in range(g.ncols - 2):
            no = g.num(r, c)
            if no is None or not g.text(r, c + 1) or g.num(r, c + 1) is not None:
                continue
            if no != int(no) or no <= 0:
                continue
            p1, p2 = _name(g.text(r, c + 1)), _name(g.text(r + 1, c + 1))
            t1, t2 = g.text(r, c + 2), g.text(r + 1, c + 2)
            if not p1 or not p2 or "BYE" in (p1.upper(), p2.upper()):
                continue
            tb = None
            sc = []
            for p, t in ((p1, t1), (p2, t2)):
                m = re.match(r"^(-?\d+(?:\.\d+)?)\s*(\+\s*T)?$", t.replace(" ", ""))
                if not m:
                    sc.append(None)
                    continue
                sc.append(float(m.group(1)))
                if m.group(2):
                    tb = p
            games.append({"no": int(no), "p1": p1, "s1": sc[0], "p2": p2, "s2": sc[1], "tb_winner": tb,
                          "col": c})
    return sorted(games, key=lambda x: x["no"])


def _forfeit_like(s1, s2) -> bool:
    if s1 is None or s2 is None:
        return False
    lo, hi = sorted((s1, s2))
    return lo == 0 and hi <= 4


def _add_game(w: TournamentWriter, a: str, b: str, sa, sb, *, stage: str, rnd: str, seq: int,
              wl: tuple[str, str] | None = None, tb_winner: str | None = None, note: str = "") -> None:
    notes = [note] if note else []
    res = ""
    forfeit = False
    if wl and sa is not None and sb is not None:
        exp = "W" if sa > sb else "L" if sa < sb else "T"
        if wl[0] != exp:
            # score and W/L disagree: forfeit / adjudicated result
            forfeit = True
            res = {"W": "1", "L": "2", "T": "T"}.get(wl[0], "")
            notes.append(f"sheet marks {a} {wl[0]} with scores {sa:g}-{sb:g}; treated as forfeit")
            sa = sb = None
    if sa is not None and sb is not None and _forfeit_like(sa, sb):
        forfeit = True
        notes.append(f"{sa:g}-{sb:g}: treated as forfeit")
    if tb_winner and sa == sb:
        notes.append(f"{tb_winner} won the tiebreaker")
    elif tb_winner:
        notes.append(f"{tb_winner} won after a tiebreaker")
    for p in (a, b):
        w.team(p, players=[p])
    if sa is None or sb is None:
        if not res:
            w.warn(f"{stage} {rnd} {a} vs {b}: no usable score")
            return
        w.game(a, b, stage=stage, round=rnd, seq=seq, result=res, forfeit=forfeit, notes="; ".join(notes))
    else:
        w.game(a, b, sa, sb, stage=stage, round=rnd, seq=seq, forfeit=forfeit, notes="; ".join(notes))


def parse_rr(w: TournamentWriter, grids: dict[str, Grid], schedule_tab: str, results_tab: str,
             crosstable_tab: str | None = None, division: str = "") -> list[list[str]]:
    rounds = schedule_rounds(grids[schedule_tab])
    res = rr_results(grids[results_tab])
    cross = crosstable_scores(grids[crosstable_tab]) if crosstable_tab else {}
    nmax = 0
    for group, players in res.items():
        names = list(players)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                rnd = rounds.get(frozenset((a, b)))
                if rnd is None:
                    w.warn(f"{group}: no scheduled round for {a} vs {b}")
                    continue
                nmax = max(nmax, rnd)
                wa, sa = players[a][rnd - 1]
                wb, sb = players[b][rnd - 1]
                if cross:
                    ca, cb = cross.get((a, b)), cross.get((b, a))
                    if (ca, cb) != (sa, sb):
                        w.warn(f"{group} RR{rnd} {a}-{b}: results {sa}-{sb} vs crosstable {ca}-{cb}")
                if {wa, wb} not in ({"W", "L"}, {"T"}):
                    w.warn(f"{group} RR{rnd} {a} {wa} vs {b} {wb}: inconsistent W/L")
                _add_game(w, a, b, sa, sb, stage="rr", rnd=f"{division}RR{rnd}", seq=rnd,
                          wl=(wa, wb), note=group if group.lower().startswith("group") else f"group {group}")
    return [list(p) for p in res.values()]


def parse_bracket(w: TournamentWriter, g: Grid, seq0: int, label: str = "DE", stage: str = "playoff") -> None:
    games = bracket_games(g)
    cols = sorted({x["col"] for x in games})
    heads = {}
    for r, c in g.find(r"^(DE|SE)\s*[\d.]+\s*:"):
        if r <= 3:
            heads[c] = re.match(r"^((?:DE|SE)\s*[\d.]+)", g.text(r, c)).group(1)
    for x in games:
        k = cols.index(x["col"]) + 1
        _add_game(w, x["p1"], x["p2"], x["s1"], x["s2"], stage=stage,
                  rnd=heads.get(x["col"], f"{label} {k}"), seq=seq0 + k, tb_winner=x["tb_winner"],
                  note=f"game {x['no']}")


# ---------------------------------------------------------------- player stats
def _resolve(w: TournamentWriter, label: str, groups: list[list[str]]) -> str:
    """Stats rows are labelled '[g.p] Name' or have 'g.p' in the first column; map the
    group/position to the round-robin spelling of the name (stats tabs have a few typos)."""
    m = re.match(r"^\s*\[?\s*(\d+)\.(\d+)\s*\]?\s*(.*)$", label)
    if not m:
        return _name(label)
    gi, pi, nm = int(m.group(1)), int(m.group(2)), _name(m.group(3))
    if 1 <= gi <= len(groups) and 1 <= pi <= len(groups[gi - 1]):
        rr = groups[gi - 1][pi - 1]
        if nm and nm != rr:
            w.warn(f"stats name {nm!r} at {gi}.{pi} -> {rr!r}")
        return rr
    return nm

def stats_fractions(w: TournamentWriter, g: Grid, games_played: dict[str, int], groups: list[list[str]],
                    per_game: int = 20, earth_per_game: int = 12, space_per_game: int = 8) -> None:
    """ESS1 'Raw' tab: per competitor fraction of questions scored 6/4/0/-4 (overall, Earth,
    Space). Counts = fraction x questions heard (20 per round: 12 Earth + 8 Space)."""
    hdr = g.row_texts(0)
    col = {h: i for i, h in enumerate(hdr) if h}
    for r in range(1, g.nrows):
        if not _name(g.text(r, 1)):
            continue
        gpos = g.cell(r, 0)
        label = f"{float(gpos):.1f} {g.text(r, 1)}" if num(gpos) is not None else g.text(r, 1)
        name = _resolve(w, label, groups)
        gp = games_played.get(name)
        if not gp:
            w.warn(f"stats: {name} has no RR games")
            continue
        out = {}
        for part, n, pref in (("overall", per_game * gp, ""), ("earth", earth_per_game * gp, "Earth "),
                              ("space", space_per_game * gp, "Space ")):
            k6, k4, k0, kn = (g.num(r, col[pref + x]) for x in (("6", "4", "0", "-4") if pref else ("6.0", "4.0", "0.0", "-4.0")))
            cnt = [x * n for x in (k6, k4, k0, kn)]
            ints = [round(x) for x in cnt]
            tol = 0.5 * n * (0.005 if not pref else 0.0005) + 1e-6
            if any(abs(x - i) > max(tol, 0.06) for x, i in zip(cnt, ints)) or sum(ints) != n:
                w.warn(f"stats: {name} {part} fractions do not give whole counts of {n}: {cnt}")
            out[part] = ints
        e, s, o = out["earth"], out["space"], out["overall"]
        if [a + b for a, b in zip(e, s)] != o:
            w.warn(f"stats: {name} Earth+Space {e}+{s} != overall {o}")
        ppg = g.num(r, col["PPG"])
        pts6 = 6 * o[0] + 4 * o[1] - 4 * o[3]
        if ppg is not None and abs(pts6 / gp - ppg) > 0.05:
            w.warn(f"stats: {name} PPG {ppg} != {pts6}/{gp}")
        # the sheet's "0" bucket is incorrect *or* no buzz, so it is not a 0s count
        correct, negs = o[0] + o[1], o[3]
        for subj in ("overall", "ess"):
            w.player_stat(name, name, subj, scope="rr", gp=gp, tuh=per_game * gp, correct=correct,
                          negs=negs, points=4 * correct - 4 * negs)


def stats_per_round(w: TournamentWriter, grids: dict[str, Grid], tabs: list[str], cumulative: str,
                    game_of: dict[tuple[int, str], str], groups: list[list[str]]) -> None:
    """ESS2 'RRk Player Stats': per competitor per question C / IC / P (+ totals)."""
    tot = defaultdict(lambda: defaultdict(float))
    for k, tab in enumerate(tabs, start=1):
        g = grids[tab]
        hdr = g.row_texts(1)
        qcols = [i for i, h in enumerate(hdr) if re.match(r"^Q\d+$", h)]
        for r in range(2, g.nrows):
            raw = g.text(r, 0)
            if not raw:
                continue
            name = _resolve(w, raw, groups)
            marks = [g.text(r, c).upper() for c in qcols]
            c4 = marks.count("C")
            c6 = marks.count("IC")
            pn = marks.count("P")
            t = tot[name]
            t["gp"] += 1
            t["tuh"] += len(qcols)
            t["c4"] += c4
            t["c6"] += c6
            t["neg"] += pn
            gid = game_of.get((k, name))
            if gid:
                w.player_game_stat(gid, name, name, "ess", correct=c4 + c6, negs=pn)
                w.player_game_stat(gid, name, name, "overall", correct=c4 + c6, negs=pn)
            else:
                w.warn(f"stats RR{k}: no game found for {name}")
    # cross-check with the cumulative tab
    g = grids[cumulative]
    hdr = g.row_texts(1)
    comb = hdr.index("C", 14) if "C" in hdr[14:] else None
    for r in range(2, g.nrows):
        if not g.text(r, 0):
            continue
        name = _resolve(w, g.text(r, 0), groups)
        t = tot.get(name)
        if t is None:
            w.warn(f"cumulative stats: {name} missing from per-round tabs")
            continue
        gp = g.num(r, 1)
        c4, c6, pn = (g.num(r, comb + i) for i in range(3))
        if (gp, c4, c6, pn) != (t["gp"], t["c4"], t["c6"], t["neg"]):
            w.warn(f"cumulative stats {name}: {(gp, c4, c6, pn)} != per-round {(t['gp'], t['c4'], t['c6'], t['neg'])}")
    for name, t in tot.items():
        correct, negs = t["c4"] + t["c6"], t["neg"]
        for subj in ("overall", "ess"):
            w.player_stat(name, name, subj, scope="rr", gp=t["gp"], tuh=t["tuh"], correct=correct,
                          negs=negs, points=4 * correct - 4 * negs)


# ---------------------------------------------------------------- entry points
def parse_ess1(t: Tournament, w: TournamentWriter) -> None:
    g = load_grids(t.raw("results.xlsx"))
    groups = parse_rr(w, g, "RR Schedule (Table)", "RR Results")
    parse_bracket(w, g["SE Results"], seq0=5, label="SE")
    st = load_grids(t.raw("stats.xlsx"))
    gp = defaultdict(int)
    for row in w.rows["games"]:
        if row["stage"] == "rr" and not row["forfeit"]:
            gp[row["team1"]] += 1
            gp[row["team2"]] += 1
    stats_fractions(w, st["Raw"], gp, groups)


def parse_ess2(t: Tournament, w: TournamentWriter) -> None:
    g = load_grids(t.raw("hub.xlsx"))
    groups = parse_rr(w, g, "RR Schedule (Table)", "RR Results")
    parse_bracket(w, g["DE Results"], seq0=5, label="DE")
    game_of = {}
    for row in w.rows["games"]:
        if row["stage"] == "rr":
            k = int(re.sub(r"\D", "", row["round"]))
            game_of[(k, row["team1"])] = game_of[(k, row["team2"])] = row["game_id"]
    st = load_grids(t.raw("stats.xlsx"))
    tabs = [f"RR{k} Player Stats" for k in range(1, 6) if f"RR{k} Player Stats" in st]
    stats_per_round(w, st, tabs, "Cumulative Player Stats", game_of, groups)


def parse_ess3(t: Tournament, w: TournamentWriter, division: str = "Adv") -> None:
    g = load_grids(t.raw("results.xlsx"))
    parse_rr(w, g, f"RR Schedule ({division})", f"RR Results ({division})",
             crosstable_tab=f"RR Crosstables ({division})")
    if division.lower().startswith("adv"):
        parse_bracket(w, g["Advanced DE"], seq0=7, label="DE")
    else:
        parse_bracket(w, g["Novice SE"], seq0=7, label="SE")
