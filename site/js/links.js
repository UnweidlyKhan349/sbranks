// Entity links and small entity-aware cells shared by pages.

import { h, href, fmt, badge } from "./ui.js";

export function teamA(T, id, { pickup = true } = {}) {
  if (!id) return h("span", { class: "muted" }, "–");
  const t = T && T.byId.get(id);
  return h("span", { class: "nowrap-ok" },
    h("a", { href: href.team(id) }, t ? t.name : id),
    pickup && t && t.composite ? h("span", { class: "tag-prov", title: "Pickup or composite team" }, "pickup") : null);
}

export function playerA(P, id, label) {
  if (!id) return h("span", { class: "muted" }, "–");
  const p = P && P.byId.get(id);
  return h("a", { href: href.player(id) }, label || (p ? p.name : id));
}

export function schoolA(id, name) {
  if (!id) return h("span", { class: "muted" }, name || "–");
  return h("a", { href: href.school(id) }, name || id);
}

export function tournamentA(TR, id) {
  const t = TR && TR.byId.get(id);
  return h("a", { href: href.tournament(id) }, t ? t.name : id);
}

/** "Team name" link plus a muted school/state sub-line. */
export function teamCell(T, id) {
  const t = T.byId.get(id);
  return h("div", null, teamA(T, id, { pickup: false }), t ? h("span", { class: "sub" }, (t.composite ? ["Pickup team", t.state] : [t.school_name, t.state]).filter(Boolean).join(" · ")) : null);
}

export function tournamentLabel(t) {
  return `${t.name} (${fmt.date(t.date)})`;
}

export function kindLabel(kind) {
  return ({ invitational: "Invitational", league: "League", scrimmage: "Scrimmage", nationals: "NSB Nationals", regional: "Regional", online: "Online" })[kind] || (kind ? kind[0].toUpperCase() + kind.slice(1) : "–");
}

export function levelBadge(level) {
  if (!level || level === "standard") return null;
  return badge(level === "novice" ? "Novice" : level === "advanced" ? "Advanced" : level);
}

/** Number of entrants: teams, or competitors for an individual (1v1) event. */
export function entrantCount(t) {
  if (t.individual) return t.n_competitors ?? t.n_players ?? 0;
  return t.n_teams;
}

/** Champion link of a tournament row: a team, or (individual events) a competitor. */
export function championA(T, P, t) {
  if (t.champion) return teamA(T, t.champion);
  if (t.individual && t.champion_name) {
    return t.champion_player && P && P.byId.has(t.champion_player) ? playerA(P, t.champion_player) : h("span", null, t.champion_name);
  }
  return h("span", { class: "muted" }, "–");
}

const ORD = (n) => { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };

/** Nationals finish: 1 -> "1st", "5-6" -> "5th–6th", "RR" -> "Round robin". */
export function finishLabel(f) {
  if (f == null || f === "") return "–";
  if (typeof f === "number") return ORD(f);
  const s = String(f).trim();
  if (/^rr$/i.test(s)) return "Round robin";
  let m = s.match(/^(\d+)\s*[-–]\s*(\d+)$/);
  if (m) return `${ORD(+m[1])}–${ORD(+m[2])}`;
  m = s.match(/^T-?(\d+)$/i);
  if (m) return `T-${ORD(+m[1])}`;
  if (/^\d+$/.test(s)) return ORD(+s);
  return s;
}

/** Sort key for a finish: best placement first, round-robin-only teams last. */
export function finishRank(f) {
  if (typeof f === "number") return f;
  const s = String(f ?? "").toLowerCase();
  if (/^(champion|winner|first)/.test(s)) return 1;
  if (/^(runner|second)/.test(s)) return 2;
  const n = parseInt(s.replace(/^t-?/, ""), 10);
  return Number.isFinite(n) ? n : 999;
}

/** Label for a tournament source link's role ("results+stats" -> "Results and statistics"). */
export function sourceRoleLabel(role, short = false) {
  const known = short
    ? { results: "Results", stats: "Stats", "results+stats": "Results & stats", "results+scoresheets": "Results & scoresheets" }
    : { results: "Results", stats: "Statistics", "results+stats": "Results and statistics", "results+scoresheets": "Results and scoresheets",
      teams: "Team list", "stats-index": "Statistics index", crosscheck: "Cross-check", other: "Source" };
  if (!role) return "Source";
  if (known[role]) return known[role];
  const s = String(role).replace(/[-_+]+/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : "Source";
}

/** Where a source link points: the service name, else the host name. */
export function sourceKindLabel(src) {
  const named = { gsheet: "Google Sheets", isobowl: "ISOBowl", scibowl_live: "scibowl.live", challonge: "Challonge", drive_folder: "Google Drive", drive_file: "Google Drive" }[src.kind];
  if (named) return named;
  try { return new URL(src.url).hostname.replace(/^www\./, ""); } catch { return ""; }
}
