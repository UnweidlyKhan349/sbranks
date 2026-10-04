// Hand-rolled SVG charts: line chart with uncertainty band + crosshair, bar charts anchored on a
// reference value (1500), sparklines, and the shared floating tooltip. Every chart ships a
// "Show table" twin, keyboard access to the same readout as hover, and redraws on resize.

import { h, s, clear, fmt, dataTable } from "./ui.js";

// ------------------------------------------------------------------ tooltip (one per page)
function tipNode() { return document.getElementById("tip"); }

export function tipContent({ title, sub, rows = [] }) {
  return h("div", null,
    title ? h("div", { class: "tip-title" }, title) : null,
    sub ? h("div", { class: "tip-sub" }, sub) : null,
    rows.map((r) => h("div", { class: "tip-row" },
      r.color ? h("span", { class: r.kind === "rect" ? "swatch" : "line-key", style: { background: r.color } }) : null,
      h("span", { class: "tip-val" }, r.value),
      r.label ? h("span", { class: "tip-lab" }, r.label) : null)));
}

// A tooltip opened by keyboard focus is anchored to the focused element: page scrolls (e.g. the
// browser scrolling the element into view) move it along instead of closing it.
let tipAnchor = null;

function placeTip(t, x, y) {
  const pad = 14;
  const r = t.getBoundingClientRect();
  let left = x + pad;
  let top = y + pad;
  if (left + r.width > window.innerWidth - 8) left = x - pad - r.width;
  if (left < 8) left = 8;
  if (top + r.height > window.innerHeight - 8) top = y - pad - r.height;
  if (top < 8) top = 8;
  t.style.left = `${Math.round(left)}px`;
  t.style.top = `${Math.round(top)}px`;
}

/** anchor: {el, pos: () => ({x, y})} for keyboard-opened tips; omit for pointer tips. */
export function showTip(content, x, y, anchor = null) {
  const t = tipNode();
  if (!t) return;
  clear(t);
  t.appendChild(content);
  t.hidden = false;
  tipAnchor = anchor;
  placeTip(t, x, y);
}

export function hideTip() {
  const t = tipNode();
  tipAnchor = null;
  if (t) t.hidden = true;
}

/** Scroll handler: keep a focus-anchored tip next to its element, hide pointer tips. */
export function onScrollTip() {
  const t = tipNode();
  if (!t || t.hidden) return;
  if (tipAnchor && document.activeElement === tipAnchor.el) {
    const { x, y } = tipAnchor.pos();
    placeTip(t, x, y);
  } else hideTip();
}

/** Attach the floating tooltip to an HTML element (hover + keyboard focus). */
export function attachTip(el, contentFn) {
  el.addEventListener("pointerenter", (e) => showTip(contentFn(), e.clientX, e.clientY));
  el.addEventListener("pointermove", (e) => showTip(contentFn(), e.clientX, e.clientY));
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => {
    const pos = () => { const r = el.getBoundingClientRect(); return { x: r.right, y: r.top }; };
    const { x, y } = pos();
    showTip(contentFn(), x, y, { el, pos });
  });
  el.addEventListener("blur", hideTip);
}

// ------------------------------------------------------------------ scales + ticks
function linear(d0, d1, r0, r1) {
  const span = d1 - d0 || 1;
  const f = (x) => r0 + ((x - d0) / span) * (r1 - r0);
  f.invert = (y) => d0 + ((y - r0) / (r1 - r0 || 1)) * span;
  return f;
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
}

export function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 50; max += 50; }
  const step = niceStep((max - min) / Math.max(1, count));
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { ticks, lo, hi };
}

const DAY = 86400000;
function timeTicks(min, max, maxTicks) {
  const d0 = new Date(min);
  const out = (months) => {
    const res = [];
    let y = d0.getUTCFullYear();
    let m = Math.ceil(d0.getUTCMonth() / months) * months;
    if (Date.UTC(y, m, 1) < min) m += months;
    for (let i = 0; i < 400; i++) {
      const t = Date.UTC(y, m, 1);
      if (t > max) break;
      if (t >= min) res.push(t);
      m += months;
    }
    return res;
  };
  for (const months of [1, 2, 3, 6, 12, 24]) {
    const t = out(months);
    if (t.length <= maxTicks) {
      return { ticks: t, label: (ms) => (months >= 12 ? String(new Date(ms).getUTCFullYear()) : fmt.monthYear(ms).replace(/ (\d\d)(\d\d)$/, " ’$2")) };
    }
  }
  return { ticks: [], label: () => "" };
}

