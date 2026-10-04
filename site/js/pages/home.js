import { h, fmt, dataTable, ratingCell, section, SUBJECTS, subjColor, emptyState } from "../ui.js";
import { sparkline } from "../charts.js";
import { meta, teams, players, tournaments } from "../data.js";
import { teamA, playerA, tournamentA, teamCell, entrantCount, championA } from "../links.js";

export async function render(ctx) {
  const [m, T, P, TR] = await Promise.all([meta(), teams(), players(), tournaments()]);
  ctx.setTitle(null);
  const rated = T.list.filter((t) => t.r != null);
  const ratedPlayers = P.list.filter((p) => p.r != null);
  const withData = TR.list.filter((t) => !t.no_data);
  const root = h("div", { class: "home" });

  // ---- hero: one figure
  root.appendChild(h("section", { class: "hero" },
    h("h1", null, h("span", { class: "hero-figure" }, fmt.int(rated.length)), " ",
      h("span", { class: "hero-label" }, "high-school Science Bowl teams rated")),
    h("p", { class: "hero-sub" },
      `From ${fmt.int(m.counts.games)} games at ${fmt.plural(m.counts.tournaments, "tournament")} with published results, plus `,
      `${fmt.int(ratedPlayers.length)} individual player ratings — overall and in math, physics, chemistry, biology, Earth & space and energy. `,
      `Data through ${fmt.date(m.snapshot)}.`)));

  // ---- top teams / top players
  // ranked first; if fewer than 10 are ranked yet, fill with the best provisional ratings (marked)
  const fill = (list, ranked) => [...ranked, ...list.filter((x) => x.r != null && x.rank == null)].slice(0, 10);
  const schoolTeams = T.list.filter((t) => !t.composite); // pickup teams are hidden by default
  const topTeamsFallback = fill(schoolTeams, schoolTeams.filter((t) => t.rank != null).sort((a, b) => a.rank - b.rank));
  const teamTable = dataTable([
    { key: "rank", label: "#", num: true, cls: "rank", render: (t) => t.rank ?? "–" },
    { key: "name", label: "Team", cls: "name", render: (t) => teamCell(T, t.id) },
    { key: "r", label: "Rating", num: true, render: (t) => ratingCell(t.r, t.rd, { provisional: t.rank == null }) },
    { key: "trend", label: "Trend", hideSm: true, render: (t) => sparkline(t.trend, { label: `Rating trend for ${t.name}` }) },
  ], topTeamsFallback, { caption: "Top 10 teams", captionHidden: true, sortable: false, empty: "No rated teams yet.", rowClass: (t) => (t.rank == null ? "dim" : null) });

  const topPlayersFallback = fill(P.list, P.list.filter((p) => p.rank != null).sort((a, b) => a.rank - b.rank));
  const playerTable = dataTable([
    { key: "rank", label: "#", num: true, cls: "rank", render: (p) => p.rank ?? "–" },
    { key: "name", label: "Player", cls: "name", render: (p) => h("div", null, playerA(P, p.id), h("span", { class: "sub" }, p.school_name || "")) },
    { key: "r", label: "Rating", num: true, render: (p) => ratingCell(p.r, p.se, { provisional: p.rank == null }) },
    { key: "trend", label: "Trend", hideSm: true, render: (p) => sparkline(p.trend, { label: `Rating trend for ${p.name}` }) },
  ], topPlayersFallback, { caption: "Top 10 players", captionHidden: true, sortable: false, empty: "No rated players yet.", rowClass: (p) => (p.rank == null ? "dim" : null) });

  root.appendChild(h("div", { class: "grid-2 section" },
    h("div", null, h("div", { class: "section-head" }, h("h2", null, "Top teams"), h("a", { href: "#/teams" }, "Full leaderboard")), teamTable),
    h("div", null, h("div", { class: "section-head" }, h("h2", null, "Top players"), h("a", { href: "#/players" }, "Full leaderboard")), playerTable)));

  // ---- subject leaders
  const leaders = SUBJECTS.map((sj) => {
    const p = P.list.find((x) => x.subj[sj.key] && x.subj[sj.key].rank === 1);
    const t = schoolTeams.find((x) => x.subj[sj.key] && x.subj[sj.key].rank === 1);
    return h("div", { class: "card leader-card" },
      h("div", { class: "lc-head" }, h("span", { class: "swatch", style: { background: subjColor(sj.key) }, "aria-hidden": "true" }), sj.label),
      p ? h("div", { class: "lc-name" }, playerA(P, p.id)) : h("div", { class: "lc-name muted" }, "No ranked player"),
      p ? h("div", { class: "lc-val" }, `${fmt.r(p.subj[sj.key].r)} ±${Math.round(p.subj[sj.key].se)} · ${p.school_name || ""}`) : null,
      t ? h("div", { class: "lc-val" }, "Top team: ", teamA(T, t.id), ` · ${fmt.r(t.subj[sj.key].r)}`) : null,
      h("div", { class: "lc-val" }, h("a", { href: `#/players?s=${sj.key}` }, `${sj.label} leaderboard`)));
  });
  root.appendChild(section("Subject leaders", "Top-ranked player in each subject", h("div", { class: "grid-3 leaders" }, leaders)));

  // ---- recent tournaments
  const recent = withData.slice(0, 8);
  root.appendChild(section("Recent tournaments", h("a", { href: "#/tournaments" }, "All tournaments"),
    recent.length ? dataTable([
      { key: "date", label: "Date", render: (t) => h("span", { class: "nowrap" }, fmt.range(t.date, t.end)) },
      { key: "name", label: "Tournament", cls: "name", render: (t) => h("div", null, tournamentA(TR, t.id), h("span", { class: "sub" }, t.online ? "Online" : (t.location || ""))) },
      { key: "n_teams", label: "Teams", num: true, render: (t) => (t.individual ? h("span", { title: "Individual event" }, fmt.int(entrantCount(t)), h("span", { class: "sub" }, "competitors")) : fmt.int(t.n_teams)) },
      { key: "strength", label: "Field strength", num: true, title: "Mean pre-tournament rating of the field's top 8 teams", render: (t) => fmt.r(t.strength) },
      { key: "champion", label: "Champion", render: (t) => h("span", { class: "nowrap" }, championA(T, P, t)) },
    ], recent, { sortable: false }) : emptyState("No tournaments yet.")));

  // ---- how ratings work
  root.appendChild(section("How ratings work", null,
    h("div", { class: "card prose" },
      h("p", null, "Team ratings use ", h("strong", null, "Glicko-2"), " on the familiar Elo scale (1500 = average): every game moves both teams by an amount that depends on the expected result, the margin of victory and how certain each rating is. The ± is the rating deviation; teams are ranked once it falls below ",
        String(m.thresholds.ranked_rd), " and they have played in the last ", String(m.thresholds.active_days), " days."),
      h("p", null, "In team games players never face each other one-on-one, so player and subject ratings are ", h("strong", null, "Elo-scaled"),
        ": tossup points per tossup heard, adjusted for the strength of the field, shrunk toward the average when there is little data, and mapped to 1500 + 200 × z."),
      h("p", null, h("a", { href: "#/about" }, "Read the full methodology"), " · ", h("a", { href: "#/compare" }, "Compare two teams")))));
  return root;
}
