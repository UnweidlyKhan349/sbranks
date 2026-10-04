import { h, clear, fmt, dataTable, section, pageHead, combobox, setQuery, SUBJECTS, subjTag, resultBadge, notice, emptyState, loadingState } from "../ui.js";
import { refBars } from "../charts.js";
import { meta, teams, players, tournaments, teamDetail, playerDetail, search, winProb } from "../data.js";
import { schoolA, tournamentA } from "../links.js";

const COLORS = { a: "var(--pos)", b: "var(--neg)" };

export async function render(ctx) {
  const [m, T, P, TR] = await Promise.all([meta(), teams(), players(), tournaments()]);
  ctx.setTitle("Compare");
  const q = ctx.query;
  const st = { type: q.get("type") === "players" ? "players" : "teams", a: q.get("a") || "", b: q.get("b") || "" };
  const root = h("div");
  root.appendChild(pageHead({ title: "Compare", sub: "Pick two teams for a win probability, subject-by-subject ratings and their head-to-head games — or two players for their subject profiles and stats. The link is shareable." }));

  const seg = h("div", { class: "seg", role: "group", "aria-label": "Compare teams or players" });
  const pickers = h("div", { class: "vs-grid card" });
  const result = h("div", { "aria-live": "polite" });
  root.append(h("div", { class: "filters" }, seg), pickers, result);

  function store() { return st.type === "teams" ? T : P; }
  function nameOf(id) { const x = store().byId.get(id); return x ? x.name : ""; }

  function renderSeg() {
    clear(seg);
    for (const [k, label] of [["teams", "Teams"], ["players", "Players"]]) {
      seg.appendChild(h("button", { type: "button", "aria-pressed": String(st.type === k), onclick: () => {
        if (st.type === k) return;
        st.type = k; st.a = ""; st.b = "";
        renderAll();
      } }, label));
    }
  }

  function picker(slot) {
    const kind = st.type === "teams" ? "Teams" : "Players";
    const cb = combobox({
      placeholder: st.type === "teams" ? "Search for a team" : "Search for a player",
      label: `${slot === "a" ? "First" : "Second"} ${st.type === "teams" ? "team" : "player"}`,
      value: nameOf(st[slot]),
      search: (qq) => search(qq, { types: [kind], limitPerType: 10 }).then((items) => items.map((it) => ({ ...it, sub: it.sub }))),
      onPick: (it, input) => { st[slot] = it.id; input.value = it.label; update(); },
    });
    return h("div", null,
      h("div", { class: "pick-label" }, h("span", { class: "swatch", style: { background: COLORS[slot] }, "aria-hidden": "true" }), slot === "a" ? (st.type === "teams" ? "Team A" : "Player A") : (st.type === "teams" ? "Team B" : "Player B")),
      cb.el);
  }

  function renderPickers() {
    clear(pickers);
    pickers.append(picker("a"), h("div", { class: "vs-sep" },
      h("button", { type: "button", class: "btn", title: "Swap", "aria-label": "Swap the two sides", onclick: () => { [st.a, st.b] = [st.b, st.a]; renderPickers(); update(); } }, "⇄ swap")), picker("b"));
  }

  function renderAll() { renderSeg(); renderPickers(); update(); }

  let seq = 0;
  async function update() {
    setQuery("/compare", { type: st.type === "teams" ? null : "players", a: st.a || null, b: st.b || null });
    const my = ++seq;
    const A = store().byId.get(st.a), B = store().byId.get(st.b);
    clear(result);
    if ((st.a && !A) || (st.b && !B)) result.appendChild(notice(`One of the ${st.type} in this link could not be found.`));
    if (!A || !B) {
      result.appendChild(h("div", { class: "section" }, emptyState(`Choose two ${st.type} to compare.`), suggestions()));
      return;
    }
    result.appendChild(loadingState());
    const out = st.type === "teams" ? await compareTeams(A, B) : await comparePlayers(A, B);
    if (my !== seq || !ctx.alive()) return;
    clear(result).appendChild(out);
  }

  function suggestions() {
    const list = st.type === "teams" ? T.list.filter((t) => t.rank != null).slice(0, 2) : P.list.filter((p) => p.rank != null).slice(0, 2);
    if (list.length < 2) return null;
    return h("p", { class: "empty" }, "Or try ", h("button", { type: "button", class: "btn-link", onclick: () => { st.a = list[0].id; st.b = list[1].id; renderPickers(); update(); } },
      `${list[0].name} vs ${list[1].name}`), ".");
  }

  function subjectChart(A, B, label) {
    const cats = SUBJECTS.map((x) => ({ key: x.key, label: x.label }));
    const vals = (E) => Object.fromEntries(SUBJECTS.filter((x) => E.subj[x.key]).map((x) => {
      const v = E.subj[x.key];
      return [x.key, { value: v.r, pm: v.se, provisional: v.n < (m.thresholds.player_min_tuh[x.key] || 25) }];
    }));
    return refBars(cats, [{ label: A.name, color: COLORS.a, values: vals(A) }, { label: B.name, color: COLORS.b, values: vals(B) }], {
      label,
      table: {
        columns: [
          { key: "s", label: "Subject", render: (r) => r.label },
          { key: "a", label: A.name, num: true, render: (r) => (A.subj[r.key] ? `${fmt.r(A.subj[r.key].r)} ±${Math.round(A.subj[r.key].se)}` : "–") },
          { key: "b", label: B.name, num: true, render: (r) => (B.subj[r.key] ? `${fmt.r(B.subj[r.key].r)} ±${Math.round(B.subj[r.key].se)}` : "–") },
        ], rows: SUBJECTS,
      },
    });
  }

  function statTable(rows, A, B) {
    return dataTable([
      { key: "k", label: "", th: true, render: (r) => r[0] },
      { key: "a", label: h("span", { class: "subj-label" }, h("span", { class: "swatch", style: { background: COLORS.a } }), A.name), render: (r) => r[1] },
      { key: "b", label: h("span", { class: "subj-label" }, h("span", { class: "swatch", style: { background: COLORS.b } }), B.name), render: (r) => r[2] },
    ], rows, { sortable: false });
  }

  async function compareTeams(A, B) {
    const out = h("div");
    if (A.id === B.id) { out.appendChild(notice("Pick two different teams.")); return out; }
    if (A.r != null && B.r != null) {
      const p = winProb(A.r, A.rd, B.r, B.rd);
      out.appendChild(section("Win probability", "Glicko-2 expected result with both rating deviations folded in",
        h("div", { class: "prob-row" },
          h("div", { class: "prob" }, h("div", { class: "prob-val" }, fmt.pct(p)), h("div", { class: "prob-name" }, h("span", { class: "swatch", style: { background: COLORS.a } }), A.name)),
          h("div", { class: "prob" }, h("div", { class: "prob-val" }, fmt.pct(1 - p)), h("div", { class: "prob-name" }, h("span", { class: "swatch", style: { background: COLORS.b } }), B.name))),
        h("p", { class: "muted", style: { "font-size": "13px", "margin-top": "8px" } },
          `${A.name} ${fmt.r(A.r)} ±${Math.round(A.rd)} vs ${B.name} ${fmt.r(B.r)} ±${Math.round(B.rd)}. P = 1 / (1 + exp(−g(φ)·Δr / 173.7)), φ = √(RD₁² + RD₂²) / 173.7.`)));
    } else {
      out.appendChild(h("div", { class: "section" }, notice(`${A.r == null ? A.name : B.name} has no overall rating yet, so no win probability can be computed.`)));
    }
    out.appendChild(section("Subject ratings", "Elo-scaled, 1500 = average; faded bars are provisional", h("div", { class: "card" }, subjectChart(A, B, `Subject ratings: ${A.name} vs ${B.name}`))));
    out.appendChild(section("At a glance", null, statTable([
      ["Rating", A.r != null ? `${fmt.r(A.r)} ±${Math.round(A.rd)}` : "unrated", B.r != null ? `${fmt.r(B.r)} ±${Math.round(B.rd)}` : "unrated"],
      ["Rank", A.rank ? `#${A.rank}` : "unranked", B.rank ? `#${B.rank}` : "unranked"],
      ["Record", A.g ? fmt.record(A.w, A.l, A.t) : "–", B.g ? fmt.record(B.w, B.l, B.t) : "–"],
      ["Peak", fmt.r(A.peak), fmt.r(B.peak)],
      ["School", schoolA(A.school, A.school_name), schoolA(B.school, B.school_name)],
      ["Tournaments", String(A.n_t), String(B.n_t)],
      ["Last played", fmt.date(A.last), fmt.date(B.last)],
    ], A, B)));
    const dA = await teamDetail(A.id);
    const h2h = ((dA && dA.games) || []).filter((g) => g.o === B.id).sort((x, y) => y.d.localeCompare(x.d) || y.seq - x.seq);
    const w = h2h.filter((g) => g.r === "W").length, l = h2h.filter((g) => g.r === "L").length, t = h2h.filter((g) => g.r === "T").length;
    out.appendChild(section("Head-to-head", h2h.length ? `${A.name} is ${fmt.record(w, l, t)} against ${B.name}` : null,
      h2h.length ? dataTable([
        { key: "d", label: "Date", render: (g) => h("span", { class: "nowrap" }, fmt.date(g.d)) },
        { key: "t", label: "Tournament", cls: "name", render: (g) => tournamentA(TR, g.t) },
        { key: "rd", label: "Round", render: (g) => g.rd || "–" },
        { key: "s", label: "Score", num: true, render: (g) => (g.ff ? "forfeit" : g.s != null ? `${fmt.int(g.s)}–${fmt.int(g.os)}` : "–") },
        { key: "r", label: `${A.name}`, cls: "ctr", render: (g) => resultBadge(g.r) },
        { key: "p", label: "Pre-game", num: true, title: `Pre-game win probability for ${A.name}`, render: (g) => fmt.pct(g.p) },
      ], h2h, { sortable: false }) : emptyState("These teams have not played each other in the recorded games.")));
    return out;
  }

  async function comparePlayers(A, B) {
    const out = h("div");
    if (A.id === B.id) { out.appendChild(notice("Pick two different players.")); return out; }
    out.appendChild(section("Subject ratings", "Elo-scaled, 1500 = average; faded bars are provisional", h("div", { class: "card" }, subjectChart(A, B, `Subject ratings: ${A.name} vs ${B.name}`))));
    out.appendChild(section("At a glance", null, statTable([
      ["Rating", A.r != null ? `${fmt.r(A.r)} ±${Math.round(A.se)}` : "unrated", B.r != null ? `${fmt.r(B.r)} ±${Math.round(B.se)}` : "unrated"],
      ["Rank", A.rank ? `#${A.rank}` : "unranked", B.rank ? `#${B.rank}` : "unranked"],
      ["School", schoolA(A.school, A.school_name), schoolA(B.school, B.school_name)],
      ["Points per game", fmt.num(A.ppg), fmt.num(B.ppg)],
      ["Points per tossup heard", fmt.num(A.ptuh, 2), fmt.num(B.ptuh, 2)],
      ["Tournaments", String(A.n_t), String(B.n_t)],
      ["Games", fmt.int(A.gp), fmt.int(B.gp)],
      ["Tossup points", fmt.int(A.pts), fmt.int(B.pts)],
      ["Best subject", subjTag(A.best), subjTag(B.best)],
      ["Peak", fmt.r(A.peak), fmt.r(B.peak)],
      ["Last played", fmt.date(A.last), fmt.date(B.last)],
    ], A, B)));
    const [dA, dB] = await Promise.all([playerDetail(A.id), playerDetail(B.id)]);
    const sB = new Map(((dB && dB.stats) || []).map((x) => [x.t, x]));
    const common = ((dA && dA.stats) || []).filter((x) => sB.has(x.t)).reverse();
    const ppg = (x) => { const o = x && x.s.overall; return o ? (o.ppg != null ? o.ppg : o.pts != null && o.gp ? o.pts / o.gp : null) : null; };
    out.appendChild(section("Shared tournaments", null, common.length ? dataTable([
      { key: "d", label: "Date", render: (x) => h("span", { class: "nowrap" }, fmt.date(x.d)) },
      { key: "t", label: "Tournament", cls: "name", render: (x) => tournamentA(TR, x.t) },
      { key: "a", label: `${A.name} PPG`, num: true, render: (x) => fmt.num(ppg(x)) },
      { key: "b", label: `${B.name} PPG`, num: true, render: (x) => fmt.num(ppg(sB.get(x.t))) },
      { key: "same", label: "", render: (x) => (x.tm === sB.get(x.t).tm ? h("span", { class: "muted" }, "teammates") : "") },
    ], common, { sortable: false }) : emptyState("These players have not played at the same tournament.")));
    return out;
  }

  renderAll();
  return root;
}
