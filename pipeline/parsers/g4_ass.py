"""ASS 2021 (6 teams, online).

Results sheet: "RR" has every team's result points (2/1/0) and score per round plus a room
table (Match k -> two team names per room); "DE SCHEDULE" is a small double-elimination
bracket whose first two rounds have scores, while the third round and the final only show
who advanced.

Stats come from a Drive folder with three sheets of the same 17-tab template (subject tabs
"all", "bio", ... with GP, 4, -4, X, TUH, ...; "<subject>_team" team totals): RR stats, DE
stats and combined. Players are listed by first name / handle only, with no team column.
Team membership is reconstructed by exact arithmetic: the partition of players into the six
teams whose per-subject 4 / -4 / X sums reproduce every team-total row of both the RR and the
DE sheet (36 equations per team). The parser only uses it when that partition is unique.
"""
from __future__ import annotations

from ..registry import Tournament
from ..schema import TournamentWriter
from ..util.grid import Grid, load_grids
from .g4_common import Roster, assign_players, read_bracket, write_bracket
from .g4_dasoni import _progression

SUBJECTS = {"all": "overall", "bio": "biology", "chem": "chemistry", "ess": "ess",
            "math": "math", "physics": "physics"}


def _rows(x: Grid) -> dict[str, dict[str, float]]:
    hdr = x.row_texts(0)
    ci = {h: i for i, h in enumerate(hdr) if h}
    k4 = "4.0" if "4.0" in ci else "4"
    kn = "-4.0" if "-4.0" in ci else "-4"
    out = {}
    for r in range(1, x.nrows):
        n = x.text(r, 0)
        if n and x.num(r, ci["GP"]) is not None:
            out[n] = {"gp": x.num(r, ci["GP"]), "c": x.num(r, ci[k4]) or 0, "n": x.num(r, ci[kn]) or 0,
                      "x": x.num(r, ci["X"]) or 0, "tuh": x.num(r, ci["TUH"]),
                      "points": x.num(r, ci["Points"])}
    return out


def parse(t: Tournament, w: TournamentWriter, results: str = "results.xlsx",
          stats: dict[str, str] | None = None, de_games: list[str] | None = None) -> None:
    g = load_grids(t.raw(results))
    rr = g["RR"]
    # team rows: name, then (result points, score) per round
    teams: dict[str, dict[int, tuple[float, float]]] = {}
    for r in range(2, rr.nrows):
        name = rr.text(r, 0)
        if not name or rr.num(r, 1) is None:
            continue
        teams[name] = {k: (rr.num(r, 2 * k - 1), rr.num(r, 2 * k)) for k in range(1, 6)}
    roster = Roster(teams)
    room_r = next(r for r in range(rr.nrows) if rr.text(r, 0).lower() == "room")
    for k in range(1, 6):
        for r in range(room_r + 1, rr.nrows):
            if not rr.text(r, 0).lower().startswith("room"):
                continue
            a, b = rr.text(r, 2 * k - 1), rr.text(r, 2 * k)
            if not a or not b:
                continue
            ta, tb = roster.resolve(a), roster.resolve(b)
            (pa, sa), (pb, sb) = teams[ta][k], teams[tb][k]
            if pa + pb != 2 or (pa == 2) != (sa > sb) or (pa == 1) != (sa == sb):
                w.warn(f"RR{k} {ta} {pa} {sa} vs {tb} {pb} {sb}: inconsistent; skipped")
                continue
            w.game(ta, tb, sa, sb, stage="rr", round=f"RR{k}", seq=k, game_id=f"rr{k}-{r}")

    de = g["DE SCHEDULE"]
    games = read_bracket(de, roster, round_labels={0: "DE1", 2: "DE2"}, max_col=3)
    write_bracket(w, games, seq_base=10)
    if de_games:
        _progression(w, de, roster, de_games, seq_base=12)

    # ---- stats -------------------------------------------------------------------------------
    stats = stats or {"rr": "stats_rr.xlsx", "playoff": "stats_de.xlsx"}
    data = {}
    for scope, fname in stats.items():
        gs = load_grids(t.raw(fname))
        data[scope] = {"P": {s: _rows(gs[s]) for s in SUBJECTS},
                       "T": {s: _rows(gs[s + "_team"]) for s in SUBJECTS}}
    players = sorted(set().union(*[set(d["P"]["all"]) for d in data.values()]))
    tnames = sorted(data["rr"]["T"]["all"])

    def vec(kind: str, name: str) -> list[float]:
        v: list[float] = []
        for scope in stats:
            for s in SUBJECTS:
                row = data[scope][kind][s].get(name, {})
                v += [row.get("c", 0), row.get("n", 0), row.get("x", 0)]
        return v

    allowed = {p: {tm for tm in tnames
                   if all(d["P"]["all"].get(p, {}).get("gp", 0) <= d["T"]["all"][tm]["gp"] for d in data.values())}
               for p in players}
    sols = assign_players({p: vec("P", p) for p in players}, {tm: vec("T", tm) for tm in tnames},
                          allowed=allowed, max_size=10, max_solutions=2)
    if len(sols) != 1:
        w.warn(f"player -> team reconstruction found {len(sols)} solutions; player stats not written")
        return
    team_of = {p: roster.resolve(tm) for p, tm in sols[0].items()}
    for p in players:
        if p not in team_of:
            w.warn(f"player {p!r}: no buzzes anywhere, team unknown; skipped")
    for scope, d in data.items():
        for s, subj in SUBJECTS.items():
            for p, row in d["P"][s].items():
                if p not in team_of:
                    continue
                w.player_stat(p, team_of[p], subj, scope=scope, gp=row["gp"], tuh=row["tuh"],
                              correct=row["c"], negs=row["n"], zeros=row["x"], points=row["points"])
