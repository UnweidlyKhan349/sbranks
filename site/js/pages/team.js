import { h, fmt, dataTable, tile, section, pageHead, notFound, SUBJECTS, subjColor, subjTag, delta, resultBadge, champBadge, upsetBadge, badge, parseDate, href, emptyState } from "../ui.js";
import { lineChart, refBars, attachTip, tipContent, seqBin, rampLegend } from "../charts.js";
import { meta, teams, players, schools, tournaments, teamDetail, isActive } from "../data.js";
import { teamA, playerA, schoolA, tournamentA } from "../links.js";

export function isUpset(result, p) {
  if (p == null) return false;
  return (result === "L" && p >= 0.7) || (result === "W" && p <= 0.3);
}

export async function render(ctx) {
  const id = ctx.param;
  const [m, T, P, TR, S] = await Promise.all([meta(), teams(), players(), tournaments(), schools()]);
  const t = T.byId.get(id);
  if (!t) { ctx.setTitle("Team not found"); return notFound("Team", id); }
  const d = (await teamDetail(id)) || { history: [], games: [], tournaments: [], roster: {}, subj_history: {}, coverage: null };
  ctx.setTitle(t.name);
  const aff = t.affiliate ? S.byId.get(t.affiliate) || { id: t.affiliate, name: t.affiliate } : null;
  const root = h("div");
  // school teams are ranked among school teams; pickup teams among all teams (rank_open)
  const rk = t.composite ? "rank_open" : "rank";
  const nRanked = T.list.filter((x) => x[rk] != null).length;
  const active = isActive(t.last, m);

  root.appendChild(pageHead({
    eyebrow: [h("a", { href: "#/teams" }, "Teams"), h("span", { "aria-hidden": "true" }, "/"),
      t.composite ? "Pickup team" : schoolA(t.school, t.school_name), t.state ? h("span", { class: "muted" }, t.state) : null,
      t.composite ? badge("Pickup / composite team") : null],
    title: t.name,
    sub: [
      t.composite ? (aff ? h("span", null, "Players mostly from ", schoolA(aff.id, aff.name)) : h("span", null, "Players from several schools")) : null,
      h("span", null, t.seasons.length ? `Seasons ${t.seasons[0]}${t.seasons.length > 1 ? " – " + t.seasons[t.seasons.length - 1] : ""}` : "No seasons"),
      h("span", null, `Last played ${fmt.date(t.last)}`),
      h("a", { href: `#/compare?type=teams&a=${encodeURIComponent(t.id)}` }, "Compare with another team"),
    ],
  }));

  // ---- header stats
  // same rule as a player's best subject (pipeline/export.py): at least 8 effective tossups heard
  const subjBest = SUBJECTS.map((x) => ({ k: x.key, v: t.subj[x.key] })).filter((x) => x.v && x.v.r != null && x.v.n >= 8).sort((a, b) => b.v.r - a.v.r)[0];
  root.appendChild(h("div", { class: "tiles" },
    tile("Rating", t.r != null ? [fmt.r(t.r), h("span", { class: "pm" }, fmt.pm(t.rd))] : "Unrated", t.r != null ? "Glicko-2 ± deviation" : "No rated games yet"),
    tile("Rank", t[rk] != null ? `#${t[rk]}` : "Unranked",
      t[rk] != null ? `of ${fmt.int(nRanked)} ranked teams${t.composite ? " incl. pickup teams" : ""}` : t.r == null ? "–" : !active ? "Inactive" : `Provisional (± above ${m.thresholds.ranked_rd})`),
    tile("Record", t.g ? fmt.record(t.w, t.l, t.t) : "–", `${fmt.plural(t.g, "rated game")}`),
    tile("Peak rating", fmt.r(t.peak), t.peak != null ? "after a tournament" : null),
    tile("Tournaments", fmt.int(t.n_t), t.seasons.length > 1 ? `in ${t.seasons.length} seasons` : t.seasons[0] || null),
    tile("Best subject", subjBest ? subjTag(subjBest.k) : "–", subjBest ? `${fmt.r(subjBest.v.r)} ±${Math.round(subjBest.v.se)}` : null)));

  // ---- rating history
  const tname = (tid) => (TR.byId.get(tid) || {}).name || tid;
  const hist = d.history || [];
  const pts = hist.map((x) => ({ x: parseDate(x.date), y: x.r, lo: x.r - x.rd, hi: x.r + x.rd, rd: x.rd, delta: x.delta, tid: x.tournament_id, date: x.date }));
  const byX = new Map(pts.map((p) => [p.x, p]));
  const histChart = lineChart([{ id: "r", label: "Rating", color: "var(--s1)", points: pts, band: true }], {
    label: `Rating history for ${t.name}`, refY: 1500, refLabel: "1500 = average", height: 260,
    empty: "No rated games yet, so there is no rating history.",
    tip: (x) => {
      const p = byX.get(x);
      return { title: tname(p.tid), sub: fmt.date(p.date), rows: [
        { color: "var(--s1)", value: `${fmt.r(p.y)} ±${Math.round(p.rd)}` },
        { value: fmt.signed(p.delta) }] };
    },
    table: {
      columns: [
        { key: "date", label: "Date", render: (p) => fmt.date(p.date) },
        { key: "t", label: "Tournament", render: (p) => tournamentA(TR, p.tid) },
        { key: "r", label: "Rating", num: true, render: (p) => fmt.r(p.y) },
        { key: "rd", label: "±", num: true, render: (p) => Math.round(p.rd) },
        { key: "delta", label: "Change", num: true, render: (p) => fmt.signed(p.delta) },
      ], rows: pts.slice().reverse(),
    },
  });
  // ---- subject ratings
  const minN = m.thresholds.player_min_tuh;
  const cats = SUBJECTS.map((x) => {
    const v = t.subj[x.key];
    return { key: x.key, label: x.label, sub: v ? (v[rk] ? `rank ${v[rk]}` : fmt.plural(v.n, "tossup")) : null };
  });
  const vals = {};
  for (const x of SUBJECTS) {
    const v = t.subj[x.key];
    if (v) vals[x.key] = { value: v.r, lo: v.r - v.se, hi: v.r + v.se, pm: v.se, provisional: v.n < (minN[x.key] || 25) };
  }
  const subjChart = refBars(cats, [{ label: "Subject rating", color: "var(--s1)", values: vals }], {
    label: `Subject ratings for ${t.name}`,
    tip: (c) => {
      const v = t.subj[c.key];
      return v ? { title: c.label, rows: [
        { color: "var(--s1)", kind: "rect", value: `${fmt.r(v.r)} ±${Math.round(v.se)}`, label: v.n < (minN[c.key] || 25) ? "provisional" : "rating" },
        { value: v[rk] ? `#${v[rk]}` : "unranked", label: "rank" },
        { value: fmt.int(v.n), label: "effective tossups heard" }] } : { title: c.label, rows: [{ value: "no data" }] };
    },
    table: {
      columns: [
        { key: "s", label: "Subject", render: (r) => r.label },
        { key: "r", label: "Rating", num: true, render: (r) => (r.v ? fmt.r(r.v.r) : "–") },
        { key: "se", label: "±", num: true, render: (r) => (r.v ? Math.round(r.v.se) : "–") },
        { key: "rank", label: "Rank", num: true, render: (r) => (r.v && r.v[rk] ? r.v[rk] : "–") },
        { key: "n", label: "Tossups", num: true, render: (r) => (r.v ? r.v.n : "–") },
      ], rows: SUBJECTS.map((x) => ({ label: x.label, v: t.subj[x.key] })),
    },
  });
  root.appendChild(h("div", { class: "grid-2 section" },
    h("div", { class: "card" }, h("h2", { class: "chart-title" }, "Rating history"), h("p", { class: "chart-sub" }, "After each rated tournament; the band is ± one rating deviation"), histChart),
    h("div", { class: "card" }, h("h2", { class: "chart-title" }, "Subject ratings"), h("p", { class: "chart-sub" }, "Elo-scaled points per tossup heard by the team's players; faded bars are provisional"), subjChart)));

  // ---- subject coverage matrix
  root.appendChild(coverageSection(t, d, P));

  // ---- tournaments
  const histByT = new Map(hist.map((x) => [x.tournament_id, x]));
  const tours = (d.tournaments || []).slice().reverse();
  root.appendChild(section("Tournaments", `${fmt.plural(tours.length, "tournament")}`, dataTable([
    { key: "d", label: "Date", sort: (r) => r.d, defaultDir: "desc", render: (r) => h("span", { class: "nowrap" }, fmt.date(r.d)) },
    { key: "t", label: "Tournament", cls: "name", sort: (r) => tname(r.t), render: (r) => tournamentA(TR, r.t) },
    { key: "rec", label: "W–L–T", num: true, sort: (r) => (r.g ? (r.w + 0.5 * (r.tie || 0)) / r.g : null), render: (r) => fmt.record(r.w, r.l, r.tie) },
    { key: "ppg", label: "PPG", num: true, sort: (r) => r.ppg, render: (r) => fmt.num(r.ppg) },
    { key: "champ", label: "Result", render: (r) => (r.champ ? champBadge() : "") },
    { key: "after", label: "Rating after", num: true, sort: (r) => histByT.get(r.t)?.r, render: (r) => { const x = histByT.get(r.t); return x ? fmt.r(x.r) : h("span", { class: "muted", title: "Unrated event" }, "–"); } },
    { key: "delta", label: "Change", num: true, sort: (r) => histByT.get(r.t)?.delta, render: (r) => { const x = histByT.get(r.t); return x ? delta(x.delta) : ""; } },
  ], tours, { sort: { key: "d", dir: "desc" }, empty: "No tournaments." })));

  // ---- games log grouped by tournament
  root.appendChild(gamesSection(t, d, T, TR));

  // ---- head to head
  root.appendChild(h2hSection(d, T, t.id));

  // ---- roster by season
  const seasons = Object.keys(d.roster || {}).sort().reverse();
  root.appendChild(section("Roster by season", "Players with published individual stats for this team",
    seasons.length ? h("div", { class: "card" }, h("ul", { class: "plain-list" }, seasons.map((sn) => h("li", null,
      h("div", { class: "li-main" }, h("div", { class: "secondary", style: { "font-size": "13px", "margin-bottom": "6px" } }, sn),
        h("div", { class: "chips" }, d.roster[sn].map((pid) => {
          const p = P.byId.get(pid);
          return h("a", { class: "chip", href: href.player(pid) }, p ? p.name : pid, p && p.r != null ? h("span", { class: "muted" }, fmt.r(p.r)) : null);
        })))))))
      : emptyState("No individual statistics were published for this team.")));
  return root;
}

