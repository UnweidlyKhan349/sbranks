// DOM helpers, formatting and shared widgets. All text goes in via text nodes, never innerHTML,
// because team/player/tournament names come from scraped spreadsheets.

const SVG_NS = "http://www.w3.org/2000/svg";

function setAttrs(el, attrs, isSvg) {
  if (!attrs) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.setAttribute("class", Array.isArray(v) ? v.filter(Boolean).join(" ") : v);
    else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) if (sv != null) el.style.setProperty(sk, sv);
    } else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else if (!isSvg && (k === "value" || k === "checked" || k === "selected" || k === "disabled") && k in el) el[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}

function append(el, kids) {
  for (const c of kids) {
    if (c == null || c === false || c === true) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}

/** h("a", {href, class}, "text", child, [more]) — children strings become text nodes. */
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs && (attrs instanceof Node || typeof attrs !== "object" || Array.isArray(attrs))) {
    kids.unshift(attrs);
    attrs = null;
  }
  setAttrs(el, attrs, false);
  append(el, kids);
  return el;
}

export function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  setAttrs(el, attrs, true);
  append(el, kids);
  return el;
}

export function escapeHTML(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function debounce(fn, ms = 150) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ------------------------------------------------------------------ icons (static, authored here)
const ICONS = {
  search: "M10.5 3a7.5 7.5 0 0 1 5.9 12.1l4.3 4.3-1.4 1.4-4.3-4.3A7.5 7.5 0 1 1 10.5 3zm0 2a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11z",
  trophy: "M7 3h10v2h3v3a4 4 0 0 1-4 4h-.3A5 5 0 0 1 13 14.9V17h3v2H8v-2h3v-2.1A5 5 0 0 1 8.3 12H8a4 4 0 0 1-4-4V5h3V3zm0 4H6v1a2 2 0 0 0 1.2 1.8A5 5 0 0 1 7 9V7zm10 0v2c0 .3 0 .5-.1.8A2 2 0 0 0 18 8V7h-1z",
  bolt: "M13 2 4 14h6l-1 8 9-12h-6l1-8z",
  check: "M9.5 16.2 5.3 12l-1.4 1.4 5.6 5.6L20.1 8.4 18.7 7z",
  minus: "M5 11h14v2H5z",
  sun: "M12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10zm0-5h0a1 1 0 0 1 1 1v1a1 1 0 0 1-2 0V3a1 1 0 0 1 1-1zm0 18a1 1 0 0 1 1 1v0a1 1 0 0 1-2 0 1 1 0 0 1 1-1zM3 11h1a1 1 0 0 1 0 2H3a1 1 0 0 1 0-2zm17 0h1a1 1 0 0 1 0 2h-1a1 1 0 0 1 0-2zM5.6 4.2l.7.7a1 1 0 0 1-1.4 1.4l-.7-.7a1 1 0 0 1 1.4-1.4zm12.7 12.7.7.7a1 1 0 0 1-1.4 1.4l-.7-.7a1 1 0 0 1 1.4-1.4zM19.8 5.6l-.7.7a1 1 0 0 1-1.4-1.4l.7-.7a1 1 0 0 1 1.4 1.4zM6.3 18.3l-.7.7a1 1 0 0 1-1.4-1.4l.7-.7a1 1 0 0 1 1.4 1.4z",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
  external: "M14 3h7v7h-2V6.4l-8.3 8.3-1.4-1.4L17.6 5H14V3zM5 5h6v2H6v11h11v-5h2v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  info: "M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm0 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm-1 7h2v6h-2v-6zm0-4h2v2h-2V7z",
  tri: "M12 4 22 20H2z",
  caret: "M7 10l5 5 5-5z",
  download: "M11 4h2v8.6l3.3-3.3 1.4 1.4L12 16.4l-5.7-5.7 1.4-1.4 3.3 3.3V4zM5 18h14v2H5z",
};

export function icon(name, cls) {
  return s("svg", { viewBox: "0 0 24 24", class: cls || "icon", "aria-hidden": "true", focusable: "false" },
    s("path", { d: ICONS[name], fill: "currentColor" }));
}

// ------------------------------------------------------------------ formatting
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function parseDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, (m || 1) - 1, d || 1);
}

