import { h, fmt, delta, dataTable, tile, section, pageHead, notFound, notice, SUBJECTS, subjColor, subjLabel, champBadge, upsetBadge, badge, emptyState, extLink } from "../ui.js";
import { teams, players, tournaments, tournamentDetail } from "../data.js";
import { teamA, playerA, kindLabel, levelBadge, championA, sourceRoleLabel, sourceKindLabel } from "../links.js";
import { coverageBadges } from "./tournaments.js";

const STAGE = { rr: "Round robin", playoff: "Playoffs", consolation: "Consolation", prelim: "Preliminaries", final: "Finals" };

function gameUpset(g) {
  if (g.p1 == null || g.ff) return false;
  return (g.res === "1" && g.p1 <= 0.3) || (g.res === "2" && g.p1 >= 0.7);
}

export async function render(ctx) {
  const id = ctx.param;
  const [T, P, TR] = await Promise.all([teams(), players(), tournaments()]);
  const row = TR.byId.get(id);
  if (!row) { ctx.setTitle("Tournament not found"); return notFound("Tournament", id); }
  const t = await tournamentDetail(id);
  // recurring events share a name ("NSB National Finals"): add the year to the window title
  ctx.setTitle(/\b(19|20)\d\d\b/.test(row.name) ? row.name : `${row.name} ${(row.date || "").slice(0, 4)}`.trim());
  const root = h("div");
  root.appendChild(pageHead({
    eyebrow: [h("a", { href: "#/tournaments" }, "Tournaments"), h("span", { "aria-hidden": "true" }, "/"), h("a", { href: `#/tournaments?season=${encodeURIComponent(row.season)}` }, `${row.season} season`),
      badge(kindLabel(row.kind)), row.individual ? badge("Individual · 1v1") : null, levelBadge(row.level), row.subject_only ? badge(`${subjLabel(String(row.subject_only))} only`) : null, row.rated === false && !row.no_data ? badge("Not rated", "off") : null],
    title: row.name,
    sub: [h("span", null, fmt.range(row.date, row.end)), h("span", null, row.online ? "Online" : row.location || "Location not recorded"),
      row.set ? h("span", { class: "muted" }, `Question set: ${row.set}`) : null],
  }));

  const srcs = row.sources || [];
  const srcBlock = h("div", { class: "section" }, h("div", { class: "section-head" }, h("h2", null, "Sources"), h("p", null, "Original results and statistics (open in a new tab)")),
    srcs.length ? h("ul", { class: "plain-list card" }, srcs.map((s) => h("li", null,
      h("span", { class: "li-main" }, extLink(s.url, sourceRoleLabel(s.role))),
      h("span", { class: "muted" }, sourceKindLabel(s)))))
      : emptyState("No source links recorded."),
    // notes are written for maintainers (parsing caveats): available, but collapsed
    row.notes ? h("details", { class: "data-notes" }, h("summary", null, "Data notes"), h("p", null, row.notes)) : null);

  if (row.no_data) {
    const why = row.status === "todo" && srcs.length
      ? "Results for this tournament have not been processed yet; they will appear after a future data update."
      : srcs.length
        ? "This tournament is listed for completeness, but no results or statistics could be obtained from the linked sources."
        : "This tournament is listed for completeness; no published results or statistics are known for it.";
    root.appendChild(h("div", { class: "section" }, notice(h("span", null, h("strong", null, "No results available. "), why), "info")));
    root.appendChild(srcBlock);
    return root;
  }

  if (row.individual) {
    renderIndividual(root, row, t, P, T, TR);
    root.appendChild(srcBlock);
    return root;
  }

  root.appendChild(h("div", { class: "tiles section" },
    tile("Teams", fmt.int(row.n_teams)),
    tile("Games", fmt.int(row.n_games), row.n_scored < row.n_games ? `${fmt.int(row.n_scored)} with scores` : "all with scores"),
    tile("Players with stats", row.n_players ? fmt.int(row.n_players) : "–"),
    tile("Field strength", fmt.r(row.strength), row.strength != null ? "mean rating of the top 8" : row.rated === false ? "not computed for unrated events" : null),
    tile("Champion", row.champion ? h("span", { class: "tile-text" }, teamA(T, row.champion)) : "–",
      row.champion ? "won the final playoff game" : (t.games || []).some((g) => g.st === "playoff") ? "final result not published" : "no playoff recorded"),
    tile("Data", coverageBadges(row))));

  // ---- standings
  const champ = row.champion;
  const scored = (t.teams || []).some((r) => r.ppg != null);
  const rated = (t.teams || []).some((r) => r.dr != null);
  root.appendChild(section("Standings", (t.games || []).some((g) => g.st === "playoff") ? (scored ? "Playoff finish first, then wins, fewest losses and points per game" : "Playoff finish first, then wins and fewest losses (no scores were published)") : (scored ? "Sorted by wins, then fewest losses, then points per game" : "Sorted by wins, then fewest losses (no scores were published)"), dataTable([
    { key: "i", label: "#", num: true, cls: "rank", render: (r, i) => i + 1 },
    { key: "tm", label: "Team", cls: "name", sort: (r) => (T.byId.get(r.tm) || {}).name || r.raw,
      render: (r) => {
        const tm = T.byId.get(r.tm);
        // note the published name only when it says more than the team's or school's name: its words
        // (ignoring generic ones like "High School") are not all part of either
        const GENERIC = new Set(["high", "school", "senior", "junior", "hs", "the", "of", "and", "a", "b", "c", "d", "team"]);
        const words = (x) => String(x || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, " ").trim().split(" ").filter((w) => w && !GENERIC.has(w) && !/^\d$/.test(w));
        const known = new Set(tm ? [...words(tm.name), ...words(tm.school_name)] : []);
        const rawWords = words(r.raw);
        const differs = tm && rawWords.length && !rawWords.every((w) => known.has(w));
        return h("div", null, teamA(T, r.tm), differs ? h("span", { class: "sub" }, `listed as “${r.raw}”`) : null);
      } },
    { key: "rec", label: "W–L–T", num: true, sort: (r) => (r.g ? (r.w + 0.5 * r.t) / r.g : null), render: (r) => fmt.record(r.w, r.l, r.t) },
    { key: "g", label: "Games", num: true, sort: (r) => r.g, render: (r) => r.g },
    ...(scored ? [
      { key: "ppg", label: "PPG", num: true, sort: (r) => r.ppg, render: (r) => fmt.num(r.ppg) },
      { key: "papg", label: "PAPG", num: true, title: "Points allowed per game", sort: (r) => r.papg, render: (r) => fmt.num(r.papg) },
      { key: "mrg", label: "Margin", num: true, sort: (r) => (r.ppg != null ? r.ppg - r.papg : null), render: (r) => (r.ppg != null ? fmt.signed(r.ppg - r.papg, 1) : "–") },
    ] : []),
    ...(rated ? [
      { key: "post", label: "Rating", num: true, title: "Overall rating after this tournament (before → after)", sort: (r) => r.post,
        render: (r) => (r.post == null ? "–" : h("span", { class: "nowrap" }, r.pre != null ? h("span", { class: "muted" }, `${fmt.r(r.pre)} → `) : null, fmt.r(r.post))) },
      { key: "dr", label: "Change", num: true, title: "Change in overall rating at this tournament", sort: (r) => r.dr, render: (r) => delta(r.dr) },
    ] : []),
    { key: "rating", label: "Rating now", num: true, hideSm: true, title: "Current overall rating", sort: (r) => (T.byId.get(r.tm) || {}).r, render: (r) => fmt.r((T.byId.get(r.tm) || {}).r) },
    { key: "note", label: "", render: (r) => (r.tm === champ ? champBadge() : "") },
  ], t.teams || [], { empty: "No standings." })));

  // ---- games by stage / round
  root.appendChild(gamesSection(t.games || [], T));

  // ---- player stats
  root.appendChild(playerSection(t.players || [], P, T));
  root.appendChild(srcBlock);
  return root;
}

