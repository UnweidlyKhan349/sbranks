"""Berkeley Science Bowl Dec 2023: question-level data from the per-game scoring interfaces.

Sources (raw/<id>/):
  * backend.xlsx        the scoring backend sheet: 'Round Robin Matchups' / 'DE Matchups'
                        (teams, round, division, scores, interface id), 'Check-In Import'
                        (school + roster), 'Direct DE Bracket' (forfeit of the reset final).
  * interfaces/<n>.csv  first tab ('Volunteer Side') of every game's interface sheet, fetched
                        by tools/g5_berkeley_interfaces.py. Layout:
        row 0   ... 'Team B:' score at col 7 ... 'Team A:' score at col 11
        row 4/5 'Team A:' / 'Team B:' name in col 1
        rows after 'Half 1:' / 'Half 2:'  lineup: slot label (col 0) | player (col 1)
        'Question # for the last question read in first half:' | n
        question rows: col 4 in {TU, Penalty, B}, col 5 = question number,
        cols 6..14 = A-Four, A-Three, A-Captain, A-One, B-One, B-Captain, B-Three, B-Four,
        No correct answers (TRUE marks the buzzing slot; for B rows the captain columns
        mark which team converted the bonus), col 18 = category.
"""
from __future__ import annotations

import csv
from collections import defaultdict

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import load_grids

SLOTS = ["A-Four", "A-Three", "A-Captain", "A-One", "B-One", "B-Captain", "B-Three", "B-Four",
         "No correct answers"]
LINEUP_LABELS = {"A Four:": "A-Four", "A Three:": "A-Three", "A Captain:": "A-Captain",
                 "A One:": "A-One", "B One:": "B-One", "B Captain:": "B-Captain",
                 "B Three:": "B-Three", "B Four:": "B-Four"}