export const fmt = {
  r(x) { return x == null || Number.isNaN(x) ? "–" : String(Math.round(x)); },
  pm(x) { return x == null ? "" : `±${Math.round(x)}`; },
  int(x) { return x == null ? "–" : Math.round(x).toLocaleString("en-US"); },
  num(x, d = 1) { return x == null || Number.isNaN(x) ? "–" : Number(x).toFixed(d); },
  pct(p, d = 0) { return p == null ? "–" : `${(p * 100).toFixed(d)}%`; },
  signed(x, d = 0) {
    if (x == null) return "–";
    const v = Number(x.toFixed(d));
    return (v > 0 ? "+" : v < 0 ? "−" : "±") + Math.abs(v).toFixed(d);
  },
  date(iso) {
    if (!iso) return "–";
    const [y, m, d] = iso.split("-").map(Number);
    return `${MONTHS[m - 1]} ${d}, ${y}`;
  },
  dateShort(iso) {
    if (!iso) return "–";
    const [y, m, d] = iso.split("-").map(Number);
    return `${MONTHS[m - 1]} ${d} ’${String(y).slice(2)}`;
  },
  monthYear(ms) {
    const d = new Date(ms);
    return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  },
  range(a, b) {
    if (!a) return "–";
    if (!b || a === b) return fmt.date(a);
    const [y1, m1, d1] = a.split("-").map(Number);
    const [y2, m2, d2] = b.split("-").map(Number);
    if (y1 === y2 && m1 === m2) return `${MONTHS[m1 - 1]} ${d1}–${d2}, ${y1}`;
    if (y1 === y2) return `${MONTHS[m1 - 1]} ${d1} – ${MONTHS[m2 - 1]} ${d2}, ${y1}`;
    return `${fmt.date(a)} – ${fmt.date(b)}`;
  },
  record(w, l, t) { return t ? `${w}–${l}–${t}` : `${w}–${l}`; },
  plural(n, one, many) { return `${fmt.int(n)} ${n === 1 ? one : many || one + "s"}`; },
  /** ["2020-21", …, "2026-27"] -> "2020-21 – 2026-27" */
  seasons(list) {
    const xs = [...new Set(list || [])].sort();
    if (!xs.length) return "–";
    return xs.length === 1 ? xs[0] : `${xs[0]} – ${xs[xs.length - 1]}`;
  },
};

// ------------------------------------------------------------------ subjects
export const SUBJECTS = [
  { key: "math", label: "Math", short: "Math" },
  { key: "physics", label: "Physics", short: "Phys" },
  { key: "chemistry", label: "Chemistry", short: "Chem" },
  { key: "biology", label: "Biology", short: "Bio" },
  { key: "ess", label: "Earth & Space", short: "ESS" },
  { key: "energy", label: "Energy", short: "Energy" },
];
export const SUBJECT_BY_KEY = Object.fromEntries(SUBJECTS.map((x) => [x.key, x]));
export const subjColor = (key) => `var(--c-${key})`;
export function subjLabel(key, short) {
  if (key === "overall") return "Overall";
  const x = SUBJECT_BY_KEY[key];
  return x ? (short ? x.short : x.label) : key;
}
export function subjTag(key, short) {
  if (!key) return h("span", { class: "muted" }, "–");
  return h("span", { class: "subj-label" }, h("span", { class: "swatch", style: { background: subjColor(key) }, "aria-hidden": "true" }), subjLabel(key, short));
}

// ------------------------------------------------------------------ small components
export function ratingCell(r, pm, { provisional = false } = {}) {
  if (r == null) return h("span", { class: "muted" }, "–");
  return h("span", { class: "nowrap" }, fmt.r(r), pm != null ? h("span", { class: "pm-val" }, fmt.pm(pm)) : null,
    provisional ? h("span", { class: "tag-prov", title: "Provisional: not enough data to be ranked" }, "prov") : null);
}

export function delta(x) {
  if (x == null) return h("span", { class: "muted" }, "–");
  const cls = x > 0.5 ? "up" : x < -0.5 ? "down" : "flat";
  return h("span", { class: `delta ${cls}` }, cls === "flat" ? null : icon("tri"), fmt.signed(x));
}

