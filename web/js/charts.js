// Plotly wrappers in the editorial palette: forest ink tones on cream, hairline grids.
// Inputs are always backend data.

export const INK = "#1A2E26";
const RULE = "#DCD7CC";
const CREAM = "#FDFBF7";
const MUTED = "#9A8F7B";        // warm beige-grey for secondary marks
const CAPTION = "#7D8A83";
// Tonal ink scale: series are told apart by tone first, then by dash pattern.
export const PALETTE = ["#1A2E26", "#9A8F7B", "#5B7368", "#C4B9A3", "#3B5247", "#7F9A8D", "#6E6352", "#A8B8AF"];
const DASHES = ["solid", "solid", "dot", "solid", "dash", "dot", "dashdot", "longdash"];
export const colorFor = (i) => PALETTE[i % PALETTE.length];
const ink = (a) => `rgba(26,46,38,${a})`;

function baseLayout(extra = {}) {
  const axis = {
    gridcolor: RULE, gridwidth: 1, zeroline: false, linecolor: INK, linewidth: 1, showline: true, ticks: "outside",
    tickcolor: INK, ticklen: 4, tickfont: { size: 11, color: CAPTION, family: "Inter, sans-serif" },
    title: { font: { size: 11.5, color: CAPTION } }, automargin: true,
  };
  return {
    paper_bgcolor: CREAM, plot_bgcolor: CREAM,
    font: { family: "Inter, Helvetica Neue, sans-serif", color: INK, size: 12 },
    margin: { l: 56, r: 16, t: 10, b: 40 }, colorway: PALETTE,
    hoverlabel: { bgcolor: INK, bordercolor: INK, font: { color: CREAM, family: "Inter", size: 12 } },
    legend: { orientation: "h", y: -0.2, x: 0, font: { size: 11.5, color: INK }, bgcolor: "rgba(0,0,0,0)" },
    hovermode: "x unified",
    ...extra,
    xaxis: { ...axis, showgrid: false, ...(extra.xaxis || {}) },
    yaxis: { ...axis, ...(extra.yaxis || {}) },
  };
}

const CONFIG = { displayModeBar: false, responsive: true };

export function plot(el, data, layout = {}) {
  el = typeof el === "string" ? document.getElementById(el) : el;
  if (!el || !window.Plotly) return;
  if (!el.classList.contains("js-plotly-plot")) el.innerHTML = "";   // drop skeleton / loading placeholder
  window.Plotly.react(el, data, baseLayout(layout), CONFIG);
}

export function rerenderAll() { /* single theme: nothing to re-theme */ }

// ------------------------------------------------------------------ chart types
/** Log-axis ticks on a 1-2-5 grid covering [lo, hi] (avoids Plotly's crowded 1..9 minor labels). */
function logTicks(lo, hi) {
  // 1-2-5 grid for wide ranges; for narrow ones (e.g. a 4-year backtest) fall back to finer mantissas.
  for (const ms of [[1, 2, 5], [1, 1.5, 2, 3, 5, 7], [1, 1.2, 1.4, 1.6, 1.8, 2, 2.5, 3, 4, 5, 6, 8]]) {
    const out = [];
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
      for (const m of ms) { const v = +(m * 10 ** e).toPrecision(6); if (v >= lo * 0.97 && v <= hi * 1.03) out.push(v); }
    }
    if (out.length >= 4) return out;
  }
  return null;   // very narrow range: let Plotly choose
}

/** Hovering a trace fades the others (one-at-a-time reading for charts with many series). */
function enableFocus(el) {
  if (el.dataset.focus) return;
  el.dataset.focus = "1";
  el.on("plotly_hover", (ev) => {
    const k = ev.points[0].curveNumber;
    window.Plotly.restyle(el, { opacity: el.data.map((_, i) => (i === k ? 1 : 0.18)) });
  });
  el.on("plotly_unhover", () => window.Plotly.restyle(el, { opacity: 1 }));
}

export function lines(el, seriesMap, { yfmt = ".2f", log = false, fill = false, ytitle = "", shapes = [], annotations = [], highlight, scale = 1, dash = {}, xrange, legend = true, focus = false } = {}) {
  const names = Object.keys(seriesMap);
  // the highlighted series is always solid ink; the rest take the tonal scale
  let k = 0;
  const data = names.map((name, i) => {
    const s = seriesMap[name], hi = highlight && name === highlight;
    const idx = highlight ? (hi ? 0 : ++k) : i;
    return {
      type: "scatter", mode: "lines", name, x: s.dates, y: s.values.map((v) => (v == null ? null : v * scale)),
      line: { color: hi ? INK : colorFor(idx), width: hi ? 2.2 : highlight ? 1.1 : 1.5, dash: dash[name] || (hi ? "solid" : DASHES[idx % DASHES.length]) },
      fill: fill && (!highlight || hi) ? "tozeroy" : "none", fillcolor: ink(0.07),
      hovertemplate: `%{y:${yfmt}}<extra>${name}</extra>`,
    };
  });
  const yaxis = { tickformat: yfmt, type: log ? "log" : "linear", title: { text: ytitle } };
  if (log) {
    const vals = data.flatMap((d) => d.y).filter((v) => v > 0);
    const ticks = vals.length && logTicks(Math.min(...vals), Math.max(...vals));
    if (ticks) yaxis.tickvals = ticks;
  }
  plot(el, data, { showlegend: legend, yaxis, shapes, annotations, xaxis: xrange ? { range: xrange } : {},
    ...(focus ? { hovermode: "closest" } : {}) });
  if (focus) {
    const node = typeof el === "string" ? document.getElementById(el) : el;
    if (node?.on) enableFocus(node);
  }
}

