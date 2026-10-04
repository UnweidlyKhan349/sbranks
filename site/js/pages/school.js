import { h, fmt, dataTable, ratingCell, tile, section, pageHead, notFound, notice, badge, subjTag, subjLabel, emptyState } from "../ui.js";
import { sparkline } from "../charts.js";
import { teams, players, schools } from "../data.js";
import { teamA, playerA, schoolA, finishLabel } from "../links.js";

export async function render(ctx) {
  const id = ctx.param;
  const [T, P, S] = await Promise.all([teams(), players(), schools()]);
  const sc = S.byId.get(id);
  if (!sc) { ctx.setTitle("School not found"); return notFound("School", id); }
  ctx.setTitle(sc.name);
  const entries = sc.teams.map((tid) => T.byId.get(tid)).filter(Boolean)
    .sort((a, b) => (b.r ?? -1) - (a.r ?? -1) || a.name.localeCompare(b.name));
  const roster = P.list.filter((p) => p.school === id);
  const pickups = (sc.pickup_teams || []).map((tid) => T.byId.get(tid)).filter(Boolean)
    .sort((a, b) => (b.last || "").localeCompare(a.last || "") || a.name.localeCompare(b.name));
  const aff = sc.affiliate && S.byId.get(sc.affiliate);
  const best = entries.find((t) => t.r != null);
  const seasons = [...new Set(entries.flatMap((t) => t.seasons))].sort();
  const root = h("div");
  root.appendChild(pageHead({
    eyebrow: [h("a", { href: "#/teams" }, "Teams"), h("span", { "aria-hidden": "true" }, "/"), sc.composite ? "Pickup team" : "School", sc.composite ? badge("Pickup / composite") : null],
    title: sc.name,
    sub: [sc.composite ? (aff ? h("span", null, "Players mostly from ", schoolA(aff.id, aff.name)) : h("span", { class: "muted" }, "Players from several schools"))
      : [sc.city, sc.state].filter(Boolean).join(", ") || h("span", { class: "muted" }, "Location not recorded"),
      seasons.length ? `Seasons ${seasons[0]}${seasons.length > 1 ? " – " + seasons[seasons.length - 1] : ""}` : null],
  }));
  if (sc.composite) {
    // pickup/composite placeholder "school": one team, no NSB history, players listed on the team page
    root.appendChild(h("div", { class: "section", style: { "margin-top": 0, "margin-bottom": "20px" } }, notice(h("span", null,
      "This is a pickup or composite team made up of players from ", aff ? "mostly one school" : "several schools", ", not a school. ",
      entries.length === 1 ? ["See ", teamA(T, entries[0].id, { pickup: false }), " for its games and roster."] : null))));
  }
  if (sc.composite && entries.length === 1) {
    const t = entries[0];
    root.appendChild(h("div", { class: "tiles" },
      tile("Rating", t.r != null ? [fmt.r(t.r), h("span", { class: "pm" }, fmt.pm(t.rd))] : "Unrated", t.r != null ? "Glicko-2 ± deviation" : "No rated games yet"),
      tile("Record", t.g ? fmt.record(t.w, t.l, t.t) : "–", fmt.plural(t.g, "rated game")),
      tile("Tournaments", fmt.int(t.n_t), fmt.seasons(t.seasons))));
  } else root.appendChild(h("div", { class: "tiles" },
    tile("Best team rating", best ? [fmt.r(best.r), h("span", { class: "pm" }, fmt.pm(best.rd))] : "–", best ? best.name : null),
    tile("Team entries", fmt.int(entries.length), entries.map((t) => t.letter || "").filter(Boolean).join(" · ") || null),
    tile("Players", fmt.int(roster.length), "with published stats"),
    tile("Nationals", sc.nsb && sc.nsb.length ? fmt.int(sc.nsb.length) : "–", sc.nsb && sc.nsb.length ? "appearances on record" : "no finishes on record")));

  root.appendChild(section("Teams", sc.composite ? null : "Every A/B/C… entry from this school", dataTable([
    { key: "name", label: "Team", cls: "name", sort: (t) => t.name, render: (t) => teamA(T, t.id) },
    { key: "r", label: "Rating", num: true, sort: (t) => t.r, render: (t) => ratingCell(t.r, t.rd, { provisional: t.r != null && t.rank == null }) },
    { key: "rank", label: "Rank", num: true, sort: (t) => t.rank, defaultDir: "asc", render: (t) => t.rank ?? "–" },
    { key: "rec", label: "W–L–T", num: true, sort: (t) => (t.g ? (t.w + 0.5 * t.t) / t.g : null), render: (t) => (t.g ? fmt.record(t.w, t.l, t.t) : "–") },
    { key: "n_t", label: "Tournaments", num: true, sort: (t) => t.n_t, render: (t) => t.n_t },
    { key: "seasons", label: "Seasons", sort: (t) => t.seasons[0] || null, render: (t) => h("span", { class: "nowrap", title: t.seasons.join(", ") }, fmt.seasons(t.seasons)) },
    { key: "last", label: "Last played", sort: (t) => t.last, render: (t) => h("span", { class: "nowrap" }, fmt.date(t.last)) },
    { key: "trend", label: "Trend", hideSm: true, render: (t) => sparkline(t.trend) },
  ], entries, { sort: { key: "r", dir: "desc" }, empty: "No team entries." })));

  if (pickups.length) {
    root.appendChild(section("Pickup teams with this school's players", "Online pickup and composite teams whose players mostly come from this school; their games count for those teams, not for the school's own entries", dataTable([
      { key: "name", label: "Team", cls: "name", sort: (t) => t.name, render: (t) => teamA(T, t.id, { pickup: false }) },
      { key: "r", label: "Rating", num: true, sort: (t) => t.r, render: (t) => ratingCell(t.r, t.rd, { provisional: t.r != null && t.rank_open == null }) },
      { key: "rec", label: "W–L–T", num: true, sort: (t) => (t.g ? (t.w + 0.5 * t.t) / t.g : null), render: (t) => (t.g ? fmt.record(t.w, t.l, t.t) : "–") },
      { key: "n_t", label: "Tournaments", num: true, sort: (t) => t.n_t, render: (t) => t.n_t },
      { key: "last", label: "Last played", sort: (t) => t.last, defaultDir: "desc", render: (t) => h("span", { class: "nowrap" }, fmt.date(t.last)) },
    ], pickups, { sort: { key: "last", dir: "desc" }, caption: "Pickup teams with this school's players", captionHidden: true })));
  }

  if (sc.composite) return root;
  const nsb = (sc.nsb || []).slice().sort((a, b) => b.year - a.year);
  root.appendChild(section("NSB Nationals", h("a", { href: "#/nationals" }, "Nationals history"),
    nsb.length ? dataTable([
      { key: "year", label: "Year", render: (x) => String(x.year) },
      { key: "finish", label: "Finish", render: (x) => finishLabel(x.finish) },
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