export function resultBadge(r) {
  const label = r === "W" ? "Win" : r === "L" ? "Loss" : "Tie";
  return h("span", { class: `res ${r}`, title: label, "aria-label": label }, r);
}

export function champBadge(text = "Champion") {
  return h("span", { class: "badge champ" }, icon("trophy"), text);
}
export function upsetBadge() {
  return h("span", { class: "badge upset", title: "The loser had at least a 70% pre-game win probability" }, icon("bolt"), "Upset");
}
export function badge(text, kind) {
  return h("span", { class: `badge ${kind || ""}` }, text);
}
export function coverageBadge(on, text, { bare = false } = {}) {
  return h("span", { class: `badge ${on ? "ok" : "off"}`, title: `${text}: ${on ? "available" : "not available"}` },
    bare ? null : icon(on ? "check" : "minus"), text);
}

export function extLink(url, text) {
  return h("a", { href: url, target: "_blank", rel: "noopener noreferrer", class: "ext" }, text, icon("external"), h("span", { class: "sr-only" }, " (opens in a new tab)"));
}

export function tile(label, value, sub) {
  return h("div", { class: "tile" }, h("div", { class: "tile-label" }, label), h("div", { class: "tile-value" }, value), sub ? h("div", { class: "tile-sub" }, sub) : null);
}

export function section(title, sub, ...content) {
  return h("section", { class: "section" },
    h("div", { class: "section-head" }, h("h2", null, title), sub ? (sub instanceof Node ? sub : h("p", null, sub)) : null),
    ...content);
}

export function notice(text, iconName = "info") {
  return h("div", { class: "notice" }, icon(iconName), h("div", null, text));
}

export function loadingState(text = "Loading…") {
  return h("div", { class: "state state-loading", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), text);
}

export function emptyState(text) {
  return h("div", { class: "empty" }, text);
}

export function errorState(err) {
  return h("div", { class: "state", role: "alert" },
    h("h1", null, "Something went wrong"),
    h("p", null, "The data for this page could not be loaded. Try reloading the page."),
    h("p", { class: "muted" }, String(err && err.message ? err.message : err)));
}

export function notFound(kind, id) {
  return h("div", { class: "state" },
    h("h1", null, `${kind} not found`),
    h("p", null, id ? `There is no ${kind.toLowerCase()} with the id “${id}”. It may have been renamed or merged with another entry.` : "This page does not exist."),
    h("p", null, h("a", { href: "#/" }, "Go to the home page"), " · ", h("a", { href: "#/teams" }, "Browse teams"), " · ", h("a", { href: "#/players" }, "Browse players")));
}

export function pageHead({ eyebrow, title, sub }) {
  return h("header", { class: "page-head" },
    eyebrow ? h("div", { class: "eyebrow" }, eyebrow) : null,
    h("h1", null, title),
    // each item of an array sub-line is its own flex item (bare strings would merge into one)
    sub ? h("div", { class: "page-sub" }, Array.isArray(sub) ? sub.filter((x) => x != null && x !== false).map((x) => (x instanceof Node ? x : h("span", null, x))) : sub) : null);
}

// ------------------------------------------------------------------ hrefs
const enc = encodeURIComponent;
export const href = {
  team: (id) => `#/team/${enc(id)}`,
  player: (id) => `#/player/${enc(id)}`,
  school: (id) => `#/school/${enc(id)}`,
  tournament: (id) => `#/tournament/${enc(id)}`,
};

// ------------------------------------------------------------------ tabs
let tabSeq = 0;
/** Tab strip; onSelect(key). Arrow keys move between tabs. `panel` (optional) is the element the tabs
 *  control: it becomes the tabpanel, labelled by the selected tab. */
