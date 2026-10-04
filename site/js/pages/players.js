import { h, clear, fmt, dataTable, ratingCell, tabs, subjectTabItems, subjLabel, subjTag, pageHead, setQuery, boolParam, debounce, csvButton } from "../ui.js";
import { meta, players, isActive } from "../data.js";
import { playerA, schoolA } from "../links.js";

export async function render(ctx) {
  const [m, P] = await Promise.all([meta(), players()]);
  ctx.setTitle("Players");
  const q = ctx.query;
  const subjects = ["overall", ...m.subjects.map((x) => x.key)];
  const st = {
    s: subjects.includes(q.get("s")) ? q.get("s") : "overall",
    q: q.get("q") || "",
    state: q.get("state") || "",
    active: boolParam(q, "active", true),
    ranked: boolParam(q, "ranked", true),
    minT: Math.max(1, parseInt(q.get("min") || "1", 10) || 1),
  };
  const states = [...new Set(P.list.map((p) => p.state).filter(Boolean))].sort();
  if (!states.includes(st.state)) st.state = ""; // unknown value from the URL: show all
  const root = h("div");
  root.appendChild(pageHead({
    title: "Player rankings",
    sub: h("span", null, `${fmt.int(P.list.length)} players with published individual statistics. Ratings are Elo-scaled tossup points per tossup heard, adjusted for field strength. Names are shown as published by tournaments. `,
      h("a", { href: "#/about" }, "Methodology")),
  }));
  const panel = h("div");
  root.append(tabs(subjectTabItems(true), st.s, (key) => { st.s = key; update(); }, "Rating", panel), panel);

  const search = h("input", { class: "input", type: "search", placeholder: "Search player or school", "aria-label": "Search players", value: st.q });
  search.addEventListener("input", debounce(() => { st.q = search.value; update(); }, 120));
  const stateSel = h("select", { class: "select", "aria-label": "State" },
    h("option", { value: "" }, "All states"), states.map((x) => h("option", { value: x, selected: x === st.state }, x)));
  stateSel.addEventListener("change", () => { st.state = stateSel.value; update(); });
  const activeBox = h("input", { type: "checkbox", checked: st.active });
  activeBox.addEventListener("change", () => { st.active = activeBox.checked; update(); });
  const rankedBox = h("input", { type: "checkbox", checked: st.ranked });
  rankedBox.addEventListener("change", () => { st.ranked = rankedBox.checked; update(); });
  const minInput = h("input", { class: "input narrow", type: "number", min: "1", max: "50", value: String(st.minT), "aria-label": "Minimum tournaments" });
  minInput.addEventListener("input", debounce(() => { st.minT = Math.max(1, parseInt(minInput.value, 10) || 1); update(); }, 150));
  const csv = csvButton("sbranks-players.csv", ["rank", "player", "school", "state", "rating", "se", "ppg", "points_per_tuh", "tournaments", "best_subject", "last_played"],
    () => current.map((p) => { const v = val(p); return [rankOf(p), p.name, p.school_name, p.state, v ? Math.round(v.r) : "", v ? Math.round(v.pm) : "", p.ppg, p.ptuh, p.n_t, p.best, p.last]; }));
  panel.appendChild(h("div", { class: "filters", role: "search", "aria-label": "Filter players" },
    search, stateSel,
    h("label", { class: "check", title: `Played within ${m.thresholds.active_days} days of the latest tournament` }, activeBox, "Active only"),
    h("label", { class: "check", title: "Enough tossups heard to be ranked, and active" }, rankedBox, "Ranked only"),
    h("label", { class: "field" }, "Min. tournaments", minInput), csv));
  const note = h("div", { class: "result-note", "aria-live": "polite" });
  const host = h("div");
  panel.append(note, host);

  let current = [];
  function val(p) {
    if (st.s === "overall") return p.r == null ? null : { r: p.r, pm: p.se };
    const v = p.subj[st.s];
    return v ? { r: v.r, pm: v.se } : null;
  }
  function rankOf(p) { return st.s === "overall" ? p.rank : (p.subj[st.s] ? p.subj[st.s].rank : null); }

  function update() {
    setQuery("/players", { s: st.s === "overall" ? null : st.s, q: st.q || null, state: st.state || null, active: st.active ? null : "0", ranked: st.ranked ? null : "0", min: st.minT > 1 ? String(st.minT) : null });
    const terms = st.q.toLowerCase().split(/\s+/).filter(Boolean);
    const base = P.list.filter((p) => st.s === "overall" || p.subj[st.s]);
    const rows = base.filter((p) => {
      if (st.state && p.state !== st.state) return false;
      if (st.active && !isActive(p.last, m)) return false;
      if (p.n_t < st.minT) return false;
      if (terms.length) {
        const k = `${p.name} ${p.school_name || ""} ${(p.aliases || []).join(" ")}`.toLowerCase();
        if (!terms.every((x) => k.includes(x))) return false;
      }
      return true;
    });
    // with "Ranked only", provisional players are listed separately below rather than dropped
    const ranked = st.ranked ? rows.filter((p) => rankOf(p) != null) : rows;
    const prov = st.ranked ? rows.filter((p) => rankOf(p) == null) : [];
    current = rows;
    clear(note).append(st.ranked ? `${fmt.plural(ranked.length, "ranked player")}, ${fmt.int(prov.length)} provisional` : fmt.plural(rows.length, "player"),
      st.s !== "overall" ? ` with ${/^[AEIOU]/.test(subjLabel(st.s)) ? "an" : "a"} ${subjLabel(st.s)} rating` : "");
    const hidden = base.length - rows.length;
    if (hidden > 0) {
      note.append(h("span", null, ` · ${fmt.int(hidden)} hidden by filters `), h("button", { type: "button", class: "btn-link", onclick: () => {
        Object.assign(st, { q: "", state: "", active: false, ranked: false, minT: 1 });
        search.value = ""; stateSel.value = ""; activeBox.checked = false; rankedBox.checked = false; minInput.value = "1";
        update();
      } }, "Show all players"));
    }
    const subj = st.s !== "overall";
    const columns = [
      { key: "rank", label: "#", num: true, cls: "rank", sort: (p) => rankOf(p), defaultDir: "asc", render: (p) => rankOf(p) ?? "–" },
      { key: "name", label: "Player", cls: "name", sort: (p) => p.name, render: (p) => h("div", null, playerA(P, p.id), p.school_name ? h("span", { class: "sub show-sm" }, p.school_name) : null) },
      { key: "school", label: "School", cls: "wrap", hideSm: true, sort: (p) => p.school_name || "", render: (p) => h("div", null, schoolA(p.school, p.school_name), p.state ? h("span", { class: "sub" }, p.state) : null) },
      { key: "r", label: subj ? `${subjLabel(st.s)} rating` : "Rating", num: true, sort: (p) => (val(p) ? val(p).r : null), tie: (p) => rankOf(p),
        render: (p) => { const v = val(p); return v ? ratingCell(v.r, v.pm, { provisional: rankOf(p) == null }) : h("span", { class: "muted", title: "No overall rating: only single-subject events or only per-subject statistics" }, "unrated"); } },
      subj
        ? { key: "pts", label: "Points", num: true, title: `Tossup points in ${subjLabel(st.s)}`, sort: (p) => p.subj[st.s]?.pts, render: (p) => fmt.int(p.subj[st.s]?.pts) }
        : { key: "ppg", label: "PPG", num: true, title: "Tossup points per game", sort: (p) => p.ppg, render: (p) => fmt.num(p.ppg) },
      subj
        ? { key: "n", label: "Tossups", num: true, title: "Effective tossups heard in this subject", sort: (p) => p.subj[st.s]?.n, render: (p) => fmt.int(p.subj[st.s]?.n) }
        : { key: "ptuh", label: "P/TUH", num: true, title: "Tossup points per tossup heard (where tossups heard were published)", sort: (p) => p.ptuh, render: (p) => fmt.num(p.ptuh, 2) },
      { key: "n_t", label: "Tourn.", num: true, title: "Tournaments played", sort: (p) => p.n_t, render: (p) => p.n_t },
      subj ? null : { key: "best", label: "Best subject", sort: (p) => (p.best ? subjLabel(p.best) : null), render: (p) => subjTag(p.best, true) },
      { key: "last", label: "Last played", sort: (p) => p.last || "", defaultDir: "desc", render: (p) => h("span", { class: "nowrap" }, fmt.date(p.last)) },
    ].filter(Boolean);
    clear(host).appendChild(dataTable(columns, ranked, {
      pageSize: 100, sort: { key: "r", dir: "desc" }, caption: `${subjLabel(st.s)} player rankings`, captionHidden: true,
      empty: prov.length ? "No ranked players match these filters — see the provisional list below." : "No players match these filters.",
      rowClass: (p) => (rankOf(p) == null ? "dim" : null),
    }));
    if (prov.length) {
      const minN = m.thresholds.player_min_tuh[st.s] ?? m.thresholds.player_min_tuh.overall;
      host.appendChild(h("details", { class: "section prov-list", open: ranked.length < 25 },
        h("summary", null, h("strong", null, `Provisional and unrated players (${fmt.int(prov.length)})`)),
        h("p", { class: "muted", style: { "font-size": "13px", margin: "6px 0 10px" } },
          `Fewer than ${minN} effective tossups heard${subj ? ` in ${subjLabel(st.s)}` : ""} or fewer than ${m.thresholds.player_min_tournaments ?? 2} tournaments, or not active${subj ? "" : ", or only single-subject events (no overall rating)"}.`),
        dataTable(columns, prov, { pageSize: 100, sort: { key: "r", dir: "desc" }, caption: "Provisional and unrated players", captionHidden: true, rowClass: () => "dim" })));
    }
  }
  update();
  return root;
}