/** 1v1 events: competitors are people (no team entries); standings come from their games. */
function renderIndividual(root, row, t, P, T, TR) {
  const subj = row.subject_only ? String(row.subject_only) : null;
  // competitors (computed from the 1v1 games); older data files only have the players array
  const comps = t.competitors && t.competitors.length ? t.competitors
    : (t.players || []).map((r) => ({ name: (P.byId.get(r.p) || {}).name || r.p, p: r.p }));
  const nComp = row.n_competitors ?? comps.length;
  root.appendChild(h("div", { class: "tiles section" },
    tile("Format", h("span", { class: "tile-text" }, "Individual event"), `${fmt.plural(nComp, "competitor")} · one-on-one games`),
    tile("Games", fmt.int(row.n_games), row.n_games ? (row.n_scored < row.n_games ? `${fmt.int(row.n_scored)} with scores` : "all with scores") : null),
    tile("Players with stats", row.n_players ? fmt.int(row.n_players) : "–", row.n_players ? null : "no statistics published"),
    tile("Champion", row.champion_name ? h("span", { class: "tile-text" }, championA(T, P, row)) : "–",
      row.champion_name ? "won the final playoff game" : "final result not published"),
    tile("Data", coverageBadges(row))));
  const rating = (c) => {
    const p = c.p && P.byId.get(c.p);
    if (!p) return null;
    return subj ? (p.subj[subj] ? p.subj[subj].r : null) : p.r;
  };
  const hasRec = comps.some((c) => c.g != null);
  const columns = [
    { key: "i", label: "#", num: true, cls: "rank", render: (c, i) => i + 1 },
    { key: "name", label: "Competitor", cls: "name", sort: (c) => c.name,
      render: (c) => (c.p && P.byId.has(c.p) ? playerA(P, c.p) : h("span", null, c.name)) },
    ...(hasRec ? [
      { key: "rec", label: "W–L–T", num: true, sort: (c) => (c.g ? (c.w + 0.5 * c.t) / c.g : null), render: (c) => (c.g ? fmt.record(c.w, c.l, c.t) : "–") },
      { key: "g", label: "Games", num: true, sort: (c) => c.g, render: (c) => fmt.int(c.g) },
      { key: "ppg", label: "PPG", num: true, sort: (c) => c.ppg, render: (c) => fmt.num(c.ppg) },
      { key: "papg", label: "PAPG", num: true, title: "Points allowed per game", sort: (c) => c.papg, render: (c) => fmt.num(c.papg) },
    ] : []),
    comps.some((c) => c.p) ? { key: "rating", label: subj ? `${subjLabel(subj, true)} rating now` : "Rating now", num: true, title: subj ? `Current ${subjLabel(subj)} rating` : "Current overall rating", sort: rating, render: (c) => fmt.r(rating(c)) } : null,
    { key: "note", label: "", render: (c) => (c.champ ? champBadge() : "") },
  ].filter(Boolean);
  const sub = hasRec
    ? `${fmt.plural(nComp, "competitor")} · records from the one-on-one games, which are not listed individually and do not affect team ratings`
    : `${fmt.plural(nComp, "competitor")}`;
  root.appendChild(section("Competitors", sub, dataTable(columns, comps, {
    caption: "Competitors", captionHidden: true, pageSize: 100,
    empty: "No competitors recorded.",
  })));
  root.appendChild(playerSection(t.players || [], P, T, { individual: true }));
}