export function tabs(items, selected, onSelect, label = "Subject", panel = null) {
  const uid = `tabs${++tabSeq}`;
  const list = h("div", { class: "tablist", role: "tablist", "aria-label": label });
  if (panel) {
    panel.id = panel.id || `${uid}-panel`;
    panel.setAttribute("role", "tabpanel");
  }
  const buttons = items.map((it) => {
    const b = h("button", {
      type: "button", class: "tab", role: "tab", id: `${uid}-${it.key}`, "aria-selected": String(it.key === selected), tabindex: it.key === selected ? "0" : "-1",
      "aria-controls": panel ? panel.id : null,
      onclick: () => select(it.key, true),
    }, it.swatch ? h("span", { class: "swatch", style: { background: it.swatch }, "aria-hidden": "true" }) : null, it.label);
    b.dataset.key = it.key;
    return b;
  });
  function select(key, fire) {
    for (const b of buttons) {
      const on = b.dataset.key === key;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && panel) panel.setAttribute("aria-labelledby", b.id);
    }
    if (fire) onSelect(key);
  }
  select(selected, false);
  list.addEventListener("keydown", (e) => {
    const i = buttons.indexOf(document.activeElement);
    if (i < 0) return;
    let j = null;
    if (e.key === "ArrowRight") j = (i + 1) % buttons.length;
    else if (e.key === "ArrowLeft") j = (i - 1 + buttons.length) % buttons.length;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = buttons.length - 1;
    if (j != null) {
      e.preventDefault();
      buttons[j].focus();
      select(buttons[j].dataset.key, true);
    }
  });
  append(list, buttons);
  return list;
}

export function subjectTabItems(withOverall = true) {
  const items = SUBJECTS.map((x) => ({ key: x.key, label: x.label, swatch: subjColor(x.key) }));
  return withOverall ? [{ key: "overall", label: "Overall" }, ...items] : items;
}

// ------------------------------------------------------------------ sortable table
/**
 * columns: [{key, label, title?, num?, cls?, sort?: row => value, tie?: row => value (ascending tie-break),
 *            render: (row, i) => Node|string, sortable?: true, defaultDir?: 'desc'|'asc'}]
 * opts: {rows, sort: {key, dir}, pageSize, caption, empty, rowClass, onSort, wrapClass}
 */
const collator = new Intl.Collator("en", { sensitivity: "base", numeric: true });