/** Calls draw(width) whenever the element's width changes (and once when it first lays out). */
function onResize(el, draw) {
  let lastW = -1;
  let raf = 0;
  const run = () => {
    raf = 0;
    const w = Math.floor(el.clientWidth);
    if (w > 0 && w !== lastW) { lastW = w; draw(w); }
  };
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(() => { if (!raf) raf = requestAnimationFrame(run); });
    ro.observe(el);
  } else {
    window.addEventListener("resize", () => { if (!raf) raf = requestAnimationFrame(run); });
    requestAnimationFrame(run);
  }
}

function textWidth(str, size = 12) { return String(str).length * size * 0.58; }

export function tableView(columns, rows, { summary = "Show table", caption } = {}) {
  const d = h("details", { class: "table-view" }, h("summary", null, summary));
  let built = false;
  d.addEventListener("toggle", () => {
    if (d.open && !built) {
      built = true;
      d.appendChild(dataTable(columns, rows, { caption, captionHidden: true, sortable: false }));
    }
  });
  return d;
}

function legend(items) {
  return h("ul", { class: "legend" }, items.map((it) =>
    h("li", null, h("span", { class: it.kind === "rect" ? "swatch" : "line-key", style: { background: it.color }, "aria-hidden": "true" }), it.label)));
}

// ------------------------------------------------------------------ line chart
/**
 * series: [{id, label, color, points: [{x: ms, y, lo?, hi?, ...}], band?: bool}]
 * opts: {height, yFormat, label (aria), refY, refLabel, tip(x, hits) -> {title, sub, rows}, table: {columns, rows},
 *        endLabels (default: 2..4 series), legend (default: >= 2 series)}
 */
