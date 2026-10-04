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
  return h("div", null, teamA(T, id), t ? h("span", { class: "sub" }, [t.school_name, t.state].filter(Boolean).join(" · ")) : null);
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