function coverageSection(t, d, P) {
  const cov = d.coverage;
  if (!cov || !cov.players || !cov.players.length) {
    return section("Subject coverage", null, emptyState("No per-subject player statistics are available for this team."));
  }
  const subjMax = Math.max(1, ...cov.players.flatMap((p) => SUBJECTS.map((x) => p.pts[x.key] || 0)));
  const teamTot = Object.fromEntries(SUBJECTS.map((x) => [x.key, cov.players.reduce((a, p) => a + Math.max(0, p.pts[x.key] || 0), 0)]));
  const columns = [
    { key: "p", label: "Player", cls: "name", render: (r) => playerA(P, r.p) },
    { key: "gp", label: "GP", num: true, render: (r) => fmt.int(r.gp) },
    { key: "overall", label: "Total", num: true, render: (r) => fmt.int(r.pts.overall) },
    ...SUBJECTS.map((x) => ({
      key: x.key, num: true, cls: "cell",
      label: h("span", { class: "subj-label" }, h("span", { class: "swatch", style: { background: subjColor(x.key) }, "aria-hidden": "true" }), x.short),
      render: (r) => {
        const v = r.pts[x.key];
        return v == null ? "–" : String(Math.round(v));
      },
    })),
  ];
  const tbl = dataTable(columns, cov.players, { sortable: false, caption: `Tossup points by subject, ${cov.season}`, captionHidden: true, tableClass: "matrix" });
  // colour cells + attach tooltips after render
  const rows = tbl.table.tBodies[0].rows;
  cov.players.forEach((pl, i) => {
    const tr = rows[i];
    if (!tr) return;
    SUBJECTS.forEach((x, j) => {
      const td = tr.cells[3 + j];
      const v = pl.pts[x.key];
      const q = seqBin(v, subjMax);
      if (q) td.dataset.q = String(q);
      else td.classList.add("zero");
      td.tabIndex = 0;
      const name = (P.byId.get(pl.p) || {}).name || pl.p;
      const share = v != null && teamTot[x.key] > 0 && v > 0 ? `${Math.round((100 * v) / teamTot[x.key])}% of the team's ${x.label.toLowerCase()} points` : "";
      td.setAttribute("aria-label", `${name}, ${x.label}: ${v == null ? "no points" : Math.round(v) + " points"}`);
      attachTip(td, () => tipContent({ title: name, sub: x.label, rows: [{ value: v == null ? "–" : `${Math.round(v)} pts`, label: share }] }));
    });
  });
  return section("Subject coverage", h("p", null, `Tossup points by subject in the ${cov.season} season `, rampLegend(0, Math.round(subjMax))), tbl);
}