function gamesSection(games, T) {
  if (!games.length) return section("Games", null, emptyState("No games recorded."));
  const stages = new Map();
  for (const g of games) {
    const st = g.st || "other";
    if (!stages.has(st)) stages.set(st, new Map());
    const rounds = stages.get(st);
    const rd = g.rd || "Games";
    if (!rounds.has(rd)) rounds.set(rd, []);
    rounds.get(rd).push(g);
  }
  const wrap = h("div", { class: "stack" });
  const order = [...stages.keys()].sort((a, b) => Math.min(...[...stages.get(a).values()].flat().map((g) => g.seq)) - Math.min(...[...stages.get(b).values()].flat().map((g) => g.seq)));
  const nUpsets = games.filter(gameUpset).length;
  for (const st of order) {
    const rounds = [...stages.get(st).entries()].sort((a, b) => Math.min(...a[1].map((g) => g.seq)) - Math.min(...b[1].map((g) => g.seq)));
    const n = rounds.reduce((a, r) => a + r[1].length, 0);
    const table = h("table", { class: "tbl games-tbl" },
      h("caption", { class: "sr-only" }, `${STAGE[st] || st} games`),
      h("colgroup", null, h("col", { style: { width: "34%" } }), h("col", { style: { width: "13%" } }), h("col", { style: { width: "34%" } }), h("col", { style: { width: "10%" } }), h("col", { style: { width: "9%" } })),
      h("thead", null, h("tr", null,
        h("th", { scope: "col", class: "num" }, "Team 1"), h("th", { scope: "col", class: "ctr" }, "Score"), h("th", { scope: "col" }, "Team 2"),
        h("th", { scope: "col", class: "num", title: "Pre-game win probability for team 1 / team 2" }, "Win prob."), h("th", { scope: "col" }, ""))));
    for (const [rd, gl] of rounds) {
      gl.sort((a, b) => a.seq - b.seq || String(a.id).localeCompare(String(b.id), undefined, { numeric: true }));
      const tb = h("tbody", null, h("tr", { class: "group-row" }, h("th", { colspan: "5", scope: "colgroup" }, rd)));
      for (const g of gl) {
        const up = gameUpset(g);
        const w1 = g.res === "1", w2 = g.res === "2";
        tb.appendChild(h("tr", { class: up ? "upset" : null },
          h("td", { class: ["num", w1 ? "won" : null], style: { "white-space": "normal" } }, teamA(T, g.t1, { pickup: false })),
          h("td", { class: "ctr nowrap num", title: g.s1 == null && !g.ff ? "Score not published" : null },
            g.ff ? "forfeit" : g.s1 != null ? `${fmt.int(g.s1)} – ${fmt.int(g.s2)}` : g.res === "T" ? "tie" : w1 ? "W – L" : w2 ? "L – W" : "–"),
          h("td", { class: w2 ? "won" : null }, teamA(T, g.t2, { pickup: false })),
          h("td", { class: "num" }, g.p1 != null ? `${Math.round(g.p1 * 100)} / ${100 - Math.round(g.p1 * 100)}` : h("span", { class: "muted", title: "Unrated game" }, "–")),
          h("td", null, up ? upsetBadge() : g.res === "T" ? badge("Tie") : "")));
      }
      table.appendChild(tb);
    }
    wrap.appendChild(h("details", { class: "card", open: st !== "rr" || n <= 60 },
      h("summary", { style: { cursor: "pointer" } }, h("strong", null, STAGE[st] || st), h("span", { class: "muted" }, ` · ${fmt.plural(n, "game")}`)),
      h("div", { class: "table-wrap bare", style: { "margin-top": "8px" } }, table)));
  }
  return section("Games", `${fmt.plural(games.length, "game")} by stage and round${nUpsets ? ` · ${fmt.plural(nUpsets, "upset")} (loser had a pre-game win probability of 70% or more)` : ""}`, wrap);
}

