// Playwright smoke test for the static site. It does not start a server; pass the base URL:
//
//   python3 -m http.server 8765 -d site &
//   NODE_PATH=$(npm root -g) node site/tests/smoke.mjs http://localhost:8765/
//
// Visits every route type with real ids from site/data, fails on any console error, uncaught
// exception or failed request, checks for horizontal overflow at 375px, exercises a few
// interactions, and saves screenshots to .cache/screens/.

import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = (process.argv[2] || "http://localhost:8765/").replace(/\/?$/, "/");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const outDir = join(root, ".cache", "screens");
mkdirSync(outDir, { recursive: true });

const getJSON = async (p) => {
  const r = await fetch(new URL(p, base));
  if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`);
  return r.json();
};

const [teams, players, tournaments, schools] = await Promise.all([getJSON("data/teams.json"), getJSON("data/players.json"), getJSON("data/tournaments.json"), getJSON("data/schools.json")]);
const enc = encodeURIComponent;
const topTeam = teams.find((t) => t.rank === 1) || teams[0];
const secondTeam = teams.find((t) => t.rank === 2) || teams[1];
const composite = teams.find((t) => t.composite);
const topPlayer = players.find((p) => p.rank === 1) || players[0];
const secondPlayer = players.find((p) => p.rank === 2) || players[1];
const noOverall = players.find((p) => p.r == null);
const withStats = tournaments.find((t) => !t.no_data && t.coverage && t.coverage.player_stats);
const noData = tournaments.find((t) => t.no_data);
const unrated = teams.find((t) => t.r == null);
const individual = tournaments.find((t) => t.individual && !t.no_data && (t.n_competitors || t.n_players));
const affiliated = teams.find((t) => t.composite && t.affiliate);
const pickupSchool = schools.find((sc) => (sc.pickup_teams || []).length);
const nsbTournament = tournaments.find((t) => t.kind === "nationals" && !t.no_data);

const routes = [
  ["home", "#/"],
  ["teams", "#/teams"],
  ["teams-math", "#/teams?s=math"],
  ["team-top", `#/team/${enc(topTeam.id)}`],
  composite ? ["team-composite", `#/team/${enc(composite.id)}`] : null,
  unrated ? ["team-unrated", `#/team/${enc(unrated.id)}`] : null,
  affiliated ? ["team-pickup-affiliate", `#/team/${enc(affiliated.id)}`] : null,
  affiliated ? ["school-composite", `#/school/${enc(affiliated.school)}`] : null,
  ["school", `#/school/${enc(topTeam.school)}`],
  pickupSchool ? ["school-with-pickups", `#/school/${enc(pickupSchool.id)}`] : null,
  ["players", "#/players"],
  ["players-energy", "#/players?s=energy"],
  ["player-top", `#/player/${enc(topPlayer.id)}`],
  noOverall ? ["player-no-overall", `#/player/${enc(noOverall.id)}`] : null,
  ["tournaments", "#/tournaments"],
  withStats ? ["tournament-stats", `#/tournament/${enc(withStats.id)}`] : null,
  noData ? ["tournament-nodata", `#/tournament/${enc(noData.id)}`] : null,
  individual ? ["tournament-individual", `#/tournament/${enc(individual.id)}`] : null,
  nsbTournament ? ["tournament-nsb", `#/tournament/${enc(nsbTournament.id)}`] : null,
  ["nationals", "#/nationals"],
  ["compare-teams", `#/compare?a=${enc(topTeam.id)}&b=${enc(secondTeam.id)}`],
  ["compare-players", `#/compare?type=players&a=${enc(topPlayer.id)}&b=${enc(secondPlayer.id)}`],
  ["about", "#/about"],
  ["notfound-team", "#/team/this-team-does-not-exist"],
  ["notfound-route", "#/no/such/page"],
].filter(Boolean);
if (!composite) console.warn("note: no composite/pickup team in the data yet; the composite check below flags one in the browser");

const failures = [];
const fail = (msg) => { failures.push(msg); console.error("FAIL", msg); };

const browser = await chromium.launch();