function gamesSection(t, d, T, TR) {
  const games = d.games || [];
  if (!games.length) return section("Games", null, emptyState("No games recorded."));
  const byT = new Map();
  for (const g of games) {
    if (!byT.has(g.t)) byT.set(g.t, []);
    byT.get(g.t).push(g);
  }
  const groups = [...byT.entries()].sort((a, b) => (b[1][0].d).localeCompare(a[1][0].d));
  const wrap = h("div", { class: "stack" });
  groups.forEach(([tid, gl], i) => {
    gl.sort((a, b) => a.seq - b.seq);
    const w = gl.filter((g) => g.r === "W" && !g.ff).length, l = gl.filter((g) => g.r === "L" && !g.ff).length, ti = gl.filter((g) => g.r === "T").length;
    const tr = TR.byId.get(tid);
    const det = h("details", { class: "card", open: i === 0 },
      h("summary", { style: { cursor: "pointer" } }, h("strong", null, tr ? tr.name : tid), h("span", { class: "muted" }, ` · ${fmt.date(gl[0].d)} · ${fmt.record(w, l, ti)}`)),
      h("div", { style: { "margin-top": "10px" } }, dataTable([
        { key: "rd", label: "Round", render: (g) => h("span", { class: "nowrap" }, g.rd || (g.st === "playoff" ? "Playoff" : "–")) },
        { key: "o", label: "Opponent", cls: "name", render: (g) => teamA(T, g.o) },
        { key: "score", label: "Score", num: true, render: (g) => (g.ff ? "forfeit" : g.s != null ? `${fmt.int(g.s)}–${fmt.int(g.os)}` : h("span", { class: "muted", title: "Score not published" }, "–")) },
        { key: "r", label: "Result", cls: "ctr", render: (g) => resultBadge(g.r) },
        { key: "p", label: "Win prob.", num: true, title: "Pre-game win probability from the ratings", render: (g) => fmt.pct(g.p) },
        { key: "note", label: "", render: (g) => (isUpset(g.r, g.p) ? upsetBadge() : g.st === "playoff" ? h("span", { class: "muted" }, "playoff") : "") },
      ], gl, { sortable: false, wrapClass: "bare", rowClass: (g) => (isUpset(g.r, g.p) ? "upset" : null) })));
    wrap.appendChild(det);
  });
  return section("Games", `${fmt.plural(games.length, "game")}, grouped by tournament`, wrap);
}

