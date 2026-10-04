// Router, header (nav, global search, theme toggle) and footer.

import { h, clear, icon, combobox, href, fmt, loadingState, errorState, notFound, extLink } from "./ui.js";
import { hideTip, onScrollTip } from "./charts.js";
import * as data from "./data.js";

const PAGES = {
  home: () => import("./pages/home.js"),
  teams: () => import("./pages/teams.js"),
  team: () => import("./pages/team.js"),
  players: () => import("./pages/players.js"),
  player: () => import("./pages/player.js"),
  school: () => import("./pages/school.js"),
  tournaments: () => import("./pages/tournaments.js"),
  tournament: () => import("./pages/tournament.js"),
  nationals: () => import("./pages/nationals.js"),
  compare: () => import("./pages/compare.js"),
  about: () => import("./pages/about.js"),
};

const ROUTES = [
  [/^\/?$/i, "home"],
  [/^\/teams\/?$/i, "teams"],
  [/^\/team\/([^/]+)\/?$/i, "team"],
  [/^\/players\/?$/i, "players"],
  [/^\/player\/([^/]+)\/?$/i, "player"],
  [/^\/school\/([^/]+)\/?$/i, "school"],
  [/^\/tournaments\/?$/i, "tournaments"],
  [/^\/tournament\/([^/]+)\/?$/i, "tournament"],
  [/^\/nationals\/?$/i, "nationals"],
  [/^\/compare\/?$/i, "compare"],
  [/^\/(about|methodology)\/?$/i, "about"],
];

const NAV_FOR = { teams: "teams", team: "teams", school: "teams", players: "players", player: "players", tournaments: "tournaments", tournament: "tournaments", nationals: "nationals", compare: "compare", about: "about" };

export function parseHash(hash = location.hash) {
  let raw = hash.replace(/^#/, "");
  if (!raw.startsWith("/")) raw = "/" + raw;
  const qi = raw.indexOf("?");
  const path = qi >= 0 ? raw.slice(0, qi) : raw;
  const query = new URLSearchParams(qi >= 0 ? raw.slice(qi + 1) : "");
  for (const [re, name] of ROUTES) {
    const m = path.match(re);
    if (m) {
      let param = null;
      try { param = m[1] != null && name !== "about" ? decodeURIComponent(m[1]) : null; } catch { param = m[1]; }
      return { name, param, query, path };
    }
  }
  return { name: "notfound", param: null, query, path };
}

const main = document.getElementById("main");
let renderSeq = 0;
let lastPath = null;

async function route() {
  const r = parseHash();
  const seq = ++renderSeq;
  hideTip();
  // same page, only the query changed through replaceState-free navigation: still re-render
  for (const a of document.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === NAV_FOR[r.name]) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const samePage = lastPath === r.path;
  lastPath = r.path;
  if (!samePage) {
    clear(main).appendChild(loadingState());
  }
  const ctx = {
    param: r.param,
    query: r.query,
    path: r.path,
    alive: () => seq === renderSeq,
    setTitle: (t) => { document.title = t ? `${t} · SBRanks` : "SBRanks · Science Bowl ratings"; },
  };
  ctx.setTitle(null);
  try {
    if (r.name === "notfound") {
      ctx.setTitle("Not found");
      clear(main).appendChild(notFound("Page", null));
    } else {
      const mod = await PAGES[r.name]();
      if (!ctx.alive()) return;
      const out = await mod.render(ctx);
      if (!ctx.alive()) return;
      clear(main);
      if (out) main.appendChild(out);
    }
  } catch (err) {
    if (!ctx.alive()) return;
    console.warn(err);
    clear(main).appendChild(errorState(err));
  }
  if (!samePage) {
    window.scrollTo(0, 0);
    // move focus for keyboard and screen-reader users after a page change (not on first load)
    if (route.started) main.focus({ preventScroll: true });
  }
  route.started = true;
}

// ------------------------------------------------------------------ theme toggle
const THEME_KEY = "sbranks-theme";
function getTheme() {
  try { return localStorage.getItem(THEME_KEY) || "system"; } catch { return "system"; }
}
function setTheme(t) {
  try { if (t === "system") localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, t); } catch { /* ignore */ }
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  renderThemeToggle();
}
function renderThemeToggle() {
  const el = document.getElementById("theme-toggle");
  const cur = getTheme();
  clear(el);
  for (const [key, ic, label] of [["system", "monitor", "System theme"], ["light", "sun", "Light theme"], ["dark", "moon", "Dark theme"]]) {
    el.appendChild(h("button", { type: "button", "aria-pressed": String(cur === key), "aria-label": label, title: label, onclick: () => setTheme(key) }, icon(ic)));
  }
}

// ------------------------------------------------------------------ global search
function renderSearch() {
  const host = document.getElementById("global-search");
  const cb = combobox({
    placeholder: "Search teams, players…",
    label: "Search teams, players, schools and tournaments",
    search: (q) => data.search(q).then((items) => items.map((it) => ({ ...it, group: it.type }))),
    onPick: (it, input) => {
      input.value = "";
      input.blur();
      const target = { Teams: href.team, Players: href.player, Schools: href.school, Tournaments: href.tournament }[it.type](it.id);
      location.hash = target;
    },
  });
  host.appendChild(cb.el);
  // "/" focuses search
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !e.ctrlKey && !e.metaKey && !/input|textarea|select/i.test(document.activeElement.tagName)) {
      e.preventDefault();
      cb.input.focus();
    }
  });
}

// ------------------------------------------------------------------ footer
async function renderFooter() {
  const el = document.getElementById("footer");
  let m = null;
  try { m = await data.meta(); } catch { /* footer without snapshot */ }
  clear(el);
  el.append(
    h("p", null,
      m ? `Data snapshot ${fmt.date(m.snapshot)} · ${fmt.plural(m.counts.tournaments, "tournament")} with results · built ${fmt.date(m.generated)}. ` : "",
      "Ratings are unofficial and computed from published results. ",
      h("a", { href: "#/about" }, "How ratings work"), "."),
    h("p", null,
      "Results from tournament organizers, the ", extLink("https://scibowl.stanford.edu/tournaments", "Stanford Science Bowl tournament list"),
      ", scibowl.live, ISOBowl, prometheus.science and the DOE National Science Bowl. ",
      extLink("https://github.com/UnweidlyKhan349/sbranks/issues", "Corrections"), "."));
}

// ------------------------------------------------------------------ boot
document.querySelector("[data-skip]").addEventListener("click", (e) => {
  e.preventDefault();
  main.focus();
});
window.addEventListener("hashchange", route);
window.addEventListener("scroll", onScrollTip, { passive: true });
renderThemeToggle();
renderSearch();
renderFooter();
route();