async function newPage(width, theme) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 600 ? 812 : 900 }, colorScheme: theme || "light", deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") fail(`[${width}] console error on ${page.url()}: ${m.text()}`); });
  page.on("pageerror", (e) => fail(`[${width}] uncaught exception on ${page.url()}: ${e.message}`));
  page.on("requestfailed", (r) => fail(`[${width}] request failed: ${r.url()} (${r.failure() && r.failure().errorText})`));
  page.on("response", (r) => { if (r.status() >= 400) fail(`[${width}] HTTP ${r.status()} for ${r.url()}`); });
  return { ctx, page };
}

async function settle(page) {
  await page.waitForFunction(() => {
    const main = document.getElementById("main");
    return main && !main.querySelector(".state-loading") && main.querySelector("h1");
  }, null, { timeout: 15000 });
  await page.waitForTimeout(150);
}

for (const [width, theme] of [[1280, "light"], [375, "light"], [375, "dark"]]) {
  const { ctx, page } = await newPage(width, theme);
  for (const [name, hash] of routes) {
    if (theme === "dark" && !["home", "team-top", "player-top", "tournament-stats", "tournament-individual", "nationals", "compare-teams"].includes(name)) continue;
    const url = base + hash;
    try {
      await page.goto(url, { waitUntil: "load" });
      await settle(page);
    } catch (e) {
      fail(`[${width}] ${name}: page did not finish rendering (${e.message.split("\n")[0]})`);
      continue;
    }
    const h1 = (await page.textContent("main h1")) || "";
    if (/^Something went wrong/.test(h1)) fail(`[${width}] ${name}: error state rendered`);
    if (name.startsWith("notfound") && !/not found/i.test(h1)) fail(`[${width}] ${name}: expected a not-found page, got "${h1}"`);
    if (!name.startsWith("notfound") && /not found/i.test(h1)) fail(`[${width}] ${name}: unexpected not-found page`);
    if (width < 600) {
      // body has overflow-x: hidden as a safety net, which would hide (clip) overflowing content rather
      // than make the page scroll; so also look for any visible element that pokes past the viewport
      // outside a scroll container (wide tables scroll inside .table-wrap and are fine)
      const over = await page.evaluate(() => {
        const W = document.documentElement.clientWidth;
        const scrolls = (el) => { for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) { if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(a).overflowX)) return true; if (a.tagName === "DETAILS" && !a.open) return true; } return false; };
        const out = [];
        for (const el of document.querySelectorAll("header *, main *, footer *")) {
          if (el.closest(".sr-only, [hidden]")) continue;
          const r = el.getBoundingClientRect();
          if ((r.width || r.height) && r.right > W + 0.5 && !scrolls(el)) out.push(`<${el.tagName.toLowerCase()}> "${(el.textContent || "").trim().slice(0, 30)}" ends at ${Math.round(r.right)}px`);
        }
        return { doc: document.documentElement.scrollWidth, body: document.body.scrollWidth, win: W, out };
      });
      if (over.doc > over.win || over.body > over.win) fail(`[${width}] ${name}: horizontal overflow (${Math.max(over.doc, over.body)}px > ${over.win}px)`);
      if (over.out.length) fail(`[${width}] ${name}: content cut off at the right edge: ${over.out.slice(0, 3).join("; ")}`);
    }
    await page.screenshot({ path: join(outDir, `${name}-${width}${theme === "dark" ? "-dark" : ""}.png`), fullPage: true });
  }
  await ctx.close();
}