export function dataTable(columns, rows, opts = {}) {
  const pageSize = opts.pageSize || Infinity;
  let shown = Math.min(pageSize, rows.length);
  let sort = opts.sort ? { ...opts.sort } : null;
  let data = rows.slice();

  const table = h("table", { class: ["tbl", opts.tableClass] });
  if (opts.caption) table.appendChild(h("caption", { class: opts.captionHidden ? "sr-only" : null }, opts.caption));
  const thead = h("thead");
  const trh = h("tr");
  const ths = columns.map((c) => {
    const th = h("th", { scope: "col", class: [c.num ? "num" : null, c.thCls, c.hideSm ? "hide-sm" : null], title: c.title || null });
    if (c.sort && opts.sortable !== false) {
      th.appendChild(h("button", { type: "button", class: "sort-btn", onclick: () => toggleSort(c) },
        c.label, s("svg", { class: "sort-ind", viewBox: "0 0 10 10", "aria-hidden": "true" }, s("path", { d: "M1 3h8L5 8z", fill: "currentColor" }))));
    } else th.appendChild(typeof c.label === "string" ? document.createTextNode(c.label) : c.label);
    return th;
  });
  append(trh, ths);
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = h("tbody");
  table.appendChild(tbody);
  const wrap = h("div", { class: ["table-wrap", opts.wrapClass] }, table);
  const more = h("div", { class: "more-row" });
  const root = h("div", { class: "dt" }, wrap, more);

  function cmp(c, dir) {
    const m = dir === "asc" ? 1 : -1;
    const base = (f, mult) => (a, b) => {
      const va = f(a), vb = f(b);
      const na = va == null || Number.isNaN(va), nb = vb == null || Number.isNaN(vb);
      if (na && nb) return 0;
      if (na) return 1; // nulls always last
      if (nb) return -1;
      if (typeof va === "string") return mult * collator.compare(va, vb);
      return mult * (va - vb);
    };
    const primary = base(c.sort, m);
    // optional tie-break (always ascending, e.g. rank for equal rounded ratings)
    const tie = c.tie ? base(c.tie, 1) : null;
    return tie ? (a, b) => primary(a, b) || tie(a, b) : primary;
  }
  function applySort() {
    ths.forEach((th, i) => {
      if (sort && columns[i].key === sort.key) th.setAttribute("aria-sort", sort.dir === "asc" ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
    if (!sort) return;
    const c = columns.find((x) => x.key === sort.key);
    if (c && c.sort) data.sort(cmp(c, sort.dir));
  }
  function toggleSort(c) {
    if (sort && sort.key === c.key) sort.dir = sort.dir === "asc" ? "desc" : "asc";
    else sort = { key: c.key, dir: c.defaultDir || (c.num ? "desc" : "asc") };
    // a new order starts again from the top (bounded re-render on big tables)
    if (shown > SHOW_ALL_MAX) shown = Math.min(pageSize, rows.length);
    data = rows.slice();
    applySort();
    renderBody();
    if (opts.onSort) opts.onSort(sort);
  }
  // Rows render in pages: "Show more" appends only the new rows, and "Show all" is offered only for
  // tables small enough to lay out at once (thousands of rows block the page for about a second).
  const SHOW_ALL_MAX = 1000;
  let rendered = 0;
  function rowEl(row, i) {
    const tr = h("tr", { class: opts.rowClass ? opts.rowClass(row) : null });
    for (const c of columns) {
      const v = c.render ? c.render(row, i) : row[c.key];
      const td = h(c.th ? "th" : "td", { class: [c.num ? "num" : null, c.cls, c.hideSm ? "hide-sm" : null], scope: c.th ? "row" : null });
      append(td, [v]);
      tr.appendChild(td);
    }
    return tr;
  }
  function renderBody(appendOnly = false) {
    if (!appendOnly) {
      clear(tbody);
      rendered = 0;
      if (!data.length) {
        tbody.appendChild(h("tr", null, h("td", { colspan: columns.length, class: "empty" }, opts.empty || "Nothing to show.")));
      }
    }
    const frag = document.createDocumentFragment();
    const firstNew = rendered;
    const end = Math.min(shown, data.length);
    for (let i = rendered; i < end; i++) frag.appendChild(rowEl(data[i], i));
    rendered = Math.max(rendered, end);
    tbody.appendChild(frag);
    // keep keyboard focus in the "more" row when its button is replaced
    const hadFocus = more.contains(document.activeElement);
    clear(more);
    if (data.length > shown) {
      more.appendChild(document.createTextNode(`Showing ${fmt.int(shown)} of ${fmt.int(data.length)}`));
      const btn = h("button", { type: "button", class: "btn", onclick: () => { shown = Math.min(data.length, shown + pageSize); renderBody(true); } },
        `Show ${fmt.int(Math.min(pageSize, data.length - shown))} more`);
      more.appendChild(btn);
      if (data.length - shown > pageSize && data.length <= SHOW_ALL_MAX) {
        more.appendChild(h("button", { type: "button", class: "btn-link", onclick: () => { shown = data.length; renderBody(true); } }, "Show all"));
      }
      if (hadFocus) btn.focus();
    } else if (data.length > 20 && pageSize !== Infinity) {
      more.appendChild(document.createTextNode(`${fmt.int(data.length)} rows`));
    }
    if (hadFocus && !more.contains(document.activeElement)) {
      // the last page was shown and its button is gone: continue at the first newly added row
      const link = tbody.rows[firstNew] && tbody.rows[firstNew].querySelector("a, button");
      if (link) link.focus();
    }
    if (!more.childNodes.length) more.hidden = true; else more.hidden = false;
  }
  applySort();
  renderBody();
  root.table = table;
  return root;
}

// ------------------------------------------------------------------ CSV download
export function csvButton(filename, header, rowsFn) {
  return h("button", {
    type: "button", class: "btn", onclick: () => {
      const q = (v) => {
        const str = v == null ? "" : String(v);
        return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
      };
      const lines = [header.map(q).join(","), ...rowsFn().map((r) => r.map(q).join(","))];
      const blob = new Blob([lines.join("\n")], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = h("a", { href: url, download: filename });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  }, icon("download"), "CSV");
}

// ------------------------------------------------------------------ combobox
let comboSeq = 0;
/**
 * Accessible combobox (ARIA 1.2 pattern). search(q) -> [{group?, label, sub?, value}] (sync or async).
 * onPick(item). Returns {el, input, setValue(label)}.
 */
export function combobox({ placeholder, label, search, onPick, minChars = 1, cls, value = "" }) {
  const id = `cb${++comboSeq}`;
  const input = h("input", {
    class: "combo-input", type: "search", role: "combobox", "aria-autocomplete": "list", "aria-expanded": "false",
    "aria-controls": `${id}-list`, autocomplete: "off", spellcheck: "false", placeholder, "aria-label": label || placeholder, value,
  });
  const list = h("ul", { class: "combo-list", id: `${id}-list`, role: "listbox", "aria-label": label || placeholder, hidden: true });
  const el = h("div", { class: ["combo", cls] }, icon("search", "combo-icon"), input, list);
  let items = [];
  let active = -1;
  let seq = 0;
  let shownQ = null; // the query the visible options belong to

  function close() {
    clearTimeout(timer);
    seq++; // drop any search still pending or in flight
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }
  function setActive(i) {
    const opts = list.querySelectorAll('[role="option"]');
    opts.forEach((o, j) => o.setAttribute("aria-selected", String(j === i)));
    active = i;
    if (i >= 0 && opts[i]) {
      input.setAttribute("aria-activedescendant", opts[i].id);
      opts[i].scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  }
  function pick(i) {
    const it = items[i];
    if (!it) return;
    close();
    onPick(it, input);
  }
  async function update() {
    const q = input.value.trim();
    const my = ++seq;
    if (q.length < minChars) { close(); return; }
    let res;
    try {
      res = search(q);
      if (res && typeof res.then === "function") res = await res;
    } catch (err) {
      if (my !== seq) return;
      console.warn(err);
      items = [];
      shownQ = null;
      clear(list).appendChild(h("li", { class: "combo-empty", role: "presentation" }, "Search is unavailable right now"));
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      setActive(-1);
      return;
    }
    if (my !== seq) return;
    items = res || [];
    shownQ = q;
    clear(list);
    if (!items.length) {
      list.appendChild(h("li", { class: "combo-empty", role: "presentation" }, "No matches"));
    } else {
      let lastGroup = null;
      items.forEach((it, i) => {
        if (it.group && it.group !== lastGroup) {
          list.appendChild(h("li", { class: "combo-group", role: "presentation" }, it.group));
          lastGroup = it.group;
        }
        const li = h("li", { class: "combo-opt", role: "option", id: `${id}-o${i}`, "aria-selected": "false" },
          h("span", { class: "opt-label" }, it.label), it.sub ? h("span", { class: "opt-sub" }, it.sub) : null);
        li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(i); });
        list.appendChild(li);
      });
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    setActive(items.length ? 0 : -1);
  }
  let timer = 0;
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(update, 80); });
  input.addEventListener("focus", () => { if (input.value.trim().length >= minChars) update(); });
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (list.hidden) { update(); return; }
      if (items.length) setActive((active + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (items.length) setActive((active - 1 + items.length) % items.length);
    } else if (e.key === "Enter") {
      const q = input.value.trim();
      if (q.length >= minChars && q !== shownQ) {
        // typed faster than the debounce: search now, then take the best match
        e.preventDefault();
        clearTimeout(timer);
        update().then(() => { if (shownQ === q && items.length) pick(0); });
      } else if (!list.hidden && active >= 0) { e.preventDefault(); pick(active); }
    } else if (e.key === "Escape") {
      if (!list.hidden) { e.preventDefault(); close(); } else input.value = "";
    }
  });
  return { el, input, setValue(v) { input.value = v; }, close };
}

// ------------------------------------------------------------------ query string helpers
export function setQuery(path, params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "" && v !== false) q.set(k, v === true ? "1" : v);
  const qs = q.toString();
  const url = `#${path}${qs ? "?" + qs : ""}`;
  if (location.hash !== url) history.replaceState(history.state, "", url);
}

export function boolParam(query, key, dflt) {
  if (!query.has(key)) return dflt;
  const v = query.get(key);
  return v === "1" || v === "true";
}