export function donut(el, labels, values, { center = "" } = {}) {
  plot(el, [{
    type: "pie", hole: 0.72, labels, values, sort: true, direction: "clockwise",
    marker: { colors: labels.map((_, i) => colorFor(i)), line: { color: CREAM, width: 2 } },
    textinfo: "none", hovertemplate: "<b>%{label}</b><br>%{percent}<extra></extra>",
  }], {
    showlegend: true, legend: { orientation: "v", x: 1.02, y: 0.5, font: { size: 11.5, color: INK } },
    margin: { l: 8, r: 8, t: 8, b: 8 }, hovermode: "closest",
    annotations: center ? [{ text: center, showarrow: false, font: { size: 16, color: INK, family: "Playfair Display, Georgia, serif" } }] : [],
  });
}

const DIVERGING = [[0, "#9A8F7B"], [0.5, CREAM], [1, INK]];
export function heatmap(el, frame, { zmin = -1, zmax = 1, fmt = ".2f", colors, title = "" } = {}) {
  const node = typeof el === "string" ? document.getElementById(el) : el;
  const showText = node && (node.clientWidth - 140) / frame.columns.length >= 36;
  plot(el, [{
    type: "heatmap", z: frame.data, x: frame.columns, y: frame.index, zmin, zmax, colorscale: colors || DIVERGING,
    xgap: 1, ygap: 1, texttemplate: showText ? `%{z:${fmt}}` : "", textfont: { size: 10, family: "JetBrains Mono, monospace" },
    hovertemplate: `%{y} · %{x}<br><b>%{z:${fmt}}</b><extra></extra>`,
    colorbar: { thickness: 8, outlinewidth: 0, tickfont: { size: 10, color: CAPTION }, title: { text: title, side: "right" } },
  }], { hovermode: "closest", yaxis: { autorange: "reversed", showline: false, ticks: "" }, xaxis: { showline: false, ticks: "" }, margin: { l: 70, r: 10, t: 10, b: 60 } });
}

export function bars(el, x, ys, { yfmt = ".2f", names, horizontal = false, barmode = "group", colors, errors } = {}) {
  const data = ys.map((y, i) => ({
    type: "bar", name: names?.[i], x: horizontal ? y : x, y: horizontal ? x : y, orientation: horizontal ? "h" : "v",
    marker: { color: colors?.[i] || (i === 0 ? INK : colorFor(i)), line: { width: 0 } },
    [horizontal ? "error_x" : "error_y"]: errors?.[i] ? { type: "data", symmetric: false, array: errors[i].plus, arrayminus: errors[i].minus, color: MUTED, thickness: 1, width: 3 } : undefined,
    hovertemplate: `%{${horizontal ? "x" : "y"}:${yfmt}}<extra>${names?.[i] || ""}</extra>`,
  }));
  plot(el, data, { barmode, hovermode: "closest", bargap: 0.45, showlegend: !!names,
    [horizontal ? "xaxis" : "yaxis"]: { tickformat: yfmt, showgrid: true }, [horizontal ? "yaxis" : "xaxis"]: { autorange: horizontal ? "reversed" : true, showgrid: false } });
}