export function lineChart(series, opts = {}) {
  const height = opts.height || 260;
  const yFormat = opts.yFormat || fmt.r;
  const fig = h("figure", { class: "chart" });
  const visible = series.filter((x) => x.points.length);
  const showLegend = opts.legend ?? visible.length >= 2;
  if (showLegend) fig.appendChild(legend(visible.map((x) => ({ label: x.label, color: x.color }))));
  const plot = h("div", { class: "chart-plot", style: { "min-height": `${height}px` } });
  const live = h("div", { class: "sr-only", "aria-live": "polite" });
  fig.append(plot, live);
  if (!visible.length) {
    plot.appendChild(h("div", { class: "empty" }, opts.empty || "No rating history yet."));
    plot.style.minHeight = "0";
    return fig;
  }
  if (opts.table) fig.appendChild(tableView(opts.table.columns, opts.table.rows, { caption: opts.label }));

  const xs = [...new Set(visible.flatMap((sr) => sr.points.map((p) => p.x)))].sort((a, b) => a - b);
  const hitsAt = (x) => visible.map((sr) => {
    let pt = null;
    for (const p of sr.points) { if (p.x <= x) pt = p; else break; }
    return pt ? { series: sr, point: pt, exact: pt.x === x } : null;
  }).filter(Boolean);
  const defaultTip = (x, hits) => ({
    title: fmt.date(new Date(x).toISOString().slice(0, 10)),
    rows: hits.map((hh) => ({ color: hh.series.color, value: yFormat(hh.point.y), label: hh.series.label })),
  });
  const tipFn = opts.tip || defaultTip;

  function draw(W) {
    clear(plot);
    const endLabels = (opts.endLabels ?? (visible.length >= 2 && visible.length <= 4));
    const m = { t: 14, r: 14, b: 28, l: 46 };
    if (endLabels) m.r = Math.min(130, 16 + Math.max(...visible.map((x) => textWidth(x.label, 12))));
    const iw = Math.max(40, W - m.l - m.r);
    const ih = height - m.t - m.b;
    let x0 = xs[0], x1 = xs[xs.length - 1];
    if (x1 - x0 < 60 * DAY) { const mid = (x0 + x1) / 2; x0 = mid - 45 * DAY; x1 = mid + 45 * DAY; }
    const padX = (x1 - x0) * 0.04;
    x0 -= padX; x1 += padX;
    let ymin = Infinity, ymax = -Infinity;
    for (const sr of visible) for (const p of sr.points) {
      ymin = Math.min(ymin, sr.band && p.lo != null ? p.lo : p.y);
      ymax = Math.max(ymax, sr.band && p.hi != null ? p.hi : p.y);
    }
    if (opts.refY != null) { ymin = Math.min(ymin, opts.refY); ymax = Math.max(ymax, opts.refY); }
    const yt = niceTicks(ymin, ymax, Math.max(3, Math.round(ih / 48)));
    const sx = linear(x0, x1, m.l, m.l + iw);
    const sy = linear(yt.lo, yt.hi, m.t + ih, m.t);

    const svgEl = s("svg", {
      width: W, height, viewBox: `0 0 ${W} ${height}`, tabindex: "0", role: "group",
      "aria-label": `${opts.label || "Line chart"}. Use the left and right arrow keys to step through the points.`,
    });
    // grid + y ticks
    for (const v of yt.ticks) {
      const y = Math.round(sy(v)) + 0.5;
      svgEl.appendChild(s("line", { class: "grid-line", x1: m.l, x2: m.l + iw, y1: y, y2: y }));
      svgEl.appendChild(s("text", { class: "ax-tick", x: m.l - 8, y: y + 4, "text-anchor": "end" }, yFormat(v)));
    }
    let refText = null;
    if (opts.refY != null) {
      const y = Math.round(sy(opts.refY)) + 0.5;
      svgEl.appendChild(s("line", { class: "ref-line", x1: m.l, x2: m.l + iw, y1: y, y2: y }));
      if (opts.refLabel) {
        // put the label at whichever end of the reference line the data leaves free (above, else below)
        const lw = textWidth(opts.refLabel, 11);
        const hitsBox = (bx0, bx1, by0, by1) => {
          let n = 0;
          for (const sr of visible) {
            const P = sr.points.map((p) => [sx(p.x), sy(p.y)]);
            for (let x = bx0; x <= bx1; x += 3) {
              for (let i = 0; i < P.length; i++) {
                const [xa, ya] = P[i];
                const [xb, yb] = P[Math.min(i + 1, P.length - 1)];
                let yy = null;
                if (Math.abs(xa - x) <= 5) yy = ya;
                else if (i + 1 < P.length && xa <= x && x <= xb) yy = ya + ((x - xa) / (xb - xa || 1)) * (yb - ya);
                if (yy != null && yy >= by0 - 5 && yy <= by1 + 5) n++;
              }
            }
          }
          return n;
        };
        const cands = [
          { x: m.l + 4, anchor: "start", ty: y - 4 }, { x: m.l + iw - 4, anchor: "end", ty: y - 4 },
          { x: m.l + 4, anchor: "start", ty: y + 13 }, { x: m.l + iw - 4, anchor: "end", ty: y + 13 },
        ].filter((c) => c.ty + 2 < m.t + ih || c.ty < y);
        let best = cands[0], bestN = Infinity;
        for (const c of cands) {
          const bx0 = c.anchor === "start" ? c.x : c.x - lw;
          const n = hitsBox(bx0, bx0 + lw, c.ty - 10, c.ty + 2);
          if (n < bestN) { best = c; bestN = n; }
          if (!n) break;
        }
        // appended after the series (below), so its halo keeps it legible where a line still crosses
        refText = s("text", { class: "ref-label", x: best.x, y: best.ty, "text-anchor": best.anchor }, opts.refLabel);
      }
    }
    // x axis
    const xb = Math.round(m.t + ih) + 0.5;
    svgEl.appendChild(s("line", { class: "ax-line", x1: m.l, x2: m.l + iw, y1: xb, y2: xb }));
    const tt = timeTicks(x0, x1, Math.max(2, Math.floor(iw / 78)));
    for (const t of tt.ticks) {
      const x = Math.round(sx(t)) + 0.5;
      svgEl.appendChild(s("line", { class: "ax-line", x1: x, x2: x, y1: xb, y2: xb + 4 }));
      svgEl.appendChild(s("text", { class: "ax-tick", x, y: xb + 17, "text-anchor": "middle" }, tt.label(t)));
    }
    // bands, then lines, then dots
    for (const sr of visible) {
      if (!sr.band) continue;
      const pts = sr.points.filter((p) => p.lo != null && p.hi != null);
      if (!pts.length) continue;
      if (pts.length === 1) {
        const p = pts[0];
        svgEl.appendChild(s("rect", { class: "series-band", x: sx(p.x) - 6, width: 12, y: sy(p.hi), height: Math.max(1, sy(p.lo) - sy(p.hi)), rx: 3, style: `fill:${sr.color}` }));
        continue;
      }
      const top = pts.map((p) => `${sx(p.x).toFixed(1)},${sy(p.hi).toFixed(1)}`);
      const bot = pts.slice().reverse().map((p) => `${sx(p.x).toFixed(1)},${sy(p.lo).toFixed(1)}`);
      svgEl.appendChild(s("path", { class: "series-band", d: `M${top.join("L")}L${bot.join("L")}Z`, style: `fill:${sr.color}` }));
    }
    for (const sr of visible) {
      if (sr.points.length < 2) continue;
      const d = "M" + sr.points.map((p) => `${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("L");
      svgEl.appendChild(s("path", { class: "series-line", d, style: `stroke:${sr.color}` }));
    }
    const dotsAll = visible.length === 1 || visible.every((sr) => sr.points.length <= 40);
    for (const sr of visible) {
      const pts = dotsAll ? sr.points : sr.points.slice(-1);
      for (const p of pts) svgEl.appendChild(s("circle", { class: "series-dot", cx: sx(p.x), cy: sy(p.y), r: 4, style: `fill:${sr.color}` }));
    }
    if (refText) svgEl.appendChild(refText);
    // direct end labels (only when they don't collide)
    if (endLabels) {
      const labs = visible.map((sr) => ({ sr, y: sy(sr.points[sr.points.length - 1].y) })).sort((a, b) => a.y - b.y);
      const collide = labs.some((l, i) => i > 0 && l.y - labs[i - 1].y < 14);
      if (!collide) {
        for (const l of labs) svgEl.appendChild(s("text", { class: "end-label", x: m.l + iw + 8, y: l.y + 4 }, l.sr.label));
      }
    }
    // hover layer
    const cross = s("line", { class: "crosshair", y1: m.t, y2: m.t + ih, visibility: "hidden" });
    const focusDots = s("g", { visibility: "hidden" });
    svgEl.appendChild(cross);
    svgEl.appendChild(focusDots);
    const overlay = s("rect", { x: m.l - 10, y: 0, width: iw + 20, height, fill: "transparent" });
    svgEl.appendChild(overlay);
    let idx = -1;
    function showAt(i, clientX, clientY) {
      idx = Math.max(0, Math.min(xs.length - 1, i));
      const x = xs[idx];
      const px = Math.round(sx(x)) + 0.5;
      cross.setAttribute("x1", px);
      cross.setAttribute("x2", px);
      cross.setAttribute("visibility", "visible");
      clear(focusDots);
      const hits = hitsAt(x);
      for (const hh of hits) {
        focusDots.appendChild(s("circle", { class: "series-dot", cx: sx(hh.point.x), cy: sy(hh.point.y), r: 5.5, style: `fill:${hh.series.color}` }));
      }
      focusDots.setAttribute("visibility", "visible");
      const content = tipContent(tipFn(x, hits));
      let anchor = null;
      if (clientX == null) {
        const pos = () => { const r = svgEl.getBoundingClientRect(); return { x: r.left + px, y: r.top + m.t + 8 }; };
        ({ x: clientX, y: clientY } = pos());
        anchor = { el: svgEl, pos };
      }
      showTip(content, clientX, clientY, anchor);
      live.textContent = content.textContent;
    }
    function hide() {
      cross.setAttribute("visibility", "hidden");
      focusDots.setAttribute("visibility", "hidden");
      hideTip();
    }
    function nearest(px) {
      const x = sx.invert(px);
      let best = 0;
      for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - x) < Math.abs(xs[best] - x)) best = i;
      return best;
    }
    svgEl.addEventListener("pointermove", (e) => {
      const r = svgEl.getBoundingClientRect();
      showAt(nearest(e.clientX - r.left), e.clientX, e.clientY);
    });
    svgEl.addEventListener("pointerleave", hide);
    svgEl.addEventListener("focus", () => showAt(idx < 0 ? xs.length - 1 : idx));
    svgEl.addEventListener("blur", hide);
    svgEl.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        showAt((idx < 0 ? xs.length - 1 : idx) + (e.key === "ArrowRight" ? 1 : -1));
      } else if (e.key === "Home") { e.preventDefault(); showAt(0); }
      else if (e.key === "End") { e.preventDefault(); showAt(xs.length - 1); }
      else if (e.key === "Escape") hide();
    });
    plot.appendChild(svgEl);
  }
  onResize(plot, draw);
  return fig;
}

// ------------------------------------------------------------------ bars from a reference value
function barPath(xa, xb, y, bh, r = 4) {
  // xa = baseline (square end), xb = data end (rounded)
  const w = Math.abs(xb - xa);
  if (w < 0.5) return "";
  const rr = Math.min(r, w, bh / 2);
  if (xb >= xa) {
    return `M${xa},${y}H${xb - rr}Q${xb},${y} ${xb},${y + rr}V${y + bh - rr}Q${xb},${y + bh} ${xb - rr},${y + bh}H${xa}Z`;
  }
  return `M${xa},${y}H${xb + rr}Q${xb},${y} ${xb},${y + rr}V${y + bh - rr}Q${xb},${y + bh} ${xb + rr},${y + bh}H${xa}Z`;
}

/**
 * Horizontal bars that grow left/right from a reference value (1500 = average).
 * categories: [{key, label, sub?}]
 * series: [{label, color, values: {key: {value, lo?, hi?, provisional?, pm?}}}]  (1 series = single color, no legend)
 * opts: {ref, refLabel, label, tip(cat) -> {title, sub, rows}, table: {columns, rows}, valueFmt}
 */
export function refBars(categories, series, opts = {}) {
  const ref = opts.ref ?? 1500;
  const valueFmt = opts.valueFmt || ((v) => fmt.r(v.value) + (v.pm != null ? ` ±${Math.round(v.pm)}` : ""));
  const nS = series.length;
  const barH = nS === 1 ? 18 : 12;
  const gap = 2;
  const barsH = nS * barH + (nS - 1) * gap;
  const top = 22;
  // wide: category labels in a left column; narrow (< STACK_W): labels sit above each row's bars
  const STACK_W = 520;
  const layout = (W) => {
    const stacked = W < STACK_W;
    const rowH = stacked ? barsH + 30 : nS === 1 ? 36 : barsH + 18;
    return { stacked, rowH, height: top + categories.length * rowH + 6 };
  };
  const fig = h("figure", { class: "chart" });
  if (nS >= 2) fig.appendChild(legend(series.map((x) => ({ label: x.label, color: x.color, kind: "rect" }))));
  const plot = h("div", { class: "chart-plot", style: { "min-height": `${layout(1000).height}px` } });
  const live = h("div", { class: "sr-only", "aria-live": "polite" });
  fig.append(plot, live);

  const vals = [];
  for (const sr of series) for (const c of categories) {
    const v = sr.values[c.key];
    if (v && v.value != null) vals.push(v);
  }
  if (!vals.length) {
    clear(plot);
    plot.style.minHeight = "0";
    plot.appendChild(h("div", { class: "empty" }, opts.empty || "No subject ratings yet."));
    return fig;
  }
  if (opts.table) fig.appendChild(tableView(opts.table.columns, opts.table.rows, { caption: opts.label }));

  function draw(W) {
    clear(plot);
    const { stacked, rowH, height } = layout(W);
    plot.style.minHeight = `${height}px`;
    const labelW = stacked ? 0 : Math.min(124, Math.max(...categories.map((c) => textWidth(c.label, 13))) + 16);
    let dmin = ref, dmax = ref;
    for (const v of vals) {
      dmin = Math.min(dmin, v.lo ?? v.value, v.value);
      dmax = Math.max(dmax, v.hi ?? v.value, v.value);
    }
    const span = Math.max(dmax - dmin, 200);
    const fs = nS === 1 ? 12 : 11;
    const labelText = (v) => valueFmt(v) + (v.provisional ? " prov" : "");
    const lblW = (side) => {
      const xs = vals.filter((v) => (side > 0 ? v.value >= ref : v.value < ref));
      return xs.length ? Math.max(...xs.map((v) => textWidth(labelText(v), fs))) + 10 : 6;
    };
    const leftPad = lblW(-1), rightPad = lblW(1);
    const x0 = labelW + leftPad, x1 = Math.max(x0 + 40, W - rightPad);
    // pad the domain so whiskers fit; keep the reference inside
    const sx = linear(dmin - span * 0.02, dmax + span * 0.02, x0, x1);
    const svgEl = s("svg", { width: W, height, viewBox: `0 0 ${W} ${height}`, role: "group", "aria-label": opts.label || "Bar chart" });
    const xr = Math.round(sx(ref)) + 0.5;
    // stacked rows put their labels above the bars: draw the reference line per row so it never
    // runs through a label
    if (!stacked) svgEl.appendChild(s("line", { class: "ref-line", x1: xr, x2: xr, y1: top - 4, y2: height - 4 }));
    const refText = opts.refLabel || `${ref} = average`;
    const rtw = textWidth(refText, 11) / 2;
    const anchor = xr + rtw > W ? "end" : xr - rtw < labelW ? "start" : "middle";
    svgEl.appendChild(s("text", { class: "ref-label", x: xr, y: 12, "text-anchor": anchor }, refText));
    categories.forEach((c, ci) => {
      const y0 = top + ci * rowH;
      const g = s("g");
      if (stacked) {
        g.appendChild(s("text", { class: "cat-label", x: 0, y: y0 + 15 }, c.label,
          c.sub ? s("tspan", { class: "cat-sub", dx: 6 }, c.sub) : null));
      } else {
        g.appendChild(s("text", { class: "cat-label", x: 0, y: y0 + rowH / 2 + (c.sub ? -1 : 4) }, c.label));
        if (c.sub) g.appendChild(s("text", { class: "cat-sub", x: 0, y: y0 + rowH / 2 + 12 }, c.sub));
      }
      if (ci > 0) g.appendChild(s("line", { class: "grid-line", x1: 0, x2: W, y1: Math.round(y0) + 0.5, y2: Math.round(y0) + 0.5 }));
      const barsTop = stacked ? y0 + 22 : y0 + (rowH - barsH) / 2;
      if (stacked) g.appendChild(s("line", { class: "ref-line", x1: xr, x2: xr, y1: barsTop - 3, y2: barsTop + barsH + 3 }));
      series.forEach((sr, si) => {
        const v = sr.values[c.key];
        const by = barsTop + si * (barH + gap);
        if (!v || v.value == null) {
          const right = xr + 60 < W;
          g.appendChild(s("text", { class: "cat-sub", x: right ? xr + 6 : xr - 6, y: by + barH / 2 + 4, "text-anchor": right ? "start" : "end" }, "no data"));
          return;
        }
        const xb = sx(v.value);
        const d = barPath(sx(ref), xb, by, barH);
        if (d) g.appendChild(s("path", { class: `bar${v.provisional ? " prov" : ""}`, d, style: `fill:${sr.color}` }));
        if (v.lo != null && v.hi != null) {
          // ± standard error as a hairline whisker with end caps, centred on the bar
          const yc = Math.round(by + barH / 2) + 0.5, x1w = sx(v.lo), x2w = sx(v.hi), cap = Math.min(4, barH / 2);
          g.appendChild(s("path", { class: "whisker", d: `M${x1w},${yc}H${x2w}M${x1w},${yc - cap}V${yc + cap}M${x2w},${yc - cap}V${yc + cap}` }));
        }
        const right = v.value >= ref;
        const lx = right ? Math.max(xb, v.hi != null ? sx(v.hi) : xb) + 6 : Math.min(xb, v.lo != null ? sx(v.lo) : xb) - 6;
        const t = s("text", { class: "bar-label", x: lx, y: by + barH / 2 + 4, "text-anchor": right ? "start" : "end", style: nS > 1 ? "font-size:11px" : null },
          fmt.r(v.value), v.pm != null ? s("tspan", { class: "pm" }, ` ±${Math.round(v.pm)}`) : null, v.provisional ? s("tspan", { class: "pm" }, " prov") : null);
        g.appendChild(t);
      });
      // hit target: the whole row (>= 24px tall), focusable
      const content = () => tipContent(opts.tip ? opts.tip(c) : {
        title: c.label,
        rows: series.map((sr) => {
          const v = sr.values[c.key];
          return { color: sr.color, kind: "rect", value: v && v.value != null ? valueFmt(v) : "no data", label: nS > 1 ? sr.label : (v && v.provisional ? "provisional" : "") };
        }),
      });
      const hit = s("rect", { class: "hit", x: 0, y: y0, width: W, height: rowH, tabindex: "0", rx: 4, "aria-label": `${c.label}: ${series.map((sr) => { const v = sr.values[c.key]; return (nS > 1 ? sr.label + " " : "") + (v && v.value != null ? valueFmt(v) + (v.provisional ? " (provisional)" : "") : "no data"); }).join(", ")}` });
      hit.addEventListener("pointermove", (e) => showTip(content(), e.clientX, e.clientY));
      hit.addEventListener("pointerleave", hideTip);
      hit.addEventListener("focus", () => {
        const pos = () => { const r = hit.getBoundingClientRect(); return { x: r.left + Math.min(r.width - 40, xr + 40), y: r.top }; };
        const node = content();
        const { x, y } = pos();
        showTip(node, x, y, { el: hit, pos });
        live.textContent = node.textContent;
      });
      hit.addEventListener("blur", hideTip);
      g.appendChild(hit);
      svgEl.appendChild(g);
    });
    plot.appendChild(svgEl);
  }
  onResize(plot, draw);
  return fig;
}

// ------------------------------------------------------------------ sparkline
export function sparkline(values, { w = 84, h: H = 24, label } = {}) {
  const v = (values || []).filter((x) => x != null);
  if (!v.length) return h("span", { class: "muted" }, "–");
  const pad = 5;
  let lo = Math.min(...v), hi = Math.max(...v);
  if (hi - lo < 40) { const mid = (hi + lo) / 2; lo = mid - 20; hi = mid + 20; }
  const sx = (i) => (v.length === 1 ? w - pad : pad + (i / (v.length - 1)) * (w - 2 * pad));
  const sy = (x) => H - pad - ((x - lo) / (hi - lo)) * (H - 2 * pad);
  const svgEl = s("svg", { class: "spark", width: w, height: H, viewBox: `0 0 ${w} ${H}`, role: "img",
    "aria-label": label || `Trend: ${v.map((x) => Math.round(x)).join(", ")}` });
  if (v.length > 1) svgEl.appendChild(s("path", { class: "spark-line", d: "M" + v.map((x, i) => `${sx(i).toFixed(1)},${sy(x).toFixed(1)}`).join("L") }));
  svgEl.appendChild(s("circle", { class: "spark-dot", cx: sx(v.length - 1), cy: sy(v[v.length - 1]), r: 4 }));
  // hover readout (the values are also in the aria-label and on the entity's page)
  const tip = () => tipContent({ title: label ? label.replace(/^Rating trend for /, "") : "Trend", sub: `Last ${v.length} rating${v.length === 1 ? "" : "s"}, oldest first`,
    rows: [{ color: "var(--s1)", value: v.map((x) => Math.round(x)).join(" → ") }] });
  svgEl.addEventListener("pointerenter", (e) => showTip(tip(), e.clientX, e.clientY));
  svgEl.addEventListener("pointermove", (e) => showTip(tip(), e.clientX, e.clientY));
  svgEl.addEventListener("pointerleave", hideTip);
  return svgEl;
}

// ------------------------------------------------------------------ sequential bins
/** Map a magnitude to a 1..6 bin of the blue ramp (0 / negative -> no fill). */
export function seqBin(v, max) {
  if (v == null || v <= 0 || !max) return 0;
  return Math.max(1, Math.min(6, Math.ceil((v / max) * 6)));
}

export function rampLegend(min, max) {
  return h("span", { class: "ramp-legend" }, String(min),
    h("span", { class: "ramp", "aria-hidden": "true" }, [1, 2, 3, 4, 5, 6].map((i) => h("span", { style: { background: `var(--q${i})` } }))),
    String(max));
}