def _read_interface(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    cell = lambda r, c: rows[r][c] if r < len(rows) and c < len(rows[r]) else ""  # noqa: E731
    out = {"team_a": clean_name(cell(4, 1)), "team_b": clean_name(cell(5, 1)),
           "score_b": num(cell(0, 7)), "score_a": num(cell(0, 11)),
           "lineups": {1: {}, 2: {}}, "half_q": None, "questions": defaultdict(dict)}
    half = None
    for r, row in enumerate(rows):
        c0 = row[0].strip() if row else ""
        if c0 == "Half 1:":
            half = 1
        elif c0 == "Half 2:":
            half = 2
        elif c0 in LINEUP_LABELS and half:
            out["lineups"][half][LINEUP_LABELS[c0]] = clean_name(cell(r, 1))
        elif c0.startswith("Question #"):
            out["half_q"] = num(cell(r, 1))
        kind = cell(r, 4)
        if kind in ("TU", "Penalty", "B") and num(cell(r, 5)) is not None:
            q = int(num(cell(r, 5)))
            flags = {s: cell(r, 6 + i).upper() == "TRUE" for i, s in enumerate(SLOTS)}
            out["questions"][q][kind] = flags
            out["questions"][q]["category"] = cell(r, 18)
    return out


def parse(t: Tournament, w: TournamentWriter, backend: str = "backend.xlsx",
          rr_rounds: int = 5) -> None:
    grids = load_grids(t.raw(backend))
    ci = grids["Check-In Import"]
    roster: dict[str, list[str]] = {}
    for r in range(1, ci.nrows):
        if ci.text(r, 1):
            roster[ci.text(r, 1)] = [ci.text(r, c) for c in range(4, 9) if ci.text(r, c)]
            w.team(ci.text(r, 1), school=ci.text(r, 0), players=roster[ci.text(r, 1)])

    tot = defaultdict(lambda: defaultdict(float))       # (player, team, subj) -> stats
    games_played = defaultdict(set)                      # (player, team) -> game ids
    # Every game of a round uses the same packet, so a scoresheet whose category lookup
    # failed (#N/A) takes the category of the same question from the round's other games.
    ivs, catmap = {}, defaultdict(set)
    for tab in ("Round Robin Matchups", "DE Matchups"):
        g = grids[tab]
        hdr = g.row_texts(0)
        for r in range(1, g.nrows):
            d = dict(zip(hdr, g.row_texts(r)))
            if not d.get("First Team"):
                continue
            idx = str(int(float(d["Interface Index"])))
            path = t.raw_dir / "interfaces" / f"{idx}.csv"
            if path.exists():
                ivs[idx] = iv = _read_interface(path)
                rnd = int(float(d["Round #"]))
                for q, qd in iv["questions"].items():
                    subj = normalize_subject(qd.get("category"))
                    if subj:
                        catmap[(rnd, q)].add(subj)
    for k, v in catmap.items():
        if len(v) > 1:
            w.warn(f"round {k[0]} question {k[1]}: conflicting categories {sorted(v)}")
    for tab, stage in (("Round Robin Matchups", "rr"), ("DE Matchups", "playoff")):
        g = grids[tab]
        hdr = g.row_texts(0)
        for r in range(1, g.nrows):
            d = dict(zip(hdr, g.row_texts(r)))
            if not d.get("First Team"):
                continue
            idx = str(int(float(d["Interface Index"])))
            rnd = int(float(d["Round #"]))
            a, b = d["First Team"], d["Second Team"]
            sa, sb = num(d["First Team Score"]), num(d["Second Team Score"])
            if stage == "rr":
                label, seq = f"RR{rnd}", rnd
            else:
                label, seq = f"DE{rnd - rr_rounds}", rnd
            if d.get("Round Done") != "True" or sa is None:
                # The bracket-reset final was not played: North Hollywood forfeited it.
                dbr = grids.get("Direct DE Bracket")
                forfeit_by = None
                if dbr is not None:
                    for rr_, cc in dbr.find(r"^Forfeit$"):
                        forfeit_by = dbr.text(rr_, cc - 1)
                if forfeit_by and forfeit_by in (a, b):
                    winner = b if forfeit_by == a else a
                    w.game(winner, forfeit_by, stage=stage, round="Final 2", seq=seq,
                           result="1", forfeit=True, game_id=f"i{idx}",
                           notes=f"{forfeit_by} forfeited the bracket-reset final")
                else:
                    w.warn(f"interface {idx} {a} vs {b}: not played")
                continue
            if stage == "playoff" and rnd >= rr_rounds + 8:
                label = "Final"
            gid = w.game(a, b, sa, sb, stage=stage, round=label, seq=seq, game_id=f"i{idx}",
                         notes=f"division {d['Division']}" if d.get("Division") else "")
            if idx not in ivs:
                w.warn(f"interface {idx}: no scoresheet")
                continue
            iv = ivs[idx]
            for q, qd in iv["questions"].items():
                if not normalize_subject(qd.get("category")) and len(catmap.get((rnd, q), ())) == 1:
                    qd["category"] = next(iter(catmap[(rnd, q)]))
            for half in (1, 2):
                for slot, p in iv["lineups"][half].items():
                    iv["lineups"][half][slot] = full_name(p, roster.get(a if slot.startswith("A-") else b, []))
            _game_stats(w, gid, a, b, sa, sb, iv, tot, games_played, stage)

    # scope 'all' = every game, overall only (DE scoresheets carry no categories);
    # scope 'rr' = round robin, overall + subjects.
    for (p, team, scope, subj), s in sorted(tot.items()):
        w.player_stat(p, team, subj, scope=scope, gp=len(games_played[(p, team, scope)]),
                      tuh=s["tuh"], correct=s["correct"], negs=s["negs"],
                      points=4 * s["correct"] - 4 * s["negs"])


def full_name(p: str, roster: list[str]) -> str:
    """Expand a truncated lineup name ('Suzuko Osa') to the unique roster name it
    abbreviates ('Suzuko Ohshima': same first name, surname sharing a prefix)."""
    if not p or p in roster:
        return p
    toks = p.lower().split()
    cands = [r for r in roster if r.lower().startswith(p.lower())]
    if not cands and len(toks) >= 2:
        cands = [r for r in roster if r.lower().split()[0] == toks[0]
                 and len(r.split()) >= 2 and r.lower().split()[-1][:1] == toks[-1][:1]]
    return cands[0] if len(cands) == 1 else p


def _game_stats(w, gid, a, b, sa, sb, iv, tot, games_played, stage) -> None:
    if (iv["team_a"], iv["team_b"]) != (a, b):
        w.warn(f"{gid}: interface teams {iv['team_a']} / {iv['team_b']} != {a} / {b}")
        return
    if (iv["score_a"], iv["score_b"]) != (sa, sb):
        w.warn(f"{gid}: interface scores {iv['score_a']}-{iv['score_b']} != {sa}-{sb}")
    half_q = iv["half_q"]
    l1, l2 = iv["lineups"][1], iv["lineups"][2]
    if half_q is None and l1 != l2:
        w.warn(f"{gid}: no halftime question and lineups differ; half-2 lineup used only "
               f"for slots that did not change")
    team_of = lambda slot: a if slot.startswith("A-") else b  # noqa: E731
    tg = {a: defaultdict(lambda: defaultdict(float)), b: defaultdict(lambda: defaultdict(float))}
    for qd_ in iv["questions"].values():   # every subject of the packet gets a row (zeros too)
        sj = normalize_subject(qd_.get("category"))
        if sj:
            tg[a][sj]; tg[b][sj]  # noqa: B018 - touch defaultdict
    pg = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))  # (p, team) -> subj -> k
    for q, d in sorted(iv["questions"].items()):
        tu, pen, bo = d.get("TU", {}), d.get("Penalty", {}), d.get("B", {})
        if not any(tu.values()) and not any(pen.values()):
            continue  # question not read
        subj = normalize_subject(d.get("category")) or "?"   # '?' = no category recorded
        if half_q is None:
            lineup = l1
        else:
            lineup = l1 if q <= half_q else l2
        for slot, p in lineup.items():
            if p:
                pg[(p, team_of(slot))][subj]["tuh"] += 1
        for slot in SLOTS[:8]:
            p = lineup.get(slot) or ""
            team = team_of(slot)
            if tu.get(slot):
                tg[team][subj]["tu"] += 1
                if p:
                    pg[(p, team)][subj]["correct"] += 1
                else:
                    w.warn(f"{gid} q{q}: correct buzz from empty slot {slot}")
            if pen.get(slot):
                tg[team][subj]["neg"] += 1
                if p:
                    pg[(p, team)][subj]["negs"] += 1
                else:
                    w.warn(f"{gid} q{q}: neg from empty slot {slot}")
        if bo.get("A-Captain"):
            tg[a][subj]["bonus"] += 1
        if bo.get("B-Captain"):
            tg[b][subj]["bonus"] += 1
    # Check against the final score: 4*TU + 10*B + 4*opponent negs.
    for team, opp, score in ((a, b, sa), (b, a, sb)):
        calc = sum(4 * v["tu"] + 10 * v["bonus"] for v in tg[team].values()) + \
            4 * sum(v["neg"] for v in tg[opp].values())
        if calc != score:
            w.warn(f"{gid} {team}: scoresheet total {calc} != score {score}")
    uncategorized = any("?" in tg[x] for x in (a, b)) or any("?" in v for v in pg.values())
    if uncategorized:
        w.warn(f"{gid}: scoresheet has no question categories (DE packet); overall stats only")
    for team in (a, b):
        if uncategorized:
            break
        for subj, v in tg[team].items():
            w.team_game_subject(gid, team, subj, 4 * v["tu"] + 10 * v["bonus"],
                                tossup_points=4 * v["tu"], bonus_points=10 * v["bonus"],
                                tossups_correct=v["tu"], negs=v["neg"])
    for (p, team), subs in pg.items():
        scopes = ["all"] + (["rr"] if stage == "rr" else [])
        for sc in scopes:
            games_played[(p, team, sc)].add(gid)
        oc = on = oh = 0.0
        for subj, v in subs.items():
            c, n = v["correct"], v["negs"]
            oc, on, oh = oc + c, on + n, oh + v["tuh"]
            if subj == "?":
                continue
            w.player_game_stat(gid, p, team, subj, correct=c, negs=n)
            if stage == "rr":
                for k in ("correct", "negs", "tuh"):
                    tot[(p, team, "rr", subj)][k] += v[k]
        w.player_game_stat(gid, p, team, "overall", correct=oc, negs=on)
        for sc in scopes:
            tot[(p, team, sc, "overall")]["correct"] += oc
            tot[(p, team, sc, "overall")]["negs"] += on
            tot[(p, team, sc, "overall")]["tuh"] += oh
