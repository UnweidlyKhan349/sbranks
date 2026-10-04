import { h, fmt, pageHead, extLink, tile } from "../ui.js";
import { meta, tournaments, teams } from "../data.js";

export async function render(ctx) {
  const [m, TR, T] = await Promise.all([meta(), tournaments(), teams()]);
  ctx.setTitle("About & methodology");
  const g = m.glicko || {};
  const gm = m.glicko_metrics || {};
  const withData = TR.list.filter((t) => !t.no_data);
  const withStats = withData.filter((t) => t.coverage && t.coverage.player_stats);
  const withSubj = withData.filter((t) => t.coverage && (t.coverage.player_subject_stats || t.coverage.team_game_subjects));
  const seasons = [...new Set(withData.map((t) => t.season))].sort();
  const p = (...kids) => h("p", null, ...kids);
  const li = (...kids) => h("li", null, ...kids);
  const code = (x) => h("code", null, x);

  const root = h("div");
  root.appendChild(pageHead({ title: "About SBRanks", sub: "What the ratings mean, how they are computed, where the data comes from, and how to request corrections." }));
  root.appendChild(h("div", { class: "tiles" },
    tile("Tournaments with results", fmt.int(withData.length), `of ${fmt.int(TR.list.length)} listed`),
    tile("Games", fmt.int(m.counts.games), `${fmt.int(m.counts.scored_games)} with scores`),
    tile("Teams", fmt.int(m.counts.teams), `${fmt.int(T.list.filter((t) => t.r != null).length)} with a rating`),
    tile("Players", fmt.int(m.counts.players), `${fmt.int(m.counts.player_stat_rows)} stat lines`),
    tile("Seasons covered", seasons.length ? `${seasons[0]} – ${seasons[seasons.length - 1]}` : "–"),
    tile("Data snapshot", fmt.date(m.snapshot), `built ${fmt.date(m.generated)}`)));

  root.appendChild(h("article", { class: "prose" },
    h("h2", null, "What this is"),
    p(`SBRanks collects published results and statistics from US high-school Science Bowl tournaments${seasons.length ? ` since the ${seasons[0]} season` : ""} — invitationals, online tournaments, leagues and the DOE National Science Bowl — and turns them into ratings for teams and individual players, overall and in each subject: math, physics, chemistry, biology, Earth & space, and energy. Middle-school and college divisions are not included.`),
    p("It is an independent fan project. Ratings are estimates from incomplete data, not official standings."),

    h("h2", null, "Team ratings (Glicko-2)"),
    p("Each team entry — a school's A, B or C team, or a pickup/composite team — has a ", h("strong", null, "Glicko-2"), " rating shown on the Elo scale, where 1500 is average. Glicko-2 is Elo with an uncertainty term: the ± next to a rating is its ", h("em", null, "rating deviation"), " (RD), and a game moves a team further when its RD is high or the result is unexpected."),
    h("ul", null,
      li(h("strong", null, "Rating periods. "), "Tournaments are processed in date order. Each tournament is one rating period: every game there is judged against the teams' pre-tournament ratings, and ratings update once at the end. Those pre-tournament ratings are also what the win probabilities on game logs use."),
      li(h("strong", null, "Margin of victory. "), `When both scores are known, the game's result is a blend: ${g.mov_weight != null ? Math.round((1 - g.mov_weight) * 100) + "%" : "part"} win/loss and ${g.mov_weight != null ? Math.round(g.mov_weight * 100) + "%" : "part"} a smooth function of the point margin (scale ${g.mov_scale ?? "–"} points), so a 150-point win moves ratings more than a 4-point win. Win/loss-only results (Nationals, bracket sites) use a plain update.`),
      li(h("strong", null, "Time away and new seasons. "), `A team's deviation grows with time since it last played (about ${g.rd_per_year ?? "–"} rating points per year), so returning teams move faster. At a team's first tournament of a new season the deviation widens further because rosters turn over${g.season_regress ? `, and its rating is pulled ${Math.round(g.season_regress * 100)}% of the way back toward its starting prior` : `; the rating itself carries over, because back-testing found that pulling ratings toward the average at a new season made predictions worse (strong programs stay strong)`}.`),
      li(h("strong", null, "Priors. "), `New teams start at 1500 ± ${g.init_rd ?? "–"}, minus ${g.letter_step ?? "–"} for each letter after A (B teams are usually weaker). If the school already has a rated team, the new entry starts ${g.sibling_gap ?? "–"} points per letter below it instead. Novice-level events start new teams ${Math.abs((g.level_offset || {}).novice ?? 150)} points lower and advanced events ${(g.level_offset || {}).advanced ?? 75} higher; teams first seen at Nationals start at ${g.nationals_prior ?? "–"}.`),
      li(h("strong", null, "Rated vs unrated events. "), "Single-subject events (for example a math-only tournament) and individual events do not change overall team ratings; their games are still listed. Forfeits are not rated."),
      li(h("strong", null, "Win probability. "), "The pre-game win probabilities on game logs and the Compare page use the Glicko expected score with both teams' deviations folded in: ",
        code("P = 1 / (1 + exp(−g(φ)·(r₁ − r₂)/173.7))"), " with ", code("φ = √(RD₁² + RD₂²)/173.7"), " and ", code("g(φ) = 1/√(1 + 3φ²/π²)"), ". An ", h("em", null, "upset"), " is a game the loser was given at least a 70% chance to win."),
      li(h("strong", null, "Backtest. "), gm.games_scored
        ? `Predicting each game from pre-tournament ratings, counting games where both teams had played before, the ratings score a log loss of ${fmt.num(gm.log_loss, 3)} and pick the winner ${fmt.pct(gm.accuracy, 1)} of the time over ${fmt.int(gm.games_scored)} games. A coin flip scores 0.693.`
        : "Backtest metrics will appear once enough games are available.")),

    h("h2", null, "Player and subject ratings (Elo-scaled)"),
    p("Players never play one-on-one, so a literal Elo does not fit. Instead, a player's rating comes from ", h("strong", null, "tossup points per tossup heard"), " (+4 for a correct tossup, −4 for a neg), overall and in each subject:"),
    h("ul", null,
      li("The model fits one ", h("em", null, "ability"), " per player and one ", h("em", null, "difficulty"), " per tournament (questions plus opposition): ", code("points per tossup heard = ability − difficulty + noise"), ". Tournaments are linked through players who attend several of them, and each tournament's difficulty is also tied loosely to its ", h("em", null, "field strength"), " (the mean pre-tournament Glicko rating of its top 8 teams), which keeps isolated events honest."),
      li("Observations are weighted by tossups heard (estimated from games played when not published), older tournaments count less (one-year half-life), and abilities are ", h("strong", null, "shrunk toward the average"), " when a player has heard few tossups — the shrinkage strength is estimated from the data (empirical Bayes) — so one great day does not produce a top rating."),
      li("Abilities are mapped to the Elo scale as ", code("rating = 1500 + 200 × z"), ", where z is the ability divided by the spread of abilities among established players. The ± is the standard error."),
      li(h("strong", null, "Team subject ratings"), " use the same model on the team's combined tossup points in each subject."),
      li("Single-subject events count toward that subject only, never the overall rating. Players who only appear in such events have subject ratings but no overall rating.")),

    h("h2", null, "Ranked, provisional and active"),
    h("ul", null,
      li(h("strong", null, "Active: "), `played within ${m.thresholds.active_days} days of the latest tournament in the data (${fmt.date(m.snapshot)}).`),
      li(h("strong", null, "Ranked teams: "), `active, with a rating deviation of ${m.thresholds.ranked_rd} or less. Everyone else is shown as provisional (faded rows, “prov” tags) and has no rank number.`),
      li(h("strong", null, "Ranked players: "), `active, with at least ${m.thresholds.player_min_tuh.overall} effective tossups heard overall (${m.thresholds.player_min_tuh.math} per subject for subject rankings).`),
      li("Faded bars in subject charts mark provisional subject ratings.")),

    h("h2", null, "Data coverage"),
    p(`${fmt.int(TR.list.length)} high-school tournaments are listed; ${fmt.int(withData.length)} have results in the data, ${fmt.int(withStats.length)} have individual player statistics and ${fmt.int(withSubj.length)} have per-subject statistics. Events with no obtainable results are still listed and marked “No results available”. National Science Bowl results contribute wins and losses only — no scores, player or subject statistics are published for Nationals.`),
    p("Coverage is uneven: some tournaments publish every buzz, others only final standings. Online events and pickup teams make up a large share of the data. Ratings carry uncertainty for exactly this reason."),

    h("h2", null, "Sources and credits"),
    p("This site would not exist without the organizers and volunteers who run tournaments and publish their results. Data comes from:"),
    h("ul", null,
      li("The ", extLink("https://scibowl.stanford.edu/tournaments", "Stanford Science Bowl tournament list"), ", which links results and statistics for most invitationals."),
      li("Official National Science Bowl results from the U.S. Department of Energy, ", extLink("https://science.osti.gov/wdts/nsb", "science.osti.gov"), "."),
      li(extLink("https://www.scibowl.live", "scibowl.live"), " (Stanford, Johns Hopkins and other tournaments' per-game and per-buzz exports)."),
      li(extLink("https://isobowl.com", "ISOBowl"), " (ISOBowl Invitational, TOMB, NSBA)."),
      li(extLink("https://prometheus.science", "prometheus.science"), " (Ignis, Olympus and Prometheus tournaments)."),
      li("Each tournament's organizers, whose spreadsheets are linked from every tournament page.")),

    h("h2", null, "Privacy and corrections"),
    p("Most players are high-school students. Names are shown exactly as published by tournaments; SBRanks adds no grades, photos or other personal details. If a name is wrong, two people have been merged (or one person split), or you would like your name removed, please open an issue at ",
      extLink("https://github.com/UnweidlyKhan349/sbranks/issues", "github.com/UnweidlyKhan349/sbranks/issues"), ". Removal requests are honoured without question."),

    h("h2", null, "Using the site"),
    h("ul", null,
      li("Press ", code("/"), " anywhere to search teams, players, schools and tournaments."),
      li("Leaderboard filters and Compare selections are kept in the address, so links are shareable."),
      li("Every chart has a “Show table” view, and charts can be stepped through with the arrow keys."))));
  return root;
}
