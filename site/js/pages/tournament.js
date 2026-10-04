import { h, fmt, dataTable, tile, section, pageHead, notFound, notice, SUBJECTS, subjColor, subjLabel, champBadge, upsetBadge, badge, emptyState, extLink } from "../ui.js";
import { teams, players, tournaments, tournamentDetail } from "../data.js";
import { teamA, playerA, kindLabel, levelBadge } from "../links.js";
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
  ctx.setTitle(row.name);
  const root = h("div");
  root.appendChild(pageHead({
    eyebrow: [h("a", { href: "#/tournaments" }, "Tournaments"), h("span", { "aria-hidden": "true" }, "/"), h("a", { href: `#/tournaments?season=${encodeURIComponent(row.season)}` }, `${row.season} season`),
      badge(kindLabel(row.kind)), levelBadge(row.level), row.subject_only ? badge(`${subjLabel(String(row.subject_only))} only`) : null, row.rated === false && !row.no_data ? badge("Not rated", "off") : null],
    title: row.name,
    sub: [h("span", null, fmt.range(row.date, row.end)), h("span", null, row.online ? "Online" : row.location || "Location not recorded"),
      row.set ? h("span", { class: "muted" }, `Question set: ${row.set}`) : null],
  }));

  const srcs = row.sources || [];
  const srcBlock = h("div", { class: "section" }, h("div", { class: "section-head" }, h("h2", null, "Sources"), h("p", null, "Original results and statistics (open in a new tab)")),
    srcs.length ? h("ul", { class: "plain-list card" }, srcs.map((s) => h("li", null,
      h("span", { class: "li-main" }, extLink(s.url, ({ results: "Results", stats: "Statistics", "results+stats": "Results and statistics", "results+scoresheets": "Results and scoresheets" })[s.role] || "Source")),
      h("span", { class: "muted" }, ({ gsheet: "Google Sheets", isobowl: "ISOBowl", scibowl_live: "scibowl.live", challonge: "Challonge", drive_folder: "Google Drive", drive_file: "Google Drive", url: (() => { try { return new URL(s.url).hostname.replace(/^www\./, ""); } catch { return "link"; } })() })[s.kind] || s.kind || ""))))
      : emptyState("No source links recorded."),
    row.notes ? h("div", { class: "data-notes" }, h("h3", null, "Data notes"), h("p", null, row.notes)) : null);

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

  root.appendChild(h("div", { class: "tiles section" },
    tile("Teams", fmt.int(row.n_teams)),
    tile("Games", fmt.int(row.n_games), row.n_scored < row.n_games ? `${fmt.int(row.n_scored)} with scores` : "all with scores"),
    tile("Players with stats", row.n_players ? fmt.int(row.n_players) : "–"),
    tile("Field strength", fmt.r(row.strength), "mean rating of the top 8"),
    tile("Champion", row.champion ? h("span", { class: "tile-text" }, teamA(T, row.champion)) : "–",
      row.champion ? "won the final playoff game" : (t.games || []).some((g) => g.st === "playoff") ? "final result not published" : "no playoff recorded"),
    tile("Data", coverageBadges(row))));

  // ---- standings
  const champ = row.champion;
  root.appendChild(section("Standings", "Sorted by wins, then fewest losses, then points per game", dataTable([
    { key: "i", label: "#", num: true, cls: "rank", render: (r, i) => i + 1 },
    { key: "tm", label: "Team", cls: "name", sort: (r) => (T.byId.get(r.tm) || {}).name || r.raw,
      render: (r) => {
        const tm = T.byId.get(r.tm);
        const norm = (x) => String(x || "").toLowerCase().replace(/\s+/g, " ").trim();
        const differs = tm && r.raw && norm(r.raw) !== norm(tm.name) && norm(r.raw) !== norm(tm.name.replace(/ [A-H]$/, ""));
        return h("div", null, teamA(T, r.tm), differs ? h("span", { class: "sub" }, `listed as “${r.raw}”`) : null);
      } },
    { key: "rec", label: "W–L–T", num: true, sort: (r) => (r.g ? (r.w + 0.5 * r.t) / r.g : null), render: (r) => fmt.record(r.w, r.l, r.t) },
    { key: "g", label: "Games", num: true, sort: (r) => r.g, render: (r) => r.g },
    { key: "ppg", label: "PPG", num: true, sort: (r) => r.ppg, render: (r) => fmt.num(r.ppg) },
    { key: "papg", label: "PAPG", num: true, title: "Points allowed per game", sort: (r) => r.papg, render: (r) => fmt.num(r.papg) },
    { key: "mrg", label: "Margin", num: true, sort: (r) => (r.ppg != null ? r.ppg - r.papg : null), render: (r) => (r.ppg != null ? fmt.signed(r.ppg - r.papg, 1) : "–") },
    { key: "rating", label: "Rating now", num: true, title: "Current overall rating", sort: (r) => (T.byId.get(r.tm) || {}).r, render: (r) => fmt.r((T.byId.get(r.tm) || {}).r) },
    { key: "note", label: "", render: (r) => (r.tm === champ ? champBadge() : "") },
  ], t.teams || [], { empty: "No standings." })));

  // ---- games by stage / round
  root.appendChild(gamesSection(t.games || [], T));

  // ---- player stats
  root.appendChild(playerSection(t.players || [], P, T));
  root.appendChild(srcBlock);
  return root;
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

