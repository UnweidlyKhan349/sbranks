import { h, fmt, dataTable, ratingCell, tile, section, pageHead, notFound, badge, subjTag, subjLabel, emptyState } from "../ui.js";
import { sparkline } from "../charts.js";
import { teams, players, schools } from "../data.js";
import { teamA, playerA } from "../links.js";

export async function render(ctx) {
  const id = ctx.param;
  const [T, P, S] = await Promise.all([teams(), players(), schools()]);
  const sc = S.byId.get(id);
  if (!sc) { ctx.setTitle("School not found"); return notFound("School", id); }
  ctx.setTitle(sc.name);
  const entries = sc.teams.map((tid) => T.byId.get(tid)).filter(Boolean)
    .sort((a, b) => (b.r ?? -1) - (a.r ?? -1) || a.name.localeCompare(b.name));
  const roster = P.list.filter((p) => p.school === id);
  const best = entries.find((t) => t.r != null);
  const seasons = [...new Set(entries.flatMap((t) => t.seasons))].sort();
  const root = h("div");
  root.appendChild(pageHead({
    eyebrow: [h("a", { href: "#/teams" }, "Teams"), h("span", { "aria-hidden": "true" }, "/"), "School", sc.composite ? badge("Pickup / composite") : null],
    title: sc.name,
    sub: [[sc.city, sc.state].filter(Boolean).join(", ") || h("span", { class: "muted" }, "Location not recorded"),
      seasons.length ? `Seasons ${seasons[0]}${seasons.length > 1 ? " – " + seasons[seasons.length - 1] : ""}` : null],
  }));
  root.appendChild(h("div", { class: "tiles" },
    tile("Best team rating", best ? [fmt.r(best.r), h("span", { class: "pm" }, fmt.pm(best.rd))] : "–", best ? best.name : null),
    tile("Team entries", fmt.int(entries.length), entries.map((t) => t.letter || "").filter(Boolean).join(" · ") || null),
    tile("Players", fmt.int(roster.length), "with published stats"),
    tile("Nationals", sc.nsb && sc.nsb.length ? fmt.int(sc.nsb.length) : "–", sc.nsb && sc.nsb.length ? "appearances on record" : "no finishes on record")));

  root.appendChild(section("Teams", "Every A/B/C… entry from this school", dataTable([
    { key: "name", label: "Team", cls: "name", sort: (t) => t.name, render: (t) => teamA(T, t.id) },
    { key: "r", label: "Rating", num: true, sort: (t) => t.r, render: (t) => ratingCell(t.r, t.rd, { provisional: t.r != null && t.rank == null }) },
    { key: "rank", label: "Rank", num: true, sort: (t) => t.rank, defaultDir: "asc", render: (t) => t.rank ?? "–" },
    { key: "rec", label: "W–L–T", num: true, sort: (t) => (t.g ? (t.w + 0.5 * t.t) / t.g : null), render: (t) => (t.g ? fmt.record(t.w, t.l, t.t) : "–") },
    { key: "n_t", label: "Tournaments", num: true, sort: (t) => t.n_t, render: (t) => t.n_t },
    { key: "seasons", label: "Seasons", render: (t) => t.seasons.join(", ") },
    { key: "last", label: "Last played", sort: (t) => t.last, render: (t) => h("span", { class: "nowrap" }, fmt.date(t.last)) },
    { key: "trend", label: "Trend", hideSm: true, render: (t) => sparkline(t.trend) },
  ], entries, { sort: { key: "r", dir: "desc" }, empty: "No team entries." })));

  const nsb = (sc.nsb || []).slice().sort((a, b) => b.year - a.year);
  root.appendChild(section("NSB Nationals", h("a", { href: "#/nationals" }, "Nationals history"),
    nsb.length ? dataTable([
      { key: "year", label: "Year", render: (x) => String(x.year) },
      { key: "finish", label: "Finish", render: (x) => String(x.finish ?? "–") },
    ], nsb, { sortable: false }) : emptyState("No National Science Bowl finishes on record for this school.")));

  root.appendChild(section("Players", `${fmt.plural(roster.length, "player")} who represented this school`, dataTable([
    { key: "name", label: "Player", cls: "name", sort: (p) => p.name, render: (p) => playerA(P, p.id) },
    { key: "r", label: "Rating", num: true, sort: (p) => p.r, render: (p) => ratingCell(p.r, p.se, { provisional: p.r != null && p.rank == null }) },
    { key: "ppg", label: "PPG", num: true, sort: (p) => p.ppg, render: (p) => fmt.num(p.ppg) },
    { key: "best", label: "Best subject", sort: (p) => (p.best ? subjLabel(p.best) : null), render: (p) => subjTag(p.best) },
    { key: "n_t", label: "Tournaments", num: true, sort: (p) => p.n_t, render: (p) => p.n_t },
    { key: "last", label: "Last played", sort: (p) => p.last || "", render: (p) => h("span", { class: "nowrap" }, fmt.date(p.last)) },
  ], roster, { sort: { key: "r", dir: "desc" }, pageSize: 50, empty: "No individual statistics published for this school." })));
  return root;
}
