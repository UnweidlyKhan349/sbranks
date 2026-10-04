# Site data contract (`site/data/`)

Written by `python -m pipeline.build` (`pipeline/export.py`). The static site only reads these
files. All JSON is compact; dates are ISO `YYYY-MM-DD`; ratings are on the Elo scale
(1500 = average). `null` = unknown / not applicable.

Subject keys: `math`, `physics`, `chemistry`, `biology`, `ess` (Earth & Space), `energy`
(+ `overall` in player/tournament stat rows; `other` may appear in stat rows).

Detail files for teams and players are sharded: shard = djb2(id) mod `meta.n_shards` where

```js
function shardOf(id) { let h = 5381; for (const ch of id) h = ((h * 33) + ch.codePointAt(0)) >>> 0; return h % 32; }
```

(Python uses `ord(ch)` per code point and masks to 32 bits — identical for BMP and non-BMP
characters as long as JS iterates code points with `for...of`.)

## `meta.json`
```
{ generated, snapshot,                      // snapshot = date of the latest tournament
  counts: {tournaments, tournaments_listed, games, scored_games, teams, schools, players, player_stat_rows},
  seasons: ["2025-26", ...],                // newest first
  subjects: [{key, label}],                 // the 6 subjects in display order
  glicko: {...params}, glicko_metrics: {games_scored, log_loss, accuracy},
  stats_model: {overall|<subject>: {beta, spread}},
  thresholds: {ranked_rd, active_days, player_min_tuh: {overall, <subject>...}},
  n_shards }
```

## `teams.json` — one row per team entry (school + letter, or a composite/pickup team)
```
{ id, name, school, school_name, state, composite, letter,
  r, rd,                 // Glicko-2 rating and deviation (null if the team never played a rated game)
  rank,                  // rank among ranked teams (rd <= ranked_rd and active), else null
  rank_all,              // rank among all rated teams
  g, w, l, t,            // rated games and record
  first, last,           // first/last tournament date
  seasons: [..], n_t,    // seasons played, number of tournaments
  peak,                  // highest post-tournament rating
  trend: [r, ...],       // last 12 post-tournament ratings (for sparklines)
  subj: { <subject>: {r, se, rank, n} } }   // Elo-scaled subject ratings (n = effective tossups heard)
```
Sorted by `r` descending.

## `teams/<shard>.json` — `{ <team id>: detail }`
```
{ history: [{tournament_id, date, r, rd, pre, delta}],      // after each rated tournament
  games: [{t, d, seq, st, rd, o, s, os, r, p, ff}],         // t=tournament, o=opponent team id, s/os=scores,
                                                            // r=W/L/T, p=pre-game win probability, st=stage, rd=round
  tournaments: [{t, d, w, l, t, g, ppg, champ}],
  roster: { <season>: [player ids] },
  subj_history: { <subject>: [{d, r, se}] } }
```

## `schools.json`
```
{ id, name, short, city, state, curated, composite, teams: [team ids], best, nsb: [{year, finish}] }
```

## `players.json`
```
{ id, name, school, school_name, state, teams: [team ids],
  r, se, rank,                 // overall rating (Elo-scaled), uncertainty, rank (ranked = enough tossups + active)
  n_t, gp, pts, ppg, ptuh,     // tournaments, games, tossup points, points/game, points per tossup heard
  first, last, best,           // best = best subject key
  peak,
  subj: { <subject>: {r, se, rank, n, pts} },
  aliases: [names as spelled in other sources] }
```
Sorted by `r` descending (players without an overall rating last).

## `players/<shard>.json` — `{ <player id>: detail }`
```
{ history: { overall|<subject>: [{d, r, se}] },
  stats: [{t, d, tm, scope, s: { overall|<subject>: {gp, tuh, c, n, pts, ppg, gp_est} }}],   // one per tournament
  teammates: [player ids] }
```
`c` = correct tossups (4s), `n` = negs, `pts` = tossup points. `gp_est: true` means games played
was inferred from the team's game count.

## `tournaments.json` (newest first)
```
{ id, name, date, end, season, location, online, kind, level, subject_only, status, notes,
  n_teams, n_games, n_scored, n_players, strength, champion, rated, coverage, set,
  sources: [{role, kind, url}], no_data? }
```
`strength` = mean pre-tournament rating of the field's top 8 teams. `rated` = games count toward
the overall team rating (false for single-subject events). `no_data: true` for listed events with
no obtainable results.

## `tournaments/<id>.json`
Tournament row (above) plus:
```
{ teams: [{tm, raw, w, l, t, g, ppg, papg}],                 // sorted by wins, then ppg
  games: [{id, st, rd, seq, t1, t2, s1, s2, res, p1, ff, pre1, pre2}],
  players: [{p, tm, s: { overall|<subject>: {gp, tuh, c, n, pts, ppg, gp_est} }}] }
```

## `nationals.json`
```
{ winners: [...sources/reference/nsb_winners.yaml...], finishes: { <year>: [{team, finish, ...}] },
  tournaments: [ids of NSB National Finals tournaments] }
```
