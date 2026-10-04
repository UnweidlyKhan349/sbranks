import { h, fmt, dataTable, section, pageHead, notice, emptyState, extLink } from "../ui.js";
import { teams, schools, tournaments, nationals } from "../data.js";
import { teamA, schoolA, tournamentA } from "../links.js";

const pick = (o, ...keys) => { for (const k of keys) if (o[k] != null && o[k] !== "") return o[k]; return null; };

function finishRank(f) {
  const s = String(f ?? "").toLowerCase();
  if (/^(1|1st|first|champion|winner)\b/.test(s)) return 1;
  if (/^(2|2nd|second|runner)/.test(s)) return 2;
  if (/^(3|3rd|third)/.test(s)) return 3;
  const n = parseInt(s.replace(/[^0-9]/g, ""), 10);
  return Number.isFinite(n) ? n : 999;
}

export async function render(ctx) {
  const [T, S, TR, N] = await Promise.all([teams(), schools(), tournaments(), nationals()]);
  ctx.setTitle("Nationals");
  const root = h("div");
  root.appendChild(pageHead({
    title: "National Science Bowl",
    sub: h("span", null, "High-school champions of the DOE National Science Bowl since 1991, finishes by year, and the Nationals tournaments included in the ratings. Official results: ",
      extLink("https://science.osti.gov/wdts/nsb", "science.osti.gov"), "."),
  }));

  // ---- champions
  const winners = (N.winners || []).filter((w) => w && typeof w === "object").slice().sort((a, b) => (b.year || 0) - (a.year || 0));
  const hasCity = winners.some((w) => pick(w, "city", "location"));
  const hasState = winners.some((w) => pick(w, "state"));
  const hasRunner = winners.some((w) => pick(w, "runner_up", "second", "runnerup"));
  const hasThird = winners.some((w) => pick(w, "third"));
  const findSchool = (w) => w.school_id || null;
  root.appendChild(section("Champions", winners.length ? `${winners.length} national champions` : null,
    winners.length ? dataTable([
      { key: "year", label: "Year", sort: (w) => w.year, defaultDir: "desc", render: (w) => String(w.year ?? "–") },
      { key: "champ", label: "Champion", cls: "name", sort: (w) => String(pick(w, "champion", "winner", "school", "team") || ""),
        render: (w) => { const name = pick(w, "champion", "winner", "school", "team") || "–"; const sid = findSchool(w); return sid && S.byId.has(sid) ? schoolA(sid, String(name)) : String(name); } },
      hasCity ? { key: "city", label: "City", render: (w) => String(pick(w, "city", "location") || "–") } : null,
      hasState ? { key: "state", label: "State", sort: (w) => String(w.state || ""), render: (w) => String(w.state || "–") } : null,
      hasRunner ? { key: "ru", label: "Runner-up", render: (w) => String(pick(w, "runner_up", "second", "runnerup") || "–") } : null,
      hasThird ? { key: "third", label: "Third", render: (w) => String(pick(w, "third") || "–") } : null,
    ].filter(Boolean), winners, { sort: { key: "year", dir: "desc" }, caption: "National Science Bowl high-school champions", captionHidden: true })
      : notice("The list of national champions is still being compiled. Check back after the next data update.")));

  // ---- finishes by year
  const years = Object.keys(N.finishes || {}).sort().reverse();
  const finWrap = h("div", { class: "stack" });
  years.forEach((y, i) => {
    const items = (N.finishes[y] || []).slice().sort((a, b) => finishRank(a.finish) - finishRank(b.finish));
    if (!items.length) return;
    finWrap.appendChild(h("details", { class: "card", open: i === 0 },
      h("summary", { style: { cursor: "pointer" } }, h("strong", null, y), h("span", { class: "muted" }, ` · ${fmt.plural(items.length, "team")}`)),
      h("div", { style: { "margin-top": "8px" } }, dataTable([
        { key: "finish", label: "Finish", render: (x) => String(x.finish ?? "–") },
        { key: "team", label: "Team", cls: "name", render: (x) => (x.tm && T.byId.has(x.tm) ? teamA(T, x.tm) : String(x.team ?? "–")) },
        { key: "school", label: "School", render: (x) => (x.school_id && S.byId.has(x.school_id) ? schoolA(x.school_id, S.byId.get(x.school_id).name) : x.school ? String(x.school) : h("span", { class: "muted" }, "–")) },
        { key: "state", label: "State", render: (x) => String(x.state || (x.school_id && S.byId.get(x.school_id)?.state) || "–") },
      ], items, { sortable: false, wrapClass: "bare" }))));
  });
  root.appendChild(section("Finishes by year", null, years.length ? finWrap : emptyState("No per-year Nationals finishes are on record yet.")));

  // ---- NSB tournaments in the data
  const ids = (N.tournaments || []).filter((id) => TR.byId.has(id));
  const nsbT = ids.length ? ids.map((id) => TR.byId.get(id)) : TR.list.filter((t) => t.kind === "nationals");
  root.appendChild(section("Nationals tournaments in the ratings", "Nationals results feed team ratings as wins and losses only (no scores or player stats are published)",
    nsbT.length ? dataTable([
      { key: "date", label: "Date", sort: (t) => t.date, render: (t) => h("span", { class: "nowrap" }, fmt.date(t.date)) },
      { key: "name", label: "Tournament", cls: "name", sort: (t) => t.name, render: (t) => tournamentA(TR, t.id) },
      { key: "n", label: "Teams", num: true, sort: (t) => t.n_teams, render: (t) => (t.no_data ? "–" : fmt.int(t.n_teams)) },
      { key: "g", label: "Games", num: true, sort: (t) => t.n_games, render: (t) => (t.no_data ? "–" : fmt.int(t.n_games)) },
      { key: "champ", label: "Champion", render: (t) => (t.champion ? teamA(T, t.champion) : h("span", { class: "muted" }, "–")) },
    ], nsbT, { sort: { key: "date", dir: "desc" } }) : emptyState("No National Science Bowl tournaments have been parsed yet.")));
  return root;
}
