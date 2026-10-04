"""Stanford Science Bowl results template (Stanford 2025, Science Bowl @ UCLA 2025).

Results workbook tabs:
  * 'Round Robin Scores'   pool grids (row = team, col = opponent; score + W/L/T columns)
  * 'Round Robin Schedule' 'Round k' rows with Team 1 | Team 2 | Room triples per pool
  * 'Consolation Scores' / 'Consolation Schedule'   afternoon consolation pools (optional)
  * 'Double Elimination'  visual bracket; each round is a column of ``team | score`` cells,
                          finals may have a second score column (if-necessary game)
  * 'Raw' (hidden)        room-by-room entry log (RR1..RR5, DE1..DE9) - used only as a
                          cross-check when ``raw_check`` is set (UCLA's copy is stale).

Stats workbook (Stanford 2025): hidden 'Raw' tab holds every round-robin scoresheet:
per game, per team, per half, per player tossup points by subject (B C E ES M P), team
bonus points by subject and penalty points. 'Indiv*' tabs show PPG where a player who
played one half counts as half a game; we reproduce that (gp = halves played / 2).
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..config import normalize_subject
from ..registry import Tournament
from ..schema import TournamentWriter, clean_name, num
from ..util.grid import Grid, load_grids
from .g5_common import bracket_column_games, is_bye, pool_grid_games, schedule_rounds


def _pool_header_rows(g: Grid) -> list[int]:
    return [r for r in range(g.nrows)
            if g.text(r, 0) and not g.text(r, 1) and g.text(r, 2) and not re.match(r"^[A-Z]\d+$", g.text(r, 0))]


def _add_pool_games(w: TournamentWriter, g: Grid, sched: dict, *, stage: str, seq0: int,
                    label: str) -> dict[frozenset, str]:
    gids = {}
    for pool, pairs in pool_grid_games(g, _pool_header_rows(g), w=w):
        for p in pairs:
            key = frozenset((p.team1, p.team2))
            rnd = sched.get(key)
            if rnd is None:
                w.warn(f"{label} {pool}: {p.team1} vs {p.team2} not in schedule")
            gid = w.game(p.team1, p.team2, p.score1, p.score2, stage=stage,
                         round=f"{label}{rnd}" if rnd else label,
                         seq=seq0 + (rnd or 0), notes=f"pool {pool}")
            gids[key] = gid
    return gids


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
          stats: str | None = None, raw_check: bool = False, consolation: bool = True,
          rr_rounds: int = 5) -> None:
    grids = load_grids(t.raw(results))
    rr_sched = schedule_rounds(grids["Round Robin Schedule"])
    rr_gids = _add_pool_games(w, grids["Round Robin Scores"], rr_sched, stage="rr", seq0=0,
                              label="RR")
    # Consolation pools run concurrently with DE rounds 1..3.
    if consolation and "Consolation Scores" in grids:
        c_sched = schedule_rounds(grids["Consolation Schedule"])
        _add_pool_games(w, grids["Consolation Scores"], c_sched, stage="consolation",
                        seq0=rr_rounds, label="Consolation ")

    rounds = bracket_column_games(grids["Double Elimination"])
    n = len(rounds)
    for k, pairs in rounds:
        final = k == n
        for a, b in pairs:
            lab = "Final" if final else f"DE{k}"
            w.game(a.name, b.name, a.scores[0], b.scores[0], stage="playoff", round=lab,
                   seq=rr_rounds + k)
            if final and len(a.scores) > 1 and len(b.scores) > 1:
                w.game(a.name, b.name, a.scores[1], b.scores[1], stage="playoff",
                       round="Final 2", seq=rr_rounds + k + 1)

    if raw_check:
        _raw_check(w, grids["Raw"])
    if stats:
        _stats(t, w, stats, rr_gids)


def _raw_check(w: TournamentWriter, raw: Grid) -> None:
    """Every scored entry in the hidden room log must match a parsed game."""
    have = defaultdict(list)
    for g in w.rows["games"]:
        have[frozenset((g["team1"], g["team2"]))].append(
            {g["team1"]: g["score1"], g["team2"]: g["score2"]})
    n = 0
    for r in range(raw.nrows):
        a, b = raw.text(r, 2), raw.text(r, 4)
        if not a or not b or a.startswith("[Select") or a == b:
            continue
        sa, sb = raw.num(r, 3), raw.num(r, 5)
        n += 1
        if not any(d.get(a) == sa and d.get(b) == sb for d in have.get(frozenset((a, b)), [])):
            w.warn(f"raw log {raw.text(r, 1)} {a} {sa} - {b} {sb} not matched by grids")
    if n == 0:
        w.warn("raw log cross-check: no entries")


SUBJ_COLS = ["B", "C", "E", "ES", "M", "P"]


def _stats(t: Tournament, w: TournamentWriter, stats: str, rr_gids: dict[frozenset, str]) -> None:
    grids = load_grids(t.raw(stats))
    raw = grids["Raw"]
    # header row 0: Team | First Players | Total | B C E ES M P | Second Players | Total | ...
    hdr = raw.row_texts(0)
    first_tot = hdr.index("Total")
    second_name = hdr.index("Second Players")
    bonus_col = hdr.index("Bonus")
    negs_col = hdr.index("Negs")
    subj_first = {s: first_tot + 1 + i for i, s in enumerate(SUBJ_COLS)}
    subj_second = {s: second_name + 2 + i for i, s in enumerate(SUBJ_COLS)}
    subj_bonus = {s: bonus_col + 1 + i for i, s in enumerate(SUBJ_COLS)}
    assert [hdr[c] for c in subj_first.values()] == SUBJ_COLS
    assert [hdr[c] for c in subj_second.values()] == SUBJ_COLS
    assert [hdr[c] for c in subj_bonus.values()] == SUBJ_COLS

    blocks = []
    cur = None
    for r in range(1, raw.nrows):
        if raw.text(r, 0):
            cur = {"team": raw.text(r, 0), "rows": []}
            blocks.append(cur)
        if cur is not None and (raw.text(r, 1) or raw.text(r, second_name)):
            cur["rows"].append(r)
    blocks = [b for b in blocks if not b["team"].startswith("[Select")]
    if len(blocks) % 2:
        raise ValueError("odd number of team blocks in stats Raw")

    tot = defaultdict(lambda: defaultdict(float))   # (player, team, subj) -> pts
    halves = defaultdict(int)                          # (player, team) -> halves played
    matched = 0
    for a, b in zip(blocks[0::2], blocks[1::2]):
        key = frozenset((a["team"], b["team"]))
        gid = rr_gids.get(key)
        if gid is None:
            w.warn(f"stats: game {a['team']} vs {b['team']} not in RR results")
            continue
        game = next(g for g in w.rows["games"] if g["game_id"] == gid)
        for blk in (a, b):
            team = blk["team"]
            pg = defaultdict(lambda: defaultdict(float))
            total = None
            tu = defaultdict(float)
            bonus = defaultdict(float)
            pen = 0.0
            for r in blk["rows"]:
                label = raw.text(r, 1)
                if label == "Total":
                    total = raw.num(r, first_tot)
                    continue
                if label == "Penalty":
                    pen += (raw.num(r, first_tot) or 0) + (raw.num(r, second_name + 1) or 0)
                    continue
                if label == "Bonus":
                    # Per-half bonus by subject; the first-half P cell is blank on about half
                    # the sheets, so derive a blank cell from that half's bonus total.
                    for tcol, scols in ((first_tot, subj_first), (second_name + 1, subj_second)):
                        half_total = raw.num(r, tcol) or 0
                        vals = {s: raw.num(r, scols[s]) for s in SUBJ_COLS}
                        blanks = [s for s, v in vals.items() if v is None]
                        known = sum(v for v in vals.values() if v is not None)
                        if len(blanks) == 1:
                            vals[blanks[0]] = half_total - known
                        elif blanks and half_total != known:
                            w.warn(f"stats: {team} bonus half total {half_total} with blanks {blanks}")
                        for s in SUBJ_COLS:
                            bonus[s] += vals[s] or 0
                        if vals[blanks[0]] < 0 if len(blanks) == 1 else False:
                            w.warn(f"stats: {team} derived negative bonus")
                    continue
                for name_col, tcol, scols in ((1, first_tot, subj_first),
                                              (second_name, second_name + 1, subj_second)):
                    p = raw.text(r, name_col)
                    if p in ("Penalty", "Bonus", "Total"):
                        continue
                    ptot = raw.num(r, tcol) or 0
                    if p:
                        halves[(p, team)] += 1
                        pg[p]["__played"] = 1
                    elif ptot:
                        w.warn(f"stats: unnamed {team} player scored {ptot} in game {gid} "
                               f"(kept in team subject points only)")
                    ssum = 0.0
                    for s in SUBJ_COLS:
                        v = raw.num(r, scols[s]) or 0
                        if p:
                            pg[p][s] += v
                        tu[s] += v
                        ssum += v
                    if abs(ssum - ptot) > 0.01:
                        w.warn(f"stats: {p} ({team}) half total {ptot} != subject sum {ssum}")
            score = game["score1"] if game["team1"] == team else game["score2"]
            calc = sum(tu.values()) + sum(bonus.values()) + pen
            if total is not None and total != score:
                w.warn(f"stats: {team} sheet total {total} != result {score} (game {gid})")
            if abs(calc - (score or 0)) > 0.01:
                w.warn(f"stats: {team} tossup+bonus+penalty {calc} != score {score} (game {gid})")
            for s in SUBJ_COLS:
                subj = normalize_subject(s)
                w.team_game_subject(gid, team, subj, tu[s] + bonus[s], tossup_points=tu[s],
                                    bonus_points=bonus[s], tossups_correct=tu[s] / 4)
            for p, d in pg.items():
                ov = sum(d[s] for s in SUBJ_COLS)
                w.player_game_stat(gid, p, team, "overall", correct=ov / 4, points=ov)
                tot[(p, team, "overall")]["points"] += ov
                for s in SUBJ_COLS:
                    subj = normalize_subject(s)
                    w.player_game_stat(gid, p, team, subj, correct=d[s] / 4, points=d[s])
                    tot[(p, team, subj)]["points"] += d[s]
        matched += 1
    if matched != len(rr_gids):
        w.warn(f"stats: scoresheets for {matched} of {len(rr_gids)} RR games")

    # Cross-check against the hidden 'Stats' totals tab and the visible 'Indiv' PPG tab.
    st = grids.get("Stats")
    if st is not None:
        for r in range(1, st.nrows):
            p, team = st.text(r, 0), st.text(r, 1)
            if not p:
                break  # second block of the tab repeats the table as PPG
            w.team(team, players=[p])  # roster (includes players with no games)
            if (p, team, "overall") not in tot:
                continue  # on the roster but never played (0 halves)
            if abs((st.num(r, 2) or 0) - tot[(p, team, "overall")]["points"]) > 0.01:
                w.warn(f"stats: {p} total {st.num(r, 2)} != scoresheets {tot[(p, team, 'overall')]['points']}")
    ind = grids.get("Indiv")
    if ind is not None:
        for r in range(1, ind.nrows):
            p, team = ind.text(r, 0), ind.text(r, 1)
            if not p or (p, team) not in halves:
                continue
            ppg = tot[(p, team, "overall")]["points"] / (halves[(p, team)] / 2)
            if abs(ppg - (ind.num(r, 2) or 0)) > 0.01:
                w.warn(f"stats: {p} PPG {ind.num(r, 2)} != computed {ppg:.3f}")

    for (p, team, subj), d in tot.items():
        gp = halves[(p, team)] / 2
        w.player_stat(p, team, subj, scope="rr", gp=gp, correct=d["points"] / 4,
                      points=d["points"])