function playerSection(rows, P, T) {
  if (!rows.length) return section("Player stats", null, emptyState("No individual statistics were published for this tournament."));
  const sv = (r, subj, k) => (r.s[subj] ? r.s[subj][k] : null);
  const ppg = (r) => { const o = r.s.overall; if (!o) return null; if (o.ppg != null) return o.ppg; return o.pts != null && o.gp ? o.pts / o.gp : null; };
  const ptuh = (r) => { const o = r.s.overall; return o && o.tuh && o.pts != null ? o.pts / o.tuh : null; };
  const hasSubj = rows.some((r) => SUBJECTS.some((x) => r.s[x.key]));
  const columns = [
    { key: "p", label: "Player", cls: "name", sort: (r) => (P.byId.get(r.p) || {}).name || r.p, render: (r) => playerA(P, r.p) },
    { key: "tm", label: "Team", cls: "team", sort: (r) => (T.byId.get(r.tm) || {}).name || r.tm, render: (r) => teamA(T, r.tm, { pickup: false }) },
    { key: "gp", label: "GP", num: true, sort: (r) => sv(r, "overall", "gp"), render: (r) => { const g = sv(r, "overall", "gp"); return g == null ? "–" : (r.s.overall.gp_est ? "≈" : "") + fmt.num(g, 0); } },
    { key: "tuh", label: "TUH", num: true, title: "Tossups heard", sort: (r) => sv(r, "overall", "tuh"), render: (r) => fmt.int(sv(r, "overall", "tuh")) },
    { key: "c", label: "4s", num: true, title: "Correct tossups", sort: (r) => sv(r, "overall", "c"), render: (r) => fmt.int(sv(r, "overall", "c")) },
    { key: "n", label: "Negs", num: true, title: "Interrupt penalties", sort: (r) => sv(r, "overall", "n"), render: (r) => fmt.int(sv(r, "overall", "n")) },
    { key: "pts", label: "Pts", num: true, title: "Tossup points", sort: (r) => sv(r, "overall", "pts"), render: (r) => fmt.int(sv(r, "overall", "pts")) },
    { key: "ppg", label: "PPG", num: true, sort: ppg, render: (r) => fmt.num(ppg(r)) },
    { key: "ptuh", label: "P/TUH", num: true, sort: ptuh, render: (r) => fmt.num(ptuh(r), 2) },
    ...(hasSubj ? SUBJECTS.map((x) => ({
      key: x.key, num: true, title: `${x.label} tossup points`, sort: (r) => sv(r, x.key, "pts"),
      label: h("span", { class: "subj-label" }, h("span", { class: "swatch", style: { background: subjColor(x.key) }, "aria-hidden": "true" }), x.short),
      render: (r) => fmt.int(sv(r, x.key, "pts")),
    })) : []),
  ];
  return section("Player stats", `${fmt.plural(rows.length, "player")} · tossup points as published; ≈ marks inferred games played`,
    dataTable(columns, rows, { sort: { key: "pts", dir: "desc" }, pageSize: 100, caption: "Player statistics", captionHidden: true, tableClass: "compact" }));
}
