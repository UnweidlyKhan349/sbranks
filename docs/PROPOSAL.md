# SBRanks: Science Bowl ratings site (proposal, draft v0)

**Status:** draft for review. No code yet.
**Goal:** a website that collects past Science Bowl results and statistics and shows two things:

1. **Teams/schools**: a rating ("Elo"), a ranking, and subject breakdowns.
2. **Individual players**: the same.

Subjects: **Math, Physics, Chemistry, Biology, Earth & Space (ESS)**. I also suggest tracking **Energy** as an optional sixth subject (see §4.5).

---

## 1. Summary

- The [Stanford tournament list](https://scibowl.stanford.edu/tournaments) covers **114 past tournaments**, from the 2019–20 season through September 2026. **105** of them link to results and **67** link to statistics. The data is spread across about 10 different hosts and many spreadsheet layouts.
- Most of the data is usable. 96 of the 107 linked Google Sheets download cleanly as `.xlsx`. Two hosts (scibowl.live and ISOBowl) have clean machine-readable feeds that go down to **individual buzzes**.
- **Per-player, per-subject stats exist for roughly 35–40 tournaments.** Game-level team scores exist for most of the rest.
- **The official NSB Nationals data is thin.** It has only win/loss/tie grids for each round-robin division and PDF brackets that name the winners. There are no point scores and no individual or subject stats. Nationals can feed team ratings (wins and losses only) and a history page, but not player or subject ratings.
- **The main work is the data pipeline, not the website:** parsers for each spreadsheet template, plus matching player and school names across tournaments. My estimate is that this is about 70% of the effort.
- **Recommendation:**
  - Teams get a true Elo-family rating (Glicko-2 with margin of victory).
  - Players get an *Elo-scaled* rating built from opponent- and difficulty-adjusted points per tossup, overall and per subject. Players never play each other one-on-one, so a literal Elo doesn't fit.
  - Build it as a static site from a reproducible pipeline.

---

## 2. What the data looks like

### 2.1 Where results and stats live

Counts are links from the Stanford page, results and statistics combined. `docs/source-inventory.csv` lists every tournament with its URLs and current fetch status.

| Host | Links | What's there | Machine-readable? | Status |
|---|---|---|---|---|
| **Google Sheets** | 120 (107 unique docs) | Round-robin score grids, bracket sheets, player/team stats tabs, often split by subject | Yes: `export?format=xlsx` works without login | 96 OK · **5 deleted** · **6 private** |
| **prometheus.science** (Ignis ×6, Olympus, Prometheus 2022, ESBOT/CAST xlsx) | 18 | Server-rendered results and stats pages, plus xlsx files | HTML scrape plus xlsx | OK on prometheus.science. **The Stanford page links are relative and return 404.** |
| **isobowl.com** (ISOBowl Invitational HS/RISE/MS, TOMB, NSBA 4) | 10 | Standings and stats | **Yes, a JSON API:** `/api/tournaments/<slug>` and `/api/tournaments/<slug>/scorelogs` give a per-question log with the subject and who buzzed | OK |
| **scibowl.live** (Stanford 2026, JHU 2026, Stanford College+ 2026, DASONI 2, a combined Stanford-set report) | 5 | Full stats warehouse | **Yes, CSVs:** `games`, `teams`, `players`, `game_players_by_category`, `game_teams_by_category`, `buzzes` (with word index), `questions_meta` | OK. Stanford 2026 alone: 48 teams, 232 players, 151 games, ~7.1k buzzes |
| drive.google.com | 4 | Folders of xlsx/scoresheets (BASED, ASS, LOST, DAST) | Partly | Needs a folder listing |
| challonge.com | 4 | Brackets only, no stats | Blocks scripts (403) | Needs an API key or manual entry |
| niskyscibowl.com (NWI 2024, NSI 2023) | 4 | Static HTML | Scrape | NWI OK. **NSI pages 404** |
| eyrieshub.fly.dev (AVES 2) | 2 | Results and stats (overall plus subject leaders) | HTML scrape | OK |
| nsba.herokuapp.com (NSBA 2022) | 2 | Results and stats | No | **Dead (503)** |
| csb.clementsjets.org (Clements 2026 stats) | 1 | Stats | No | Connection reset |

**Spreadsheet templates repeat.** These families of sheets share a layout, so one parser covers several tournaments:

- *A 17-tab `subject / all / bio / bio_team …` export*: MOSFET 2020, WISC, DBHSST, SBST 2021, WSBT, NSBA2. Columns: `4s / 0s / -4s / TUH / P/TUH / PPG`.
- *"Catstats Hub"*: TJSBT, SMH League Cup.
- *SMH "Individual Biology Stats …"*: SMH Standard/Rookie 2023, SMH Cup 2024.
- *DASONI "Metrics Guide"*: DASONI 2022 and 2023.
- *Stanford/UCLA "Indiv / Indiv Bio … / Team"*.
- *Berkeley/Rice "Check-In Import / Morning RR"*.
- *Round-robin score grids*, where the row is the team and the column is the opponent. These show up almost everywhere.
- *Double-elimination bracket sheets*. These are visual layouts and the hardest to parse.

### 2.2 Official NSB Nationals

Source: the [NSB Score Center](https://science.osti.gov/wdts/nsb/2026-Finals/Competition-Results/High-School-Round-Robin).

- **Round robin:** 8 divisions of 8–9 teams (2026: Ames, Brookhaven, Fermi, Lawrence Berkeley, Princeton Plasma, Rockies, Savannah River, SLAC). Each pairing has a **2/1/0 (win/tie/loss) grid**, total points, division place, and a Division Team Challenge rank. **There are no game scores.** A middle-school page has the same structure.
- **Double elimination:** two PDFs (No-Loss and One-Loss brackets) that list which team won each numbered game. **No scores.**
- **History:** [Past HS winners 1991–present](https://science.osti.gov/wdts/nsb/About/Historical-Information/Past-National-Science-Bowl-Winners/Past-HS-Winners), with rosters for recent years. Middle school has the same.
- **Coverage:** I fetched round-robin pages for 2015, 2019, 2023 and 2026. Search results show pages for 2017, 2018 and 2025 too. I didn't find 2020–22 or 2024 under the same URL pattern; those were virtual or changed-format years and need a manual check.
- **Access:** the OSTI firewall returns 403 to plain scripted requests for some pages and PDFs. A headless browser works. We should fetch rarely and keep a cached copy.

So Nationals gives **wins and losses** for about 70 HS teams a year, plus official finishes. That's good for team ratings and a "Nationals history" view, but it adds nothing to player or subject ratings.

### 2.3 Data richness tiers

| Tier | What we get | Sources (approx.) | Supports |
|---|---|---|---|
| **A: question-level** | Every tossup: subject, who buzzed, correct or neg, sometimes buzz position | scibowl.live (6 reports), ISOBowl (5), Berkeley 2025 ("All RR Questions"), ‘Iolani 2025 (per-game sheets) | Everything, including buzz-by-buzz Elo and per-game subject results |
| **B: player and subject aggregates + game scores** | Player and team totals per tournament, often per subject. Round-robin scores, sometimes bracket scores | ~25–30 Google Sheets, prometheus.science, Eyrie | Team Elo with margin of victory, adjusted player and subject ratings |
| **C: results only** | Game scores, or just wins and losses | ~40 results-only sheets, Challonge, NSB Nationals | Team Elo only |
| **Lost** | None | 5 deleted and 6 private sheets, the NSBA Heroku app, NSI pages | Ask the organizers for copies |

### 2.4 Messy parts we'll need to handle

- **Player names vary.** The same person appears as "Theenash Sengupta" (Stanford), "Theenash S" (Berkeley) and sometimes in lowercase ("suzuko ohshima" on Eyrie). SSBT lists Discord usernames, with a separate mapping tab.
- **Team names vary.** "BISV B", "BASIS Silicon Valley" and "BASIS Independent Silicon Valley" are one school. Online events also have **pickup or composite teams** that aren't schools ("Gargy Bomy", "Ultimate Uzbeks", "Dheerans Establishment"), plus A/B/C entries from the same school.
- **Categories vary.** Most sources use Bio/Chem/Phys/Math/ESS/Energy. Some differ: "life" (DBHSST), Earth and Space reported separately (E&S Scrimmage), "compsci" (NSBA2), "csenergy" (ICSBT 2).
- **Metrics vary.** PPG, PP4TUH and P/TUH are all used. Some stats cover the round robin only and some include playoffs. Some sources give tossups heard (TUH) and some don't.
- **Sets and difficulty vary:** middle-school, novice, College+, single-subject events (ChemBowl, Lexington Bio Bowl, TOMB math, Earth & Space Scrimmage), and **mirrors** that share a set. For example, the Stanford set is played at Stanford, JHU and Stanford College+, and scibowl.live already publishes an `ssb-2026-combined` report.
- **Links break.** Five sheets have already been deleted, six went private, one app is dead, and the Stanford page's Prometheus links are broken. We should keep our own snapshot of every source.

---

## 3. The website

### 3.1 Site map

```
/                      Home: top teams and players this season, recent tournaments, biggest rating movers
/teams                 Team leaderboard (Overall | Math | Phys | Chem | Bio | ESS [| Energy])
/teams/:school         School page (all A/B/C entries, every season)
/teams/:school/:season Team-season page
/players               Player leaderboard (same subject tabs)
/players/:id           Player page
/tournaments           Every tournament: date, field size, strength of field, source links
/tournaments/:id       Field, standings, games, bracket, stat leaders
/nationals             NSB Nationals history: champions since 1991, division grids, brackets, ratings vs finish
/compare               Head-to-head: team vs team or player vs player
/methodology           How ratings work, data coverage, calibration charts, sources and credits
```

### 3.2 Teams

- **Leaderboard:** rank, team, school, state, rating ± uncertainty, record, games, last played, trend sparkline. Subject tabs re-sort by subject rating.
  - Filters: division (HS/MS/College+), season, state/region, active only (played in the last N months), schools only (hide pickup teams), minimum games.
- **Team page:**
  - Rating history chart with a marker at each tournament
  - Subject radar or bar chart against the field average
  - **Subject coverage**: which roster player carries which subject, and where the gaps are
  - Tournament-by-tournament results and games
  - Head-to-head record against frequent opponents
  - Roster with links to player pages
- **School page:** every entry (A/B/C) across seasons, Nationals appearances and finishes, and the school's best rating each season.

### 3.3 Players

- **Leaderboard:** rank, player, school, rating ±, PPG, P/TUH, negs per game, best subject, tournaments played. Subject tabs and the same filters as teams.
- **Player page:**
  - Rating history overall and per subject
  - Subject profile chart
  - Per-tournament stat lines: games, TUH, 4s, negs, PPG, P/TUH, by subject
  - Teammates
  - Where question-level data exists: buzz-timing distribution and per-subject accuracy

### 3.4 Shared features

- Global search across teams, schools, players and tournaments.
- Every number links back to its source sheet or page, for transparency.
- CSV download for each leaderboard.

---

## 4. Ratings

### 4.1 Team rating ("Elo")

- **Rated unit:** a team entry in a season, for example *Lynbrook A, 2025–26*. A school's rating is its best entry's rating. Pickup teams are rated but flagged, and hidden from the schools view by default.
- **Algorithm: Glicko-2, shown on the familiar Elo scale (1500 = average).** Plain Elo also works. Glicko-2 suits this data better because teams play only 2–5 tournaments a season in regional clusters (West Coast and East Coast teams rarely meet outside online events and Nationals). Glicko-2's uncertainty term gives "±" and "provisional" badges directly.
- **Margin of victory:** when scores are known, scale the update by a log-margin multiplier (as in FiveThirtyEight-style Elo). When only wins and losses are known (Nationals, Challonge), use a plain win/loss update.
- **Order:** process tournaments by date, and within a tournament by round (round robin, then playoffs).
- **New seasons:** rosters turn over, so pull each team about ⅓ of the way back to the mean and widen its uncertainty each August. Later, a new season's rating could be seeded from the returning players' ratings.
- **Tuning:** backtest on held-out games (log-loss and Brier score) to choose K and the margin factor. Publish the calibration chart on `/methodology`.

### 4.2 Team subject ratings

- **With per-game category data** (tier A, plus sheets with per-game subject columns): treat each subject inside a game as a mini-match. Compare the two teams' points in that subject, including bonuses, and update that subject's Elo.
- **Otherwise:** use the team's subject points per game from the stats tables, adjusted for opponent strength the same way as player ratings (§4.3).

### 4.3 Player rating ("Elo-scaled")

**Why not plain Elo?** Players never play one-on-one matches; wins and losses belong to teams. For most tournaments we only have each player's totals (correct tossups, negs, TUH, by subject). The rating has to come from **how much a player scores, given how hard it was to score**.

**Recommended: adjusted production, mapped to the Elo scale.**

1. **Core stat:** points per tossup heard (P/TUH), overall and per subject. If TUH isn't reported, estimate it from games played × tossups per game, set per tournament.
2. **Adjust for:**
   - **Opposing strength.** Strong opponents leave fewer tossups. Use the team ratings of the opponents actually faced, or the field average if per-game data is missing.
   - **Set difficulty.** Estimate one difficulty term per question set, using players who appear at several tournaments. Mirrors share one term.
   - **Teammate strength** (phase 3). On a stacked team, players split the available tossups.
3. **Model:** `rate[player, subject, tournament] = ability[player, subject] − difficulty[set] − opponents[...] + noise`, weighted by tossups heard. Older tournaments count less (recency weighting), and ratings shrink toward the division mean when there's little data (empirical Bayes).
4. **Display:** `rating = 1500 + 200 × z-score` within the division, with an uncertainty ±. It reads like an Elo, and the methodology page explains what it is.

**Optional "Buzz Elo" for tier-A tournaments:** treat each tossup as a race among the 8 players. The player who answers correctly beats everyone else on the board, and a neg loses to everyone, with a multiplayer Elo/TrueSkill-style update. This is closer to real Elo, but only about 12 tournaments have the data. I'd use it to validate the main rating, and possibly blend it in later.

### 4.4 Rankings rules

- Leaderboards show a minimum-games or minimum-TUH threshold. Below it, players and teams are marked **provisional** and listed separately.
- Default view: current season plus the last 12 months. Historical seasons are browsable.

### 4.5 Subjects

| Display | Source labels mapped to it |
|---|---|
| Math | math, mathematics |
| Physics | phys, physics |
| Chemistry | chem, chemistry |
| Biology | bio, biology, life |
| ESS | ess, e&s, earth, space, earth and space, astronomy |
| *Energy (optional)* | energy, "csenergy" (approximate) |
| *Other* | compsci, general science (counted in Overall only) |

**Energy** is an official NSB category and appears in almost every stats sheet. I'd track it and show it as an optional sixth tab rather than drop it. Otherwise Overall includes points that no subject accounts for.

---

## 5. Architecture

```
sources/        one YAML file per tournament: URLs, parser type, tab mapping, division, set used, aliases
raw/            snapshots of every fetched file (xlsx/CSV/JSON/HTML/PDF), so broken links don't lose data
pipeline/       Python: fetch → parse (per template family) → normalize → resolve names → rate → export
data/           standard tables (CSV/Parquet + SQLite): schools, teams, players, rosters, tournaments,
                games, game_team_subject, player_tournament_subject, buzzes (when available)
site/           static frontend reading pre-built JSON (Astro or SvelteKit-static + Observable Plot/ECharts)
.github/        Action: rebuild data and site on push, deploy to GitHub Pages
```

- **No server or runtime database.** The whole dataset is small: about 115 tournaments × ~30 teams × 4–5 players is roughly 15k player-tournament rows and a few thousand unique players. Pre-computed JSON loads instantly and hosting is free.
- **Name matching is semi-automatic.** Fuzzy-match candidates (same school, similar name, "First L." expanded to a full name), then a person confirms them into `aliases.yaml`. Schools get a canonical table (name, city, state) with an alias list.
- **Adding a new tournament** means adding one YAML file. CI re-runs the pipeline.

**Parsers by priority:**

1. Google Sheets round-robin score grids (many tournaments)
2. Google Sheets stats-template families (§2.1)
3. scibowl.live CSV
4. ISOBowl JSON
5. NSB Score Center (HTML grid plus PDF brackets, through a headless browser)
6. prometheus.science HTML
7. Double-elimination bracket sheets, each needing its own config
8. Manual entry for Challonge and other one-offs

---

## 6. Phased plan

| Phase | Scope | Result |
|---|---|---|
| **0: Sources** | Source registry for all 114 tournaments plus NSB; snapshot raw files. *The inventory is already done: `docs/source-inventory.csv`.* | A reproducible raw-data snapshot |
| **1: Team MVP** | HS, seasons 2022–23 to 2025–26. Round-robin grids, structured bracket games, NSB round-robin grids and brackets. Team Glicko/Elo. | `/teams`, team and school pages, `/tournaments`, `/methodology` |
| **2: Players** | Stats-template parsers, scibowl.live, ISOBowl; name matching; player overall and subject ratings | `/players`, player pages, subject tabs |
| **3: Depth** | Team subject ratings, MS and College+, seasons back to 2019–20, `/compare`, win-probability tool, buzz analytics, `/nationals` | The full site |
| **4: Upkeep** | One-file tournament additions, a corrections process (issues or a form), seasonal re-tuning | A site that stays current |

---

## 7. Risks and considerations

- **Most players are minors.** Their names are already public in the source sheets, but ranked profiles that combine many tournaments are a new kind of exposure. Recommendations:
  - Show names exactly as published, with no grades, photos or other details.
  - Offer an easy opt-out or removal process.
  - Consider showing "First L." on player pages and `noindex` for search engines.
  - Ideally, give Stanford Science Bowl and the other organizers a heads-up and credit every source.
- **Be a good guest on others' sites.** Use cached snapshots, fetch rarely, and respect the OSTI firewall rather than working around it at volume.
- **Uneven data:**
  - Tier-A players have far more data than others.
  - Online events and pickup teams make up a large share of the data.
  - Nationals contributes wins and losses only.
  
  Ratings will show uncertainty, and the methodology page will be clear about coverage.
- **Parsing effort:** bracket layouts and one-off sheets will need hand-written per-tournament config. That's expected and budgeted in phases 1–3.

---

## 8. Extra ideas

- **Win-probability tool:** "Team A vs Team B: 68%", based on the ratings.
- **Strength of field for each tournament** (for example, the average rating of the top 8 teams). This helps teams choose tournaments and puts results in context.
- **Mirror leaderboards:** compare everyone who played the same set (Stanford set at Stanford, JHU and College+).
- **Pre-Nationals vs. actual finish:** a calibration page and some fun "upset" stories.
- **Season awards:** top player per subject, most improved, best rookie.
- **Buzz-timing analytics** where buzz positions exist (scibowl.live has a word index for each buzz).

---

## 9. Open questions

1. **Divisions:** HS only for v1, or HS + MS + College+ from the start?
2. **Time range:** all seasons since 2019–20, or start with the last 3–4?
3. **Player "Elo":** is the Elo-scaled adjusted rating (§4.3) OK, or do you want a strict buzz-by-buzz Elo limited to tournaments with question logs?
4. **Energy:** track it as an optional sixth subject (my recommendation), or leave it out?
5. **Privacy:** full names as published, "First L.", or opt-in only? Will you contact Stanford Science Bowl or other organizers?
6. **Team unit:** rank entries (Lynbrook A) and roll them up to schools? Should pickup or online-only teams appear on the team leaderboard?
7. **Stack and hosting:** is a Python pipeline plus a static site on GitHub Pages fine, or do you have a preference?

---

### Sources consulted

- Stanford Science Bowl tournament list: <https://scibowl.stanford.edu/tournaments>, including all linked Results/Statistics pages (see `docs/source-inventory.csv`)
- Stanford mirrors page: <https://scibowl.stanford.edu/mirrors>
- NSB 2026 HS round robin: <https://science.osti.gov/wdts/nsb/2026-Finals/Competition-Results/High-School-Round-Robin>
- NSB 2026 HS double elimination: <https://science.osti.gov/wdts/nsb/2026-Finals/Competition-Results/High-School-Double-Elimination>
- NSB 2023 HS round robin: <https://science.osti.gov/wdts/nsb/About/Historical-Information/2023-Competition/High-School-Round-Robin>
- NSB past HS winners: <https://science.osti.gov/wdts/nsb/About/Historical-Information/Past-National-Science-Bowl-Winners/Past-HS-Winners>
- scibowl.live stats feeds: <https://www.scibowl.live/tournaments/stanford-science-bowl>
- ISOBowl Premier: <https://isobowl.com/premier/tournaments/isobowl-invitational-tournament/stats>
- Prometheus / Ignis: <https://prometheus.science/olympus/statistics>