export function frontier(el, fr, assets, chosen, rf, { legend = true } = {}) {
  const data = [];
  if (fr?.volatility?.length) {
    data.push({ type: "scatter", mode: "lines", name: "Efficient frontier", x: fr.volatility, y: fr.return,
      line: { width: 2.2, color: INK }, hovertemplate: "σ %{x:.1%} · μ %{y:.1%}<extra>frontier</extra>" });
    const sr = fr.return.map((r, i) => (r - rf) / fr.volatility[i]);
    const k = sr.indexOf(Math.max(...sr));
    const xmax = Math.max(...fr.volatility, ...assets.map((a) => a.volatility)) * 1.05;
    data.push({ type: "scatter", mode: "lines", name: `Capital market line (SR ${sr[k].toFixed(2)})`, x: [0, xmax], y: [rf, rf + sr[k] * xmax],
      line: { dash: "dot", width: 1, color: MUTED }, hoverinfo: "skip" });
  }
  data.push({ type: "scatter", mode: "markers+text", name: "Assets", x: assets.map((a) => a.volatility), y: assets.map((a) => a["exp. return"]),
    text: assets.map((a) => a.ticker), textposition: "top center", textfont: { size: 10, color: CAPTION, family: "JetBrains Mono, monospace" },
    marker: { size: 7, color: CREAM, line: { width: 1.2, color: INK } },
    hovertemplate: "<b>%{text}</b><br>σ %{x:.1%} · μ %{y:.1%}<extra></extra>" });
  if (chosen) data.push({ type: "scatter", mode: "markers", name: "Chosen portfolio", x: [chosen.vol], y: [chosen.ret],
    marker: { size: 11, symbol: "square", color: INK, line: { width: 2, color: CREAM } },
    hovertemplate: "Chosen<br>σ %{x:.1%} · μ %{y:.1%}<extra></extra>" });
  plot(el, data, { hovermode: "closest", showlegend: legend, margin: legend ? undefined : { l: 48, r: 8, t: 8, b: 36 },
    xaxis: { tickformat: ".0%", title: { text: "Volatility (annualised)" }, rangemode: "tozero" },
    yaxis: { tickformat: ".0%", title: { text: "Expected return" } } });
}

/** Histogram; bars left of the first vline (the tail) are drawn in full ink, the body in muted beige. */
export function histogram(el, counts, edges, { xfmt = ".1%", vlines = [], name = "" } = {}) {
  const mids = counts.map((_, i) => (edges[i] + edges[i + 1]) / 2);
  plot(el, [{ type: "bar", x: mids, y: counts, name, marker: { color: mids.map((m) => (vlines.length && m <= vlines[0].x ? INK : "#C4B9A3")), line: { width: 0 } },
    hovertemplate: `%{x:${xfmt}} · %{y} obs<extra></extra>` }], {
    bargap: 0.08, hovermode: "closest", xaxis: { tickformat: xfmt }, yaxis: { title: { text: "count" } },
    shapes: vlines.map((v) => ({ type: "line", x0: v.x, x1: v.x, yref: "paper", y0: 0, y1: 1, line: { color: INK, width: 1, dash: "dash" } })),
    annotations: vlines.map((v) => ({ x: v.x, yref: "paper", y: 1, text: v.label, showarrow: false, xanchor: "right", font: { size: 11, color: INK } })),
  });
}

export function stacked(el, dates, assets, values) {
  plot(el, assets.map((a, i) => ({
    type: "scatter", mode: "lines", stackgroup: "w", name: a, x: dates, y: values[i], line: { width: 0.6, color: CREAM, shape: "hv" },
    fillcolor: colorFor(i), hovertemplate: `%{y:.1%}<extra>${a}</extra>`,
  })), { yaxis: { tickformat: ".0%", range: [0, 1] } });
}

export function fan(el, mc) {
  const x = mc.days, b = mc.bands, data = [];
  mc.sample.forEach((p) => data.push({ type: "scatter", mode: "lines", x, y: p, showlegend: false, hoverinfo: "skip", line: { width: 0.7, color: ink(0.12) } }));
  data.push({ type: "scatter", mode: "lines", x, y: b.p95, line: { width: 0.8, color: MUTED, dash: "dot" }, name: "95th pct", hovertemplate: "95th %{y:$,.0f}<extra></extra>" });
  data.push({ type: "scatter", mode: "lines", x, y: b.p75, line: { width: 0 }, showlegend: false, hoverinfo: "skip" });
  data.push({ type: "scatter", mode: "lines", x, y: b.p25, fill: "tonexty", fillcolor: "rgba(154,143,123,.28)", line: { width: 0 }, name: "25–75%", hovertemplate: "25th %{y:$,.0f}<extra></extra>" });
  data.push({ type: "scatter", mode: "lines", x, y: b.p5, line: { width: 0.8, color: MUTED, dash: "dot" }, name: "5th pct", hovertemplate: "5th %{y:$,.0f}<extra></extra>" });
  data.push({ type: "scatter", mode: "lines", x, y: b.p50, name: "Median", line: { width: 2.2, color: INK }, hovertemplate: "median %{y:$,.0f}<extra></extra>" });
  plot(el, data, { xaxis: { title: { text: "Trading days" } }, yaxis: { tickformat: "$,.0f" } });
}

/** Shaded region (e.g. estimation warm-up) for line charts. */
export const band = (x0, x1, text) => ({
  shape: { type: "rect", xref: "x", yref: "paper", x0, x1, y0: 0, y1: 1, fillcolor: "#F5F2EB", line: { width: 0 }, layer: "below" },
  annotation: { x: x0, xref: "x", yref: "paper", y: 1, xanchor: "left", yanchor: "top", text, showarrow: false, font: { size: 10.5, color: CAPTION } },
});
