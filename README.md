# SBRanks

Elo-style ratings and rankings for US **high-school Science Bowl** teams and players, overall and
by subject (math, physics, chemistry, biology, Earth & space, energy), built from published
tournament results since the 2019–20 season plus the DOE National Science Bowl.

- **Teams** (school entries like *Lynbrook A*, and online pickup/composite teams) get a
  **Glicko-2** rating on the Elo scale (1500 = average) from game results, with margin of victory,
  season regression and priors for B teams and novice events.
- **Players** and **team subject ratings** are **Elo-scaled**: tossup points per tossup heard,
  adjusted for tournament difficulty and field strength, shrunk toward the average when data is
  thin, and shown as `1500 + 200 × z`.

The site is fully static: a Python pipeline turns raw tournament files into JSON, and a
framework-free HTML/CSS/JS front end (`site/`) reads that JSON. The methodology is explained on
the site's About page (`#/about`) and in [`docs/PROPOSAL.md`](docs/PROPOSAL.md).

## Repository layout

```
sources/tournaments/   one YAML file per tournament: dates, sources, parser, status
sources/reference/     hand-curated schools, team/player aliases, NSB winners and finishes
raw/                   snapshots of every fetched source file (xlsx, CSV, JSON, HTML, PDF)
pipeline/              fetch -> parse -> resolve -> rate -> export (Python)
data/parsed/           canonical per-tournament CSVs written by the parsers
site/                  the static website (index.html, css/, js/, data/ is generated)
docs/                  proposal, data contract for site/data, source inventory
```

## Running the pipeline

Python 3.11+.

```sh
pip install -r requirements.txt

python -m pipeline.fetch            # download raw sources into raw/<tournament id>/ (cached; --force to refresh)
python -m pipeline.parse            # raw/ -> data/parsed/<tournament id>/  (--only ID ... for one tournament)
python -m pipeline.validate         # consistency checks on parsed output
python -m pipeline.build            # resolve names, compute ratings, write site/data/*.json
python -m pipeline.resolve --report # list unmatched team names to curate in sources/reference/
```

`python -m pipeline.build` takes a few seconds and is all the site needs: it reads
`data/parsed/` and writes `site/data/` as described in
[`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md). Fetching and parsing only need to be re-run
when sources change. `python -m pipeline.build --tune` grid-searches the Glicko parameters
against a held-out log loss and stores them in `sources/reference/rating_params.yaml`.

## Serving the site locally

```sh
python -m pipeline.build
python3 -m http.server 8765 -d site
# open http://localhost:8765/
```

There is no build step and there are no runtime dependencies or network requests: plain ES
modules, a hash router (`#/teams`, `#/team/<id>`, `#/players`, `#/tournament/<id>`, `#/compare?…`,
…) and relative URLs, so the `site/` folder works from any sub-path (e.g. a GitHub Pages project
site). Opening `index.html` straight from disk does not work because browsers block `fetch` of
local files — use any static server.

### Smoke test

`site/tests/smoke.mjs` visits every route type with real ids from `site/data`, fails on console
errors, uncaught exceptions, failed requests and horizontal overflow at 375px, exercises search,
chart hover/keyboard and table sorting, and saves screenshots to `.cache/screens/`. It needs
Node 18+ and Playwright (with Chromium) installed globally; it does not start a server itself:

```sh
python3 -m http.server 8765 -d site &
NODE_PATH=$(npm root -g) node site/tests/smoke.mjs http://localhost:8765/
```

## Deployment

`.github/workflows/pages.yml` runs on every push to `main` (and on demand): it installs the
Python requirements, runs `python -m pipeline.build`, and publishes `site/` to GitHub Pages.
The build reads the committed `data/parsed/` output, so commit parser output together with any
new tournament. In the repository settings, set **Pages → Source** to **GitHub Actions**.

## Adding a tournament

1. Create `sources/tournaments/<YYYY-MM-DD>-<slug>.yaml` (the file stem is the id):

   ```yaml
   id: 2026-03-08-stanford-science-bowl
   name: Stanford Science Bowl
   date: '2026-03-08'
   end_date: null              # for multi-day or multi-week events
   season: 2025-26
   location: Palo Alto, CA
   online: false
   division: HS
   include: true
   kind: invitational          # invitational | league | nationals | scrimmage
   level: standard             # novice | standard | advanced
   subject_only: null          # e.g. chemistry for a ChemBowl
   question_set: stanford-2026 # shared id for mirrors of the same set
   sources:
     - {kind: gsheet, role: results, sheet_id: <id>, url: <link>, file: results.xlsx}
   parser: null                # "module:function" under pipeline/parsers
   parser_options: {}
   status: todo                # todo | parsed | partial | unavailable
   notes: ""
   ```

   Source kinds (`gsheet`, `scibowl_live`, `isobowl`, `url`, `browser_url`, `drive_file`,
   `manual`) are documented at the top of `pipeline/fetch.py`.
2. `python -m pipeline.fetch --only <id>` to snapshot the sources into `raw/<id>/`.
3. Point `parser:` at an existing parser that understands the layout (see `pipeline/parsers/`),
   or write a new one that fills a `TournamentWriter` — the canonical CSV files are documented in
   `pipeline/schema.py`. Then `python -m pipeline.parse --only <id>` and
   `python -m pipeline.validate --only <id>`.
4. `python -m pipeline.resolve --report` and add any new schools or aliases to
   `sources/reference/` (`schools.yaml`, `team_aliases.yaml`, `player_aliases.yaml`).
5. `python -m pipeline.build`, check the site locally, set `status: parsed`, and commit.

A tournament with no obtainable results can still be listed (`include: true`, no parser); the
site shows it with "No results available" and its `notes`.

## Data sources and credits

Results and statistics are published by tournament organizers and volunteers; SBRanks only
collects them. Sources include:

- The [Stanford Science Bowl tournament list](https://scibowl.stanford.edu/tournaments), which
  links results and statistics for most invitationals.
- Official National Science Bowl results from the U.S. Department of Energy
  ([science.osti.gov](https://science.osti.gov/wdts/nsb)).
- [scibowl.live](https://www.scibowl.live) per-game, per-category and per-buzz exports.
- [ISOBowl](https://isobowl.com) tournament and score-log data.
- [prometheus.science](https://prometheus.science) results and stats pages.
- Every tournament's organizers, whose spreadsheets are linked from each tournament page.

Player names are shown exactly as published by tournaments, with no other personal details.
Corrections, merges and removal requests:
<https://github.com/UnweidlyKhan349/sbranks/issues>.

Ratings are unofficial estimates from incomplete data and are not endorsed by the DOE, the
National Science Bowl or any tournament.
