import { h, clear, fmt, dataTable, ratingCell, tabs, subjectTabItems, subjLabel, pageHead, setQuery, boolParam, debounce, csvButton } from "../ui.js";
import { sparkline } from "../charts.js";
import { meta, teams, schools, isActive } from "../data.js";
import { teamA, schoolA } from "../links.js";

export async function render(ctx) {
  const [m, T, S] = await Promise.all([meta(), teams(), schools()]);
  ctx.setTitle("Teams");
  const q = ctx.query;
  const subjects = ["overall", ...m.subjects.map((x) => x.key)];
  const st = {
    s: subjects.includes(q.get("s")) ? q.get("s") : "overall",
    q: q.get("q") || "",
    state: q.get("state") || "",
    season: q.get("season") || "",
    active: boolParam(q, "active", true),
    ranked: null, // resolved below (default depends on subject)
    comp: boolParam(q, "comp", true),
  };
  st.ranked = boolParam(q, "ranked", st.s === "overall");

  const states = [...new Set(T.list.map((t) => t.state).filter(Boolean))].sort();
  // values from the URL that match no option fall back to "all" (the select could not show them)
  if (!states.includes(st.state)) st.state = "";
  if (!m.seasons.includes(st.season)) st.season = "";
  const root = h("div");
  root.appendChild(pageHead({
    title: "Team rankings",
    sub: h("span", null, `${fmt.int(T.list.length)} team entries (A/B/C… teams and pickup teams). Overall ratings are Glicko-2; subject ratings are Elo-scaled points per tossup heard. `,
      h("a", { href: "#/about" }, "Methodology")),
  }));

  const panel = h("div");
  const tabEl = tabs(subjectTabItems(true), st.s, (key) => {
    const wasDefault = st.ranked === (st.s === "overall");
    st.s = key;
    if (wasDefault) { st.ranked = key === "overall"; rankedBox.checked = st.ranked; }
    update();
  }, "Rating", panel);
  root.append(tabEl, panel);

  // ---- filter row
  const search = h("input", { class: "input", type: "search", placeholder: "Search team or school", "aria-label": "Search teams", value: st.q });
  search.addEventListener("input", debounce(() => { st.q = search.value; update(); }, 120));
  const stateSel = h("select", { class: "select", "aria-label": "State" },
    h("option", { value: "" }, "All states"), states.map((x) => h("option", { value: x, selected: x === st.state }, x)));
  stateSel.addEventListener("change", () => { st.state = stateSel.value; update(); });
  const seasonSel = h("select", { class: "select", "aria-label": "Season" },
    h("option", { value: "" }, "All seasons"), m.seasons.map((x) => h("option", { value: x, selected: x === st.season }, x)));
  seasonSel.addEventListener("change", () => { st.season = seasonSel.value; update(); });
  const box = (label, key, title) => {
    const input = h("input", { type: "checkbox", checked: st[key] });
    input.addEventListener("change", () => { st[key] = input.checked; update(); });
    return [h("label", { class: "check", title }, input, label), input];
  };
  const [activeLbl] = box("Active only", "active", `Played within ${m.thresholds.active_days} days of the latest tournament`);
  const [rankedLbl, rankedBox] = box("Ranked only", "ranked", `Overall: rating deviation at most ${m.thresholds.ranked_rd} and active. Subjects: enough tossups heard and active.`);
  const [compLbl] = box("Include pickup/composite teams", "comp", "Online pickup teams and composite teams made of players from several schools");
  const csv = csvButton("sbranks-teams.csv", ["rank", "team", "school", "state", "rating", "deviation", "wins", "losses", "ties", "games", "last_played"],
    () => current.map((t) => {
      const v = val(t);
      return [rankOf(t), t.name, t.school_name, t.state, v ? Math.round(v.r) : "", v ? Math.round(v.pm) : "", t.w, t.l, t.t, t.g, t.last];
    }));
  panel.appendChild(h("div", { class: "filters", role: "search", "aria-label": "Filter teams" }, search, stateSel, seasonSel, activeLbl, rankedLbl, compLbl, csv));
  const note = h("div", { class: "result-note", "aria-live": "polite" });
  const tableHost = h("div");
  panel.append(note, tableHost);

  let current = [];
  function val(t) {
    if (st.s === "overall") return t.r == null ? null : { r: t.r, pm: t.rd };
    const v = t.subj[st.s];
    return v ? { r: v.r, pm: v.se, n: v.n } : null;
  }
  function rankOf(t) { return st.s === "overall" ? t.rank : (t.subj[st.s] ? t.subj[st.s].rank : null); }

  function update() {
    setQuery("/teams", {
      s: st.s === "overall" ? null : st.s, q: st.q || null, state: st.state || null, season: st.season || null,
      active: st.active ? null : "0", ranked: st.ranked === (st.s === "overall") ? null : (st.ranked ? "1" : "0"), comp: st.comp ? null : "0",
    });
    const terms = st.q.toLowerCase().split(/\s+/).filter(Boolean);
    const base = T.list.filter((t) => st.s === "overall" || t.subj[st.s]);
    const passes = (t) => {
      if (st.state && t.state !== st.state) return false;
      if (st.season && !t.seasons.includes(st.season)) return false;
      if (st.active && !isActive(t.last, m)) return false;
      if (!st.comp && t.composite) return false;
      if (terms.length) {
        const k = `${t.name} ${t.school_name || ""}`.toLowerCase();
        if (!terms.every((x) => k.includes(x))) return false;
      }
      return true;
    };
    const byVal = (a, b) => {
      const va = val(a), vb = val(b);
      if (!va && !vb) return a.name.localeCompare(b.name);
      if (!va) return 1;
      if (!vb) return -1;
      return vb.r - va.r;
    };
    const matching = base.filter(passes).sort(byVal);
    const rows = st.ranked ? matching.filter((t) => rankOf(t) != null) : matching;
    // with "Ranked only", provisional/unranked teams are listed separately rather than dropped
    const prov = st.ranked ? matching.filter((t) => rankOf(t) == null) : [];
    current = matching;
    clear(note);
    const hidden = base.length - matching.length;
    note.append(st.ranked ? `${fmt.plural(rows.length, "ranked team")}, ${fmt.int(prov.length)} provisional` : `${fmt.plural(rows.length, "team")}`,
      st.s !== "overall" ? ` with ${/^[AEIOU]/.test(subjLabel(st.s)) ? "an" : "a"} ${subjLabel(st.s)} rating` : "");
    if (hidden > 0) {
      note.append(h("span", null, ` · ${fmt.int(hidden)} hidden by filters `),
        h("button", { type: "button", class: "btn-link", onclick: () => {
          Object.assign(st, { q: "", state: "", season: "", active: false, ranked: false, comp: true });
          search.value = ""; stateSel.value = ""; seasonSel.value = "";
          for (const cb of root.querySelectorAll(".filters input[type=checkbox]")) cb.checked = cb === compLbl.querySelector("input");
          update();
        } }, "Show all teams"));
    }
    const subj = st.s !== "overall";
    const columns = [
      { key: "rank", label: "#", num: true, cls: "rank", title: "Rank among ranked teams", sort: (t) => rankOf(t), defaultDir: "asc", render: (t) => rankOf(t) ?? "–" },
      { key: "name", label: "Team", cls: "name", sort: (t) => t.name, render: (t) => h("div", null, teamA(T, t.id), t.state ? h("span", { class: "sub show-sm" }, t.state) : null) },
      { key: "school", label: "School", cls: "wrap", hideSm: true, sort: (t) => (t.composite ? "" : t.school_name || ""),
        render: (t) => (t.composite
          ? h("div", null, h("span", { class: "muted" }, "Pickup team"), t.affiliate && S.byId.has(t.affiliate) ? h("span", { class: "sub" }, "mostly ", schoolA(t.affiliate, S.byId.get(t.affiliate).name)) : null)
          : h("div", null, schoolA(t.school, t.school_name), t.state ? h("span", { class: "sub" }, t.state) : null)) },
      { key: "r", label: subj ? `${subjLabel(st.s)} rating` : "Rating", num: true, sort: (t) => (val(t) ? val(t).r : null), tie: (t) => rankOf(t),
        title: subj ? "Elo-scaled subject rating ± standard error" : "Glicko-2 rating ± rating deviation",
        render: (t) => { const v = val(t); return v ? ratingCell(v.r, v.pm, { provisional: rankOf(t) == null }) : h("span", { class: "muted" }, "unrated"); } },
      { key: "rec", label: "W–L–T", num: true, sort: (t) => (t.g ? (t.w + 0.5 * t.t) / t.g : null), render: (t) => (t.g ? fmt.record(t.w, t.l, t.t) : "–"), title: "Rated games record" },
      { key: "g", label: "Games", num: true, sort: (t) => t.g, render: (t) => fmt.int(t.g) },
      subj ? { key: "n", label: "Tossups", num: true, title: "Effective tossups heard in this subject", sort: (t) => t.subj[st.s]?.n, render: (t) => fmt.int(t.subj[st.s]?.n) } : null,
      { key: "last", label: "Last played", sort: (t) => t.last || "", defaultDir: "desc", render: (t) => h("span", { class: "nowrap" }, fmt.date(t.last)) },
      subj ? null : { key: "trend", label: "Trend", hideSm: true, render: (t) => sparkline(t.trend, { label: `Rating trend for ${t.name}` }) },
    ].filter(Boolean);
    clear(tableHost).appendChild(dataTable(columns, rows, {
      pageSize: 100, caption: `${subjLabel(st.s)} team rankings`, captionHidden: true, sort: { key: "r", dir: "desc" },
      empty: prov.length ? "No ranked teams match these filters yet — see the provisional list below." : "No teams match these filters.",
      rowClass: (t) => (rankOf(t) == null ? "dim" : null),
    }));
    if (prov.length) {
      const why = subj
        ? `Fewer than ${m.thresholds.player_min_tuh[st.s]} effective tossups heard in ${subjLabel(st.s)}, or not active.`
        : `Rating deviation above ${m.thresholds.ranked_rd} (too few recent games to be confident), no rated games yet, or not active.`;
      tableHost.appendChild(h("details", { class: "section prov-list", open: rows.length < 25 },
        h("summary", null, h("strong", null, `Provisional and unranked teams (${fmt.int(prov.length)})`)),
        h("p", { class: "muted", style: { "font-size": "13px", margin: "6px 0 10px" } }, why),
        dataTable(columns, prov, { pageSize: 100, caption: "Provisional and unranked teams", captionHidden: true, sort: { key: "r", dir: "desc" }, rowClass: () => "dim" })));
    }
  }
  update();
  return root;
}