function playerSection(rows, P, T, { individual = false } = {}) {
  if (!rows.length) return section("Player stats", null, emptyState("No individual statistics were published for this tournament."));
  const sv = (r, subj, k) => (r.s[subj] ? r.s[subj][k] : null);
  const ppg = (r) => { const o = r.s.overall; if (!o) return null; if (o.ppg != null) return o.ppg; return o.pts != null && o.gp ? o.pts / o.gp : null; };
  const ptuh = (r) => { const o = r.s.overall; return o && o.tuh && o.pts != null ? o.pts / o.tuh : null; };
  const hasSubj = rows.some((r) => SUBJECTS.some((x) => r.s[x.key]));
  const hasChange = rows.some((r) => r.post != null);
  const columns = [
    { key: "p", label: "Player", cls: "name", sort: (r) => (P.byId.get(r.p) || {}).name || r.p, render: (r) => playerA(P, r.p) },
    individual ? null : { key: "tm", label: "Team", cls: "team", sort: (r) => (T.byId.get(r.tm) || {}).name || r.tm, render: (r) => teamA(T, r.tm, { pickup: false }) },
    { key: "gp", label: "GP", num: true, sort: (r) => sv(r, "overall", "gp"), render: (r) => { const g = sv(r, "overall", "gp"); return g == null ? "–" : (r.s.overall.gp_est ? "≈" : "") + fmt.num(g, 0); } },
    { key: "tuh", label: "TUH", num: true, title: "Tossups heard", sort: (r) => sv(r, "overall", "tuh"), render: (r) => fmt.int(sv(r, "overall", "tuh")) },
    { key: "c", label: "4s", num: true, title: "Correct tossups", sort: (r) => sv(r, "overall", "c"), render: (r) => fmt.int(sv(r, "overall", "c")) },
    { key: "n", label: "Negs", num: true, title: "Interrupt penalties", sort: (r) => sv(r, "overall", "n"), render: (r) => fmt.int(sv(r, "overall", "n")) },
    { key: "pts", label: "Pts", num: true, title: "Tossup points", sort: (r) => sv(r, "overall", "pts"), render: (r) => fmt.int(sv(r, "overall", "pts")) },
    { key: "ppg", label: "PPG", num: true, sort: ppg, render: (r) => fmt.num(ppg(r)) },
    { key: "ptuh", label: "P/TUH", num: true, sort: ptuh, render: (r) => fmt.num(ptuh(r), 2) },
    hasChange ? { key: "post", label: "Rating", num: true, title: "Overall player rating after this tournament", sort: (r) => r.post, render: (r) => fmt.r(r.post) } : null,
    hasChange ? { key: "dr", label: "Change", num: true, title: "Change in overall player rating since the player's previous tournament", sort: (r) => r.dr, render: (r) => (r.post != null && r.dr == null ? h("span", { class: "muted", title: "First rated tournament" }, "new") : delta(r.dr)) } : null,
    ...(hasSubj ? SUBJECTS.map((x) => ({
      key: x.key, num: true, title: `${x.label} tossup points`, sort: (r) => sv(r, x.key, "pts"),
      label: h("span", { class: "subj-label" }, h("span", { class: "swatch", style: { background: subjColor(x.key) }, "aria-hidden": "true" }), x.short),
      render: (r) => fmt.int(sv(r, x.key, "pts")),
    })) : []),
  ].filter(Boolean);
  return section("Player stats", `${fmt.plural(rows.length, "player")} · tossup points as published; ≈ marks inferred games played`,
    dataTable(columns, rows, { sort: { key: "pts", dir: "desc" }, pageSize: 100, caption: "Player statistics", captionHidden: true, tableClass: "compact" }));
}