function h2hSection(d, T, selfId) {
  const agg = new Map();
  for (const g of d.games || []) {
    if (g.ff) continue;
    const a = agg.get(g.o) || { o: g.o, g: 0, w: 0, l: 0, t: 0, pf: 0, pa: 0, ns: 0, last: "" };
    a.g++;
    if (g.r === "W") a.w++; else if (g.r === "L") a.l++; else a.t++;
    if (g.s != null && g.os != null) { a.pf += g.s; a.pa += g.os; a.ns++; }
    if (g.d > a.last) a.last = g.d;
    agg.set(g.o, a);
  }
  const rows = [...agg.values()].sort((a, b) => b.g - a.g || b.last.localeCompare(a.last)).slice(0, 12);
  if (!rows.length) return section("Head-to-head", null, emptyState("No games recorded."));
  return section("Head-to-head", "Most frequent opponents", dataTable([
    { key: "o", label: "Opponent", cls: "name", sort: (r) => (T.byId.get(r.o) || {}).name || r.o, render: (r) => teamA(T, r.o) },
    { key: "g", label: "Games", num: true, sort: (r) => r.g, render: (r) => r.g },
    { key: "rec", label: "W–L–T", num: true, sort: (r) => (r.w + 0.5 * r.t) / r.g, render: (r) => fmt.record(r.w, r.l, r.t) },
    { key: "avg", label: "Avg score", num: true, sort: (r) => (r.ns ? (r.pf - r.pa) / r.ns : null), render: (r) => (r.ns ? `${Math.round(r.pf / r.ns)}–${Math.round(r.pa / r.ns)}` : "–") },
    { key: "last", label: "Last met", sort: (r) => r.last, render: (r) => h("span", { class: "nowrap" }, fmt.date(r.last)) },
    { key: "cmp", label: "", render: (r) => h("a", { href: `#/compare?type=teams&a=${encodeURIComponent(selfId)}&b=${encodeURIComponent(r.o)}` }, "Compare") },
  ], rows, { sort: { key: "g", dir: "desc" } }));
}
