import { h, clear, fmt, delta, dataTable, tile, section, pageHead, notFound, SUBJECTS, subjColor, subjTag, parseDate, href, emptyState } from "../ui.js";
import { lineChart, refBars } from "../charts.js";
import { meta, teams, players, tournaments, playerDetail } from "../data.js";
import { teamA, schoolA, tournamentA } from "../links.js";

export async function render(ctx) {
  const id = ctx.param;
  const [m, T, P, TR] = await Promise.all([meta(), teams(), players(), tournaments()]);
  const p = P.byId.get(id);
  if (!p) { ctx.setTitle("Player not found"); return notFound("Player", id); }
  const d = (await playerDetail(id)) || { history: {}, stats: [], teammates: [] };
  ctx.setTitle(p.name);
  const nRanked = P.list.filter((x) => x.rank != null).length;
  const minN = m.thresholds.player_min_tuh;
  const root = h("div");
  // other spellings, ignoring case-only differences
  const seenNames = new Set([p.name.toLowerCase()]);
  const aliases = (p.aliases || []).filter((a) => { const k = String(a).toLowerCase(); if (seenNames.has(k)) return false; seenNames.add(k); return true; });

  root.appendChild(pageHead({
    eyebrow: [h("a", { href: "#/players" }, "Players"),
      ...(p.school ? [h("span", { "aria-hidden": "true" }, "/"), schoolA(p.school, p.school_name), p.state ? h("span", { class: "muted" }, p.state) : null]
        : p.school_name ? [h("span", { "aria-hidden": "true" }, "/"), h("span", null, p.school_name)] : [])],
    title: p.name,
    sub: [
      p.teams.length ? h("span", null, "Teams: ", p.teams.map((tid, i) => [i ? ", " : "", teamA(T, tid)])) : null,
      aliases.length ? h("span", { class: "muted" }, `Also listed as ${aliases.join(", ")}`) : null,
      h("a", { href: `#/compare?type=players&a=${encodeURIComponent(p.id)}` }, "Compare with another player"),
    ],
  }));

  const provReason = p.r == null ? "No overall rating" : p.rank == null ? "Provisional or inactive" : `of ${fmt.int(nRanked)} ranked players`;
  // why there is no overall rating: only single-subject events, or only per-subject stats were published
  const onlySubjectEvents = (d.stats || []).length > 0 && d.stats.every((st) => (TR.byId.get(st.t) || {}).subject_only);
  const unratedWhy = onlySubjectEvents ? "Only single-subject events" : "Only per-subject stats published";
  root.appendChild(h("div", { class: "tiles" },
    tile("Rating", p.r != null ? [fmt.r(p.r), h("span", { class: "pm" }, fmt.pm(p.se))] : "Unrated", p.r != null ? "Elo-scaled ± standard error" : unratedWhy),
    tile("Rank", p.rank != null ? `#${p.rank}` : "Unranked", provReason),
    tile("Best subject", p.best ? subjTag(p.best) : "–", p.best && p.subj[p.best] ? `${fmt.r(p.subj[p.best].r)} ±${Math.round(p.subj[p.best].se)}` : null),
    tile("Points per game", fmt.num(p.ppg), p.ptuh != null ? `${fmt.num(p.ptuh, 2)} per tossup heard` : "tossups heard not published"),
    tile("Tournaments", fmt.int(p.n_t), p.gp ? `${fmt.int(p.gp)} games` : null),
    tile("Peak rating", fmt.r(p.peak), p.first ? (p.first === p.last ? `played ${fmt.dateShort(p.first)}` : `active ${fmt.dateShort(p.first)} – ${fmt.dateShort(p.last)}`) : null)));

  // ---- subject profile
  const cats = SUBJECTS.map((x) => {
    const v = p.subj[x.key];
    return { key: x.key, label: x.label, sub: v ? (v.rank ? `rank ${v.rank}` : fmt.plural(v.n, "tossup")) : null };
  });
  const vals = {};
  for (const x of SUBJECTS) {
    const v = p.subj[x.key];
    if (v) vals[x.key] = { value: v.r, lo: v.r - v.se, hi: v.r + v.se, pm: v.se, provisional: v.n < (minN[x.key] || 25) };
  }
  const profile = refBars(cats, [{ label: "Subject rating", color: "var(--s1)", values: vals }], {
    label: `Subject ratings for ${p.name}`,
    tip: (c) => {
      const v = p.subj[c.key];
      return v ? { title: c.label, rows: [
        { color: "var(--s1)", kind: "rect", value: `${fmt.r(v.r)} ±${Math.round(v.se)}`, label: v.n < (minN[c.key] || 25) ? "provisional" : "rating" },
        { value: v.rank ? `#${v.rank}` : "unranked", label: "rank" },
        { value: fmt.int(v.pts), label: "tossup points" },
        { value: fmt.int(v.n), label: "effective tossups heard" }] } : { title: c.label, rows: [{ value: "no data" }] };
    },
    table: {
      columns: [
        { key: "s", label: "Subject", render: (r) => r.label },
        { key: "r", label: "Rating", num: true, render: (r) => (r.v ? fmt.r(r.v.r) : "–") },
        { key: "se", label: "±", num: true, render: (r) => (r.v ? Math.round(r.v.se) : "–") },
        { key: "rank", label: "Rank", num: true, render: (r) => (r.v && r.v.rank ? r.v.rank : "–") },
        { key: "pts", label: "Points", num: true, render: (r) => (r.v ? fmt.int(r.v.pts) : "–") },
        { key: "n", label: "Tossups", num: true, render: (r) => (r.v ? r.v.n : "–") },
      ], rows: SUBJECTS.map((x) => ({ label: x.label, v: p.subj[x.key] })),
    },
  });

  // ---- rating history (overall + optional subject lines)
  const histHost = h("div");
  let showSubj = !d.history.overall || !d.history.overall.length;
  const toggle = h("input", { type: "checkbox", checked: showSubj });
  toggle.addEventListener("change", () => { showSubj = toggle.checked; drawHistory(); });
  const tByDate = new Map();
  for (const st of d.stats || []) if (!tByDate.has(st.d)) tByDate.set(st.d, st.t);
  function drawHistory() {
    const series = [];
    // history snapshots are taken after each of the player's tournaments; the model is refitted as
    // later events arrive, so the current rating is appended as a final point when it differs
    const withCurrent = (hs, cur) => {
      const pts = (hs || []).map((q) => ({ x: parseDate(q.d), y: q.r, lo: q.r - q.se, hi: q.r + q.se, d: q.d }));
      if (cur && cur.r != null && pts.length) {
        const last = pts[pts.length - 1];
        if (last.d < m.snapshot && Math.abs(last.y - cur.r) >= 0.5) pts.push({ x: parseDate(m.snapshot), y: cur.r, lo: cur.r - cur.se, hi: cur.r + cur.se, d: m.snapshot, current: true });
      }
      return pts;
    };
    const ov = withCurrent(d.history.overall, p.r != null ? { r: p.r, se: p.se } : null);
    if (ov.length) series.push({ id: "overall", label: "Overall", color: showSubj ? "var(--ink)" : "var(--s1)", points: ov, band: !showSubj });
    if (showSubj) {
      for (const x of SUBJECTS) {
        const hs = d.history[x.key];
        if (hs && hs.length) series.push({ id: x.key, label: x.label, color: subjColor(x.key), points: withCurrent(hs, p.subj[x.key]) });
      }
    }
    const allDates = [...new Set(series.flatMap((sr) => sr.points.map((q) => q.d)))].sort().reverse();
    const chart = lineChart(series, {
      label: `Rating history for ${p.name}`, refY: 1500, refLabel: "1500 = average", height: 260, legend: showSubj && series.length > 0,
      empty: "No rating history yet.",
      tip: (x, hits) => {
        const iso = new Date(x).toISOString().slice(0, 10);
        const tid = tByDate.get(iso);
        return {
          title: tid ? (TR.byId.get(tid) || {}).name || tid : iso === m.snapshot ? "Current rating" : fmt.date(iso), sub: fmt.date(iso),
          rows: hits.map((hh) => ({ color: hh.series.color, value: `${fmt.r(hh.point.y)}${hh.series.id === "overall" && !showSubj ? " ±" + Math.round(hh.point.hi - hh.point.y) : ""}`, label: hh.series.label + (hh.exact ? "" : " (earlier)") })),
        };
      },
      table: {
        columns: [
          { key: "d", label: "Date", render: (r) => fmt.date(r) },
          ...series.map((sr) => ({ key: sr.id, label: sr.label, num: true, render: (r) => { const q = sr.points.find((pp) => pp.d === r); return q ? fmt.r(q.y) : "–"; } })),
        ], rows: allDates,
      },
    });
    clear(histHost).appendChild(chart);
  }
  drawHistory();
  root.appendChild(h("div", { class: "grid-2 section" },
    h("div", { class: "card" }, h("h2", { class: "chart-title" }, "Subject profile"), h("p", { class: "chart-sub" }, "Elo-scaled subject ratings with ± one standard error; faded bars are provisional"), profile),
    h("div", { class: "card" }, h("h2", { class: "chart-title" }, "Rating history"),
      h("div", { class: "chart-controls" }, h("p", { class: "chart-sub", style: { margin: 0 } }, "After each tournament, plus the current rating"),
        h("label", { class: "check" }, toggle, "Show subject ratings")), histHost)));

  // ---- per-tournament stats
  const stats = (d.stats || []).slice().reverse();
  const sv = (row, subj, k) => (row.s[subj] ? row.s[subj][k] : null);
  // overall rating after each tournament (snapshots are keyed by the tournament's end date)
  const ovHist = (d.history && d.history.overall) || [];
  const ovIdx = new Map(ovHist.map((x, i) => [x.d, i]));
  const change = (r) => { const i = ovIdx.get(r.d); return i == null ? null : { post: ovHist[i].r, dr: i > 0 ? ovHist[i].r - ovHist[i - 1].r : null }; };
  const columns = [
    { key: "d", label: "Date", sort: (r) => r.d, defaultDir: "desc", render: (r) => h("span", { class: "nowrap" }, fmt.date(r.d)) },
    { key: "t", label: "Tournament", cls: "name", sort: (r) => (TR.byId.get(r.t) || {}).name || r.t, render: (r) => h("div", null, tournamentA(TR, r.t), r.scope === "rr" ? h("span", { class: "sub" }, "round robin only") : r.scope === "playoff" ? h("span", { class: "sub" }, "playoffs only") : null) },
    { key: "tm", label: "Team", cls: "team", sort: (r) => (T.byId.get(r.tm) || {}).name || r.tm, render: (r) => teamA(T, r.tm) },
    { key: "gp", label: "GP", num: true, sort: (r) => sv(r, "overall", "gp"), render: (r) => { const g = sv(r, "overall", "gp"); return g == null ? "–" : (r.s.overall.gp_est ? "≈" : "") + fmt.num(g, 0); } },
    { key: "tuh", label: "TUH", num: true, title: "Tossups heard", sort: (r) => sv(r, "overall", "tuh"), render: (r) => fmt.int(sv(r, "overall", "tuh")) },
    { key: "c", label: "4s", num: true, title: "Correct tossups", sort: (r) => sv(r, "overall", "c"), render: (r) => fmt.int(sv(r, "overall", "c")) },
    { key: "n", label: "Negs", num: true, title: "Interrupt penalties", sort: (r) => sv(r, "overall", "n"), render: (r) => fmt.int(sv(r, "overall", "n")) },
    { key: "pts", label: "Pts", num: true, title: "Tossup points", sort: (r) => sv(r, "overall", "pts"), render: (r) => fmt.int(sv(r, "overall", "pts")) },
    { key: "ppg", label: "PPG", num: true, sort: (r) => ppg(r), render: (r) => fmt.num(ppg(r)) },
    { key: "ptuh", label: "P/TUH", num: true, sort: (r) => ptuh(r), render: (r) => fmt.num(ptuh(r), 2) },
    ovHist.length ? { key: "post", label: "Rating", num: true, title: "Overall rating after this tournament", sort: (r) => change(r)?.post, render: (r) => fmt.r(change(r)?.post) } : null,
    ovHist.length ? { key: "dr", label: "Change", num: true, title: "Change in overall rating since the previous tournament", sort: (r) => change(r)?.dr,
      render: (r) => { const c = change(r); return c && c.dr == null ? h("span", { class: "muted", title: "First rated tournament" }, "new") : delta(c ? c.dr : null); } } : null,
    ...SUBJECTS.map((x) => ({
      key: x.key, num: true, title: `${x.label} tossup points`, sort: (r) => sv(r, x.key, "pts"),
      label: h("span", { class: "subj-label" }, h("span", { class: "swatch", style: { background: subjColor(x.key) }, "aria-hidden": "true" }), x.short),
      render: (r) => fmt.int(sv(r, x.key, "pts")),
    })),
  ].filter(Boolean);
  function ppg(r) {
    const o = r.s.overall;
    if (!o) return null;
    if (o.ppg != null) return o.ppg;
    return o.pts != null && o.gp ? o.pts / o.gp : null;
  }
  function ptuh(r) {
    const o = r.s.overall;
    return o && o.tuh && o.pts != null ? o.pts / o.tuh : null;
  }
  root.appendChild(section("Tournament stats", "Tossup statistics as published; ≈ marks games played inferred from the team's game count",
    dataTable(columns, stats, { sort: { key: "d", dir: "desc" }, empty: "No statistics.", tableClass: "compact" })));

  // ---- teammates
  const mates = (d.teammates || []).map((x) => P.byId.get(x)).filter(Boolean);
  root.appendChild(section("Teammates", "Most frequent teammates",
    mates.length ? h("div", { class: "chips" }, mates.map((q) => h("a", { class: "chip", href: href.player(q.id) }, q.name, q.r != null ? h("span", { class: "muted" }, fmt.r(q.r)) : null)))
      : emptyState("No teammates recorded.")));
  return root;
}
