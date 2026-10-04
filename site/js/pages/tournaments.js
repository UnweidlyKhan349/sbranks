import { h, clear, fmt, dataTable, pageHead, setQuery, boolParam, debounce, coverageBadge, badge, extLink, emptyState, subjLabel } from "../ui.js";
import { teams, players, tournaments } from "../data.js";
import { tournamentA, kindLabel, levelBadge, entrantCount, championA, sourceRoleLabel } from "../links.js";

export function sourceLinks(t) {
  const label = (s) => sourceRoleLabel(s.role, true);
  const seen = new Map();
  return h("span", { class: "source-links" }, (t.sources || []).map((s) => {
    let text = label(s);
    const n = (seen.get(text) || 0) + 1;
    seen.set(text, n);
    if (n > 1) text += ` ${n}`;
    return h("span", { class: "nowrap" }, extLink(s.url, text));
  }));
}

/** Compact badges for the data a tournament has (only what is available). */
export function coverageBadges(t, { compact = false } = {}) {
  const c = t.coverage || {};
  const out = [];
  const o = { bare: compact };
  if (c.scores) out.push(coverageBadge(true, "Scores", o));
  else if (c.games) out.push(coverageBadge(true, "Win/loss only", o));
  if (c.player_stats) out.push(coverageBadge(true, compact ? "Players" : "Player stats", o));
  if (c.player_subject_stats || c.team_game_subjects) out.push(coverageBadge(true, compact ? "Subjects" : "Subject stats", o));
  if (!out.length) return h("span", { class: "muted" }, "–");
  return h("span", { class: ["badges", compact ? "nowrap-badges" : null] }, out);
}

