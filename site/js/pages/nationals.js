import { h, fmt, dataTable, section, pageHead, notice, emptyState, extLink, tile, champBadge } from "../ui.js";
import { teams, schools, tournaments, nationals } from "../data.js";
import { teamA, schoolA, finishLabel, finishRank } from "../links.js";

const pick = (o, ...keys) => { for (const k of keys) if (o[k] != null && o[k] !== "") return o[k]; return null; };

export async function render(ctx) {
  const [T, S, TR, N] = await Promise.all([teams(), schools(), tournaments(), nationals()]);
  ctx.setTitle("Nationals");
  const root = h("div");
  root.appendChild(pageHead({
    title: "National Science Bowl",
    sub: h("span", null, "High-school champions of the DOE National Science Bowl since 1991, finishes by year, and the Nationals tournaments included in the ratings. Official results: ",
      extLink("https://science.osti.gov/wdts/nsb", "science.osti.gov")),
  }));

  // ---- champions
  // National Finals tournament pages, by year
  const nsbIds = (N.tournaments || []).filter((id) => TR.byId.has(id));
  const tourByYear = new Map(nsbIds.map((id) => [TR.byId.get(id).date.slice(0, 4), id]));
  const finalsLink = (y, text) => (tourByYear.has(String(y))
    ? h("a", { href: `#/tournament/${encodeURIComponent(tourByYear.get(String(y)))}` }, text ?? String(y)) : text ?? String(y ?? "–"));
  if (tourByYear.size) {
    const ys = [...tourByYear.keys()].sort().reverse();
    root.appendChild(h("nav", { class: "year-links", "aria-label": "National Finals tournament pages" },
      h("span", { class: "muted" }, "National Finals pages: "),
      ys.map((y, i) => [i ? h("span", { class: "muted", "aria-hidden": "true" }, " · ") : null, finalsLink(y, `${y}`)])));
  }
  const winners = (N.winners || []).filter((w) => w && typeof w === "object").slice().sort((a, b) => (b.year || 0) - (a.year || 0));
  const champName = (w) => String(pick(w, "school", "champion", "winner", "team") || "–");
  const champCell = (w) => (w.school_id && S.byId.has(w.school_id) ? schoolA(w.school_id, champName(w)) : h("span", null, champName(w)));
  const place = (w) => [pick(w, "city", "location"), pick(w, "state")].filter(Boolean).join(", ");

  if (winners.length) {
    const titles = new Map();
    for (const w of winners) {
      const k = w.school_id || champName(w);
      const e = titles.get(k) || { w, n: 0, years: [] };
      e.n++;
      e.years.push(w.year);
      titles.set(k, e);
    }
    const top = [...titles.values()].sort((a, b) => b.n - a.n || Math.max(...b.years) - Math.max(...a.years));
    const most = top.filter((x) => x.n === top[0].n);
    const latest = winners[0];
    const years = winners.map((w) => w.year).filter(Boolean);
    root.appendChild(h("div", { class: "tiles" },
      tile("Latest champion", h("span", { class: "tile-text" }, champCell(latest)), `${latest.year}${place(latest) ? ` · ${place(latest)}` : ""}`),
      tile("Most titles", h("span", { class: "tile-text" }, most.slice(0, 2).map((x, i) => [i ? ", " : "", champCell(x.w)])),
        `${fmt.plural(most[0].n, "title")}${most.length > 2 ? ` · ${most.length - 2} more schools tied` : ""}`),
      tile("Champions on record", fmt.int(winners.length), years.length ? `${Math.min(...years)}–${Math.max(...years)}` : null),
      tile("Different schools", fmt.int(titles.size), "have won the title")));
  }

  const hasRoster = winners.some((w) => (w.roster && w.roster.length) || w.coach);
  root.appendChild(section("Champions", winners.length ? `${winners.length} national champions${hasRoster ? ", with their team members and coach where recorded" : ""}` : null,
    winners.length ? dataTable([
      { key: "year", label: "Year", num: true, sort: (w) => w.year, defaultDir: "desc", title: "Linked years open that National Finals tournament page", render: (w) => finalsLink(w.year) },
      { key: "champ", label: "Champion", cls: "name wide", sort: (w) => champName(w),
        render: (w) => {
          const team = (w.roster || []).filter(Boolean);
          return h("div", null, champCell(w),
            place(w) ? h("span", { class: "sub show-sm" }, place(w)) : null,
            team.length || w.coach ? h("span", { class: "sub" }, team.join(", "), team.length && w.coach ? " · " : "", w.coach ? `Coach ${w.coach}` : "") : null);
        } },
      { key: "loc", label: "Location", hideSm: true, sort: (w) => place(w), render: (w) => place(w) || h("span", { class: "muted" }, "–") },
      { key: "titles", label: "Titles", hideSm: true, title: "The school's title count up to and including that year",
        render: (w) => { const e = titles2(w); return e > 1 ? h("span", { class: "nowrap" }, `${ordinal(e)} title`) : h("span", { class: "muted nowrap" }, "first title"); } },
    ], winners, { sort: { key: "year", dir: "desc" }, caption: "National Science Bowl high-school champions", captionHidden: true, tableClass: "compact" })
      : notice("The list of national champions is still being compiled. Check back after the next data update.")));
  function titles2(w) {
    const k = w.school_id || champName(w);
    return winners.filter((x) => (x.school_id || champName(x)) === k && (x.year || 0) <= (w.year || 0)).length;
  }

  // ---- finishes by year
  const years = Object.keys(N.finishes || {}).sort().reverse();
  const finWrap = h("div", { class: "stack" });
  let first = true;
  for (const y of years) {
    const items = (N.finishes[y] || []).slice().sort((a, b) => finishRank(a.finish) - finishRank(b.finish)
      || String(a.division || "").localeCompare(String(b.division || "")) || (a.division_place || 99) - (b.division_place || 99)
      || String(a.team || "").localeCompare(String(b.team || "")));
    if (!items.length) continue;
    const champ = items.find((x) => finishRank(x.finish) === 1);
    const tid = tourByYear.get(y);
    const elim = items.filter((x) => finishRank(x.finish) < 999);
    const rr = items.filter((x) => finishRank(x.finish) >= 999);
    const teamCol = { key: "team", label: "Team", cls: "name", render: (x) => h("div", null,
      x.tm && T.byId.has(x.tm) ? teamA(T, x.tm) : h("span", null, String(x.team ?? "–")), schoolSub(x)) };
    const body = h("div", { class: "year-body" });
    if (tid) body.appendChild(h("p", { class: "muted year-note" }, h("a", { href: `#/tournament/${encodeURIComponent(tid)}` }, `${y} National Finals: all games`)));
    if (elim.length) {
      if (rr.length) body.appendChild(h("h3", { class: "year-h" }, `Elimination rounds (${elim.length} teams)`));
      body.appendChild(dataTable([
        { key: "finish", label: "Finish", render: (x) => h("span", { class: "nowrap" }, finishLabel(x.finish)) },
        teamCol,
        { key: "note", label: "", render: (x) => (finishRank(x.finish) === 1 ? champBadge() : "") },
      ], elim, { sortable: false, wrapClass: "bare", caption: `${y} National Finals: elimination-round finishes`, captionHidden: true }));
    }
    if (rr.length) {
      const hasDiv = rr.some((x) => x.division);
      if (elim.length) body.appendChild(h("h3", { class: "year-h" }, `Round robin only (${rr.length} teams)`));
      body.appendChild(dataTable([
        hasDiv ? { key: "div", label: "Division", render: (x) => (x.division ? String(x.division) : h("span", { class: "muted" }, "–")) } : null,
        hasDiv ? { key: "place", label: "Place", num: true, title: "Place in the round-robin division", render: (x) => (x.division_place ? ordinal(x.division_place) : "–") } : null,
        teamCol,
        { key: "rec", label: "Record", num: true, title: "Round-robin record", render: (x) => (x.record ? String(x.record).replace(/-/g, "–") : h("span", { class: "muted" }, "–")) },
      ].filter(Boolean), rr, { sortable: false, wrapClass: "bare", caption: `${y} National Finals: teams eliminated in the round robin`, captionHidden: true }));
    }
    finWrap.appendChild(h("details", { class: "card", open: first },
      h("summary", { class: "year-summary" }, h("strong", null, y),
        h("span", { class: "muted" }, ` · ${fmt.plural(items.length, "team")}${champ ? ` · champion ${champ.tm && T.byId.has(champ.tm) ? T.byId.get(champ.tm).name : champ.team}` : ""}`)),
      body));
    first = false;
  }
  function schoolSub(x) {
    const sc = x.school_id && S.byId.get(x.school_id);
    const tm = x.tm && T.byId.get(x.tm);
    const bits = [];
    // the team name is usually the school's short name; show the school only when it adds information
    if (sc && (!tm || !tm.name.startsWith(sc.short || sc.name))) bits.push(schoolA(sc.id, sc.name));
    const st = x.state || (sc && sc.state);
    if (st) bits.push(st);
    return bits.length ? h("span", { class: "muted" }, bits.map((b) => [" · ", b])) : null;
  }
  root.appendChild(section("Finishes by year", "Placements at the National Finals; teams eliminated in the same round share a range",
    years.length ? finWrap : emptyState("No per-year Nationals finishes are on record yet.")));

  // ---- NSB tournaments in the data
  const nsbT = nsbIds.length ? nsbIds.map((id) => TR.byId.get(id)) : TR.list.filter((t) => t.kind === "nationals");
  const anyScores = nsbT.some((t) => t.coverage && t.coverage.scores);
  root.appendChild(section("Nationals tournaments in the ratings",
    anyScores ? "Nationals games feed the team ratings" : "Nationals results feed team ratings as wins and losses only (no scores or player stats are published)",
    nsbT.length ? dataTable([
      { key: "date", label: "Date", sort: (t) => t.date, render: (t) => h("span", { class: "nowrap" }, fmt.date(t.date)) },
      { key: "name", label: "Tournament", cls: "name", sort: (t) => t.date, render: (t) => h("a", { href: `#/tournament/${encodeURIComponent(t.id)}` }, `${t.date.slice(0, 4)} ${t.name}`) },
      { key: "n", label: "Teams", num: true, sort: (t) => t.n_teams, render: (t) => (t.no_data ? "–" : fmt.int(t.n_teams)) },
      { key: "g", label: "Games", num: true, sort: (t) => t.n_games, render: (t) => (t.no_data ? "–" : fmt.int(t.n_games)) },
      { key: "champ", label: "Champion", render: (t) => (t.champion ? teamA(T, t.champion) : h("span", { class: "muted" }, "–")) },
    ], nsbT, { sort: { key: "date", dir: "desc" } }) : emptyState("No National Science Bowl tournaments have been parsed yet.")));
  return root;
}

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
