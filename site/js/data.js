// Data loading: fetch-once caching of site/data/*.json, id indexes, and sharded detail files.
// All URLs are relative so the site works from any sub-path (e.g. a GitHub Pages project site).

const cache = new Map();

export class NotFoundError extends Error {}

export function getJSON(path) {
  if (!cache.has(path)) {
    const p = fetch(path, { cache: "no-cache" })
      .then((r) => {
        if (r.status === 404) throw new NotFoundError(`Missing data file: ${path}`);
        if (!r.ok) throw new Error(`HTTP ${r.status} loading ${path}`);
        return r.json();
      })
      .catch((e) => {
        cache.delete(path);
        throw e;
      });
    cache.set(path, p);
  }
  return cache.get(path);
}

/** djb2 over code points, mirrored from pipeline/export.py. */
export function shardOf(id, n = 32) {
  let h = 5381;
  for (const ch of id) h = ((h * 33) + ch.codePointAt(0)) >>> 0;
  return h % n;
}

function indexed(path, decorate) {
  let p = null;
  return () => {
    if (!p) {
      p = getJSON(path).then((list) => {
        const byId = new Map(list.map((x) => [x.id, x]));
        const out = { list, byId };
        if (decorate) decorate(out);
        return out;
      }).catch((e) => { p = null; throw e; });
    }
    return p;
  };
}

export const meta = () => getJSON("data/meta.json");
export const teams = indexed("data/teams.json");
export const players = indexed("data/players.json");
export const schools = indexed("data/schools.json");
export const tournaments = indexed("data/tournaments.json");
export const nationals = () => getJSON("data/nationals.json").catch((e) => {
  if (e instanceof NotFoundError) return { winners: [], finishes: {}, tournaments: [] };
  throw e;
});

export async function teamDetail(id) {
  const [m, t] = await Promise.all([meta(), teams()]);
  if (!t.byId.has(id)) return null;
  const shard = await getJSON(`data/teams/${shardOf(id, m.n_shards)}.json`);
  return shard[id] || null;
}

export async function playerDetail(id) {
  const [m, p] = await Promise.all([meta(), players()]);
  if (!p.byId.has(id)) return null;
  const shard = await getJSON(`data/players/${shardOf(id, m.n_shards)}.json`);
  return shard[id] || null;
}

export async function playerDetails(ids) {
  return Promise.all(ids.map((id) => playerDetail(id).catch(() => null)));
}

export async function tournamentDetail(id) {
  const t = await tournaments();
  const row = t.byId.get(id);
  if (!row || row.no_data) return row ? { ...row, teams: [], games: [], players: [] } : null;
  return getJSON(`data/tournaments/${encodeURIComponent(id)}.json`);
}

// ------------------------------------------------------------------ derived helpers

export function isActive(last, m) {
  if (!last || !m || !m.snapshot) return false;
  const cut = new Date(Date.parse(m.snapshot) - m.thresholds.active_days * 86400000).toISOString().slice(0, 10);
  return last >= cut;
}

/** Glicko expected score of A vs B, both deviations folded in (shown as a win probability). */
export function winProb(r1, rd1, r2, rd2) {
  const Q = 173.7178;
  const phi = Math.sqrt(rd1 * rd1 + rd2 * rd2) / Q;
  const g = 1 / Math.sqrt(1 + (3 * phi * phi) / (Math.PI * Math.PI));
  return 1 / (1 + Math.exp((-g * (r1 - r2)) / Q));
}

export function teamName(T, id) {
  const t = T.byId.get(id);
  return t ? t.name : id;
}
export function playerName(P, id) {
  const p = P.byId.get(id);
  return p ? p.name : id;
}

/** Search index across all entity types (built lazily on first query). */
let searchIndexP = null;
export function searchIndex() {
  if (!searchIndexP) {
    searchIndexP = Promise.all([teams(), players(), schools(), tournaments()]).then(([T, P, S, TR]) => {
      const norm = (x) => (x || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
      const items = [];
      for (const t of T.list) items.push({ type: "Teams", id: t.id, label: t.name, sub: t.r != null ? `${Math.round(t.r)}` : (t.composite ? "pickup" : "unrated"), key: norm(t.name + " " + (t.school_name || "")), weight: t.r || 0 });
      for (const p of P.list) items.push({ type: "Players", id: p.id, label: p.name, sub: p.school_name || "", key: norm(p.name + " " + (p.aliases || []).join(" ")), weight: p.r || 0 });
      for (const sc of S.list) items.push({ type: "Schools", id: sc.id, label: sc.name, sub: sc.state || "", key: norm(sc.name + " " + (sc.short || "") + " " + (sc.city || "")), weight: sc.best || 0 });
      const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const when = (d) => (d ? `${MONTHS[Number(d.slice(5, 7)) - 1]} ${d.slice(0, 4)}` : "");
      for (const tr of TR.list) items.push({ type: "Tournaments", id: tr.id, label: tr.name, sub: when(tr.date), key: norm(`${tr.name} ${tr.season} ${(tr.date || "").slice(0, 4)} ${tr.location || ""}`), weight: Date.parse(tr.date) / 1e9 });
      return { items, norm };
    }).catch((e) => { searchIndexP = null; throw e; });
  }
  return searchIndexP;
}

export async function search(q, { types = null, limitPerType = 6 } = {}) {
  const { items, norm } = await searchIndex();
  const terms = norm(q).split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const groups = new Map();
  for (const it of items) {
    if (types && !types.includes(it.type)) continue;
    if (!terms.every((t) => it.key.includes(t))) continue;
    const starts = it.key.startsWith(terms[0]) || it.key.includes(" " + terms[0]) ? 1 : 0;
    const g = groups.get(it.type) || [];
    g.push({ it, score: starts * 1e6 + it.weight });
    groups.set(it.type, g);
  }
  const order = ["Teams", "Players", "Schools", "Tournaments"];
  const out = [];
  for (const type of order) {
    const g = groups.get(type);
    if (!g) continue;
    g.sort((a, b) => b.score - a.score);
    for (const { it } of g.slice(0, limitPerType)) out.push(it);
  }
  return out;
}