export async function render(ctx) {
  const [T, P, TR] = await Promise.all([teams(), players(), tournaments()]);
  ctx.setTitle("Tournaments");
  const q = ctx.query;
  const st = { q: q.get("q") || "", season: q.get("season") || "", kind: q.get("kind") || "", stats: boolParam(q, "stats", false), data: boolParam(q, "data", false) };
  const seasons = [...new Set(TR.list.map((t) => t.season))].sort().reverse();
  const kinds = [...new Set(TR.list.map((t) => t.kind).filter(Boolean))].sort();
  // unknown values from the URL fall back to "all"
  if (!seasons.includes(st.season)) st.season = "";
  if (!kinds.includes(st.kind)) st.kind = "";
  const root = h("div");
  const nData = TR.list.filter((t) => !t.no_data).length;
  root.appendChild(pageHead({
    title: "Tournaments",
    sub: `${fmt.int(TR.list.length)} high-school tournaments listed, ${fmt.int(nData)} with results so far. Field strength is the mean pre-tournament rating of the field's top 8 teams.`,
  }));
  const search = h("input", { class: "input", type: "search", placeholder: "Search tournaments", "aria-label": "Search tournaments", value: st.q });
  search.addEventListener("input", debounce(() => { st.q = search.value; update(); }, 120));
  const seasonSel = h("select", { class: "select", "aria-label": "Season" }, h("option", { value: "" }, "All seasons"), seasons.map((x) => h("option", { value: x, selected: x === st.season }, x)));
  seasonSel.addEventListener("change", () => { st.season = seasonSel.value; update(); });
  const kindSel = h("select", { class: "select", "aria-label": "Kind" }, h("option", { value: "" }, "All kinds"), kinds.map((x) => h("option", { value: x, selected: x === st.kind }, kindLabel(x))));
  kindSel.addEventListener("change", () => { st.kind = kindSel.value; update(); });
  const dataBox = h("input", { type: "checkbox", checked: st.data });
  dataBox.addEventListener("change", () => { st.data = dataBox.checked; update(); });
  const statsBox = h("input", { type: "checkbox", checked: st.stats });
  statsBox.addEventListener("change", () => { st.stats = statsBox.checked; update(); });
  root.appendChild(h("div", { class: "filters", role: "search", "aria-label": "Filter tournaments" }, search, seasonSel, kindSel,
    h("label", { class: "check" }, dataBox, "Has results"), h("label", { class: "check" }, statsBox, "Has player stats")));
  const note = h("div", { class: "result-note", "aria-live": "polite" });
  const host = h("div");
  root.append(note, host);

  function update() {
    setQuery("/tournaments", { q: st.q || null, season: st.season || null, kind: st.kind || null, stats: st.stats ? "1" : null, data: st.data ? "1" : null });
    const terms = st.q.toLowerCase().split(/\s+/).filter(Boolean);
    const rows = TR.list.filter((t) => {
      if (st.season && t.season !== st.season) return false;
      if (st.kind && t.kind !== st.kind) return false;
      if (st.data && t.no_data) return false;
      if (st.stats && !(t.coverage && t.coverage.player_stats)) return false;
      if (terms.length) {
        const k = `${t.name} ${t.location || ""} ${t.season}`.toLowerCase();
        if (!terms.every((x) => k.includes(x))) return false;
      }
      return true;
    });
    clear(note).append(`${fmt.plural(rows.length, "tournament")}`);
    clear(host);
    if (!rows.length) { host.appendChild(emptyState("No tournaments match these filters.")); return; }
    const bySeason = new Map();
    for (const t of rows) {
      if (!bySeason.has(t.season)) bySeason.set(t.season, []);
      bySeason.get(t.season).push(t);
    }
    for (const [season, list] of [...bySeason.entries()].sort((a, b) => b[0].localeCompare(a[0]))) {
      const withRes = list.filter((t) => !t.no_data).length;
      host.appendChild(h("h2", { class: "season-head" }, `${season} season`, h("span", { class: "muted" }, `${fmt.plural(list.length, "tournament")} · ${withRes} with results`)));
      host.appendChild(dataTable([
        { key: "date", label: "Date", sort: (t) => t.date, defaultDir: "desc", render: (t) => h("span", { class: "nowrap" }, fmt.range(t.date, t.end)) },
        { key: "name", label: "Tournament", cls: "name wide", sort: (t) => t.name,
          render: (t) => h("div", null, tournamentA(TR, t.id), " ", t.kind && t.kind !== "invitational" ? badge(kindLabel(t.kind)) : null, " ", levelBadge(t.level), t.individual ? badge("Individual") : null, " ", t.subject_only ? badge(`${subjLabel(String(t.subject_only))} only`) : null,
            t.no_data ? h("span", { class: "sub" }, "No results available") : null) },
        { key: "loc", label: "Location", sort: (t) => (t.online ? "Online" : t.location || ""), render: (t) => (t.online ? "Online" : t.location || h("span", { class: "muted" }, "–")) },
        { key: "n_teams", label: "Teams", num: true, title: "Teams (competitors for individual events)", sort: (t) => (t.no_data ? null : entrantCount(t)),
          render: (t) => (t.no_data ? "–" : t.individual ? h("span", { title: `Individual event: ${fmt.plural(entrantCount(t), "competitor")}` }, fmt.int(entrantCount(t)), h("span", { class: "sub" }, "competitors")) : fmt.int(t.n_teams)) },
        { key: "n_games", label: "Games", num: true, sort: (t) => (t.no_data ? null : t.n_games), render: (t) => (t.no_data ? "–" : fmt.int(t.n_games)) },
        { hideSm: true, key: "strength", label: "Field", num: true, title: "Field strength: mean pre-tournament rating of the top 8 teams", sort: (t) => t.strength, render: (t) => fmt.r(t.strength) },
        { key: "champ", label: "Champion", sort: (t) => (t.champion ? (T.byId.get(t.champion) || {}).name : t.champion_name || null), render: (t) => championA(T, P, t) },
        { hideSm: true, key: "cov", label: "Data", render: (t) => (t.no_data ? badge("No results", "off") : coverageBadges(t, { compact: true })) },
        { hideSm: true, key: "src", label: "Sources", render: (t) => sourceLinks(t) },
      ], list, { sort: { key: "date", dir: "desc" }, rowClass: (t) => (t.no_data ? "dim" : null), caption: `${season} tournaments`, captionHidden: true, tableClass: "compact" }));
    }
  }
  update();
  return root;
}