// ---- interactions (desktop)
{
  const { ctx, page } = await newPage(1280);
  // global search
  await page.goto(base + "#/");
  await settle(page);
  const q = topTeam.name.slice(0, 4);
  await page.fill("#global-search input", q);
  await page.waitForSelector("#global-search [role=option]", { timeout: 5000 }).catch(() => fail("global search shows no options"));
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  if (!/#\/(team|player|school|tournament)\//.test(page.url())) fail(`global search Enter did not navigate (url ${page.url()})`);
  // chart hover + keyboard on the team page
  await page.goto(base + `#/team/${enc(topTeam.id)}`);
  await settle(page);
  const svg = page.locator(".chart-plot svg").first();
  await svg.scrollIntoViewIfNeeded();
  const box = await svg.boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height / 2);
    await page.waitForTimeout(100);
    if (await page.locator("#tip").isHidden()) fail("line chart hover shows no tooltip");
    await page.screenshot({ path: join(outDir, "interaction-chart-hover.png") });
  } else fail("team page has no chart");
  await page.mouse.move(5, 5);
  await svg.focus();
  await page.keyboard.press("ArrowLeft");
  if (await page.locator("#tip").isHidden()) fail("line chart keyboard focus shows no tooltip");
  // table view twin
  await page.locator("details.table-view summary").first().click();
  await page.waitForSelector("details.table-view[open] table", { timeout: 3000 }).catch(() => fail("Show table did not render a table"));
  // sorting on the leaderboard
  await page.goto(base + "#/teams");
  await settle(page);
  await page.click("th:has(button:text('Games')) button");
  const sorted = await page.getAttribute("th:has(button:text('Games'))", "aria-sort");
  if (sorted !== "descending") fail(`sorting by Games did not set aria-sort (got ${sorted})`);
  // subject tab via keyboard
  await page.click("[role=tab][aria-selected=true]");
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(150);
  if (!page.url().includes("s=math")) fail(`subject tab did not update the URL (${page.url()})`);
  await page.screenshot({ path: join(outDir, "interaction-teams-math.png"), fullPage: false });
  await ctx.close();
}

// ---- pickup/composite rendering (simulated when the data has none yet)
{
  const { ctx, page } = await newPage(1280);
  let target = composite;
  if (!target) {
    target = teams.find((t) => t.r != null && t.rank == null) || teams[teams.length - 1];
    await page.route("**/data/teams.json", async (route) => {
      const res = await route.fetch();
      const list = await res.json();
      for (const t of list) if (t.id === target.id) t.composite = true;
      await route.fulfill({ response: res, json: list });
    });
  }
  await page.goto(base + `#/team/${enc(target.id)}`);
  await settle(page);
  if (!(await page.locator("main .page-head .badge", { hasText: /pickup/i }).count())) fail("composite team page shows no pickup badge");
  await page.screenshot({ path: join(outDir, "team-composite-1280.png"), fullPage: false });
  await page.goto(base + `#/teams?ranked=0&active=0&q=${enc(target.name)}`);
  await settle(page);
  const before = await page.locator("main tbody tr").count();
  await page.click("label:has-text('Include pickup/composite teams') input");
  await page.waitForTimeout(200);
  const after = await page.locator("main tbody tr a", { hasText: target.name }).count();
  if (!(before > 0 && after === 0)) fail(`pickup filter did not hide the composite team (before ${before}, after ${after})`);
  await ctx.close();
}

// ---- nationals page with champion/finish rows (simulated when the data has none yet)
{
  const nat = await getJSON("data/nationals.json");
  const { ctx, page } = await newPage(1280);
  if (!(nat.winners || []).length) {
    await page.route("**/data/nationals.json", (route) => route.fulfill({ json: {
      winners: [{ year: 2025, champion: "Example High School", state: "CA", runner_up: "Sample Academy" }, { year: 1991, champion: "Old School", state: "NY" }],
      finishes: { 2025: [{ team: topTeam.name, finish: "1st", tm: topTeam.id, school_id: topTeam.school }, { team: "Unmatched Team", finish: "T-5", school: "Unmatched HS" }] },
      tournaments: [],
    } }));
  }
  await page.goto(base + "#/nationals");
  await settle(page);
  const rows = await page.locator("main tbody tr").count();
  if (rows < 2) fail(`nationals page rendered ${rows} table rows`);
  await page.screenshot({ path: join(outDir, "nationals-sample-1280.png"), fullPage: true });
  await ctx.close();
}

// ---- features: individual events, pickup affiliations, Nationals history, collapsed data notes
{
  const { ctx, page } = await newPage(1280);
  const text = async () => (await page.textContent("main")) || "";
  if (individual) {
    await page.goto(base + `#/tournament/${enc(individual.id)}`);
    await settle(page);
    const tx = await text();
    if (!/Individual event/.test(tx)) fail("individual tournament page does not say 'Individual event'");
    if (/\b0 teams\b/.test(tx)) fail("individual tournament page shows '0 teams'");
    const n = await page.locator("main section:has(h2:text-is('Competitors')) tbody tr").count();
    const expect = Math.min(100, individual.n_competitors || individual.n_players);
    if (n !== expect) fail(`individual tournament lists ${n} competitors, expected ${expect}`);
    await page.goto(base + `#/tournaments?q=${enc(individual.name)}`);
    await settle(page);
    if (!(await page.locator("main tbody tr", { hasText: "competitors" }).count())) fail("tournament list does not label an individual event's competitors");
  }
  if (affiliated) {
    await page.goto(base + `#/team/${enc(affiliated.id)}`);
    await settle(page);
    const sub = (await page.textContent(".page-sub")) || "";
    if (!/Players mostly from/.test(sub)) fail("pickup team page lacks 'Players mostly from'");
    if (!(await page.locator(`.page-sub a[href="#/school/${enc(affiliated.affiliate)}"]`).count())) fail("pickup team page does not link its affiliate school");
  }
  if (pickupSchool) {
    await page.goto(base + `#/school/${enc(pickupSchool.id)}`);
    await settle(page);
    const sec = page.locator("main section:has(h2:text-is(\"Pickup teams with this school's players\"))");
    const n = await sec.locator("tbody tr").count();
    if (n !== pickupSchool.pickup_teams.length) fail(`school page lists ${n} pickup teams, expected ${pickupSchool.pickup_teams.length}`);
  }
  // Nationals: champions back to 1991 and per-year finishes with team links
  const nat = await getJSON("data/nationals.json");
  if ((nat.winners || []).length) {
    await page.goto(base + "#/nationals");
    await settle(page);
    const champs = await page.locator("main section:has(h2:text-is('Champions')) tbody tr").count();
    if (champs !== nat.winners.length) fail(`nationals lists ${champs} champions, expected ${nat.winners.length}`);
    const years = Object.keys(nat.finishes || {});
    const cards = await page.locator("main section:has(h2:text-is('Finishes by year')) details").count();
    if (cards !== years.length) fail(`nationals shows ${cards} finish years, expected ${years.length}`);
    const newest = years.sort().reverse()[0];
    const linked = await page.locator("main section:has(h2:text-is('Finishes by year')) details[open] tbody a[href^='#/team/']").count();
    if (newest && linked < Math.min(10, nat.finishes[newest].filter((x) => x.tm).length)) fail(`nationals ${newest} finishes link only ${linked} teams`);
  }
  // maintainer notes stay collapsed
  const withNotes = tournaments.find((t) => t.notes && !t.no_data);
  if (withNotes) {
    await page.goto(base + `#/tournament/${enc(withNotes.id)}`);
    await settle(page);
    const det = page.locator("main details.data-notes");
    if (!(await det.count())) fail("tournament notes are not in a 'Data notes' disclosure");
    else if (await det.evaluate((d) => d.open)) fail("'Data notes' disclosure is open by default");
  }
  await ctx.close();
}

// ---- big leaderboard stays responsive: paging appends rows, no full re-render of thousands
{
  const { ctx, page } = await newPage(1280);
  await page.goto(base + "#/players?ranked=0&active=0");
  await settle(page);
  const r = await page.evaluate(() => {
    const btn = document.querySelector(".more-row .btn");
    if (!btn) return null;
    const t0 = performance.now();
    btn.click();
    document.body.offsetHeight;
    return { ms: performance.now() - t0, rows: document.querySelectorAll("main tbody tr").length, showAll: !![...document.querySelectorAll(".more-row button")].find((b) => b.textContent === "Show all") };
  });
  if (!r) fail("players leaderboard has no 'Show more' button");
  else {
    if (r.ms > 400) fail(`'Show more' on the players leaderboard blocked for ${Math.round(r.ms)} ms`);
    if (r.showAll && players.length > 1000) fail("players leaderboard offers 'Show all' for thousands of rows");
  }
  await ctx.close();
}

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log(`OK: ${routes.length} routes x 2 widths (+ dark spot checks), screenshots in ${outDir}`);
