// Shared UI primitives: formatting, toasts, tooltips, counters, tables, CSV, loading/empty states.

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------ formatting
const isNum = (x) => typeof x === "number" && Number.isFinite(x);
export const fmt = {
  pct: (x, d = 1) => (isNum(x) ? `${(x * 100).toFixed(d)}%` : "—"),
  spct: (x, d = 1) => (isNum(x) ? `${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%` : "—"),
  num: (x, d = 2) => (isNum(x) ? (Math.abs(x) < 0.5 * 10 ** -d ? 0 : x).toFixed(d) : "—"),   // no "-0.00"
  money: (x, d = 0) => (isNum(x) ? x.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: d, minimumFractionDigits: d }) : "—"),
  compact: (x) => (isNum(x) ? Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1, style: "currency", currency: "USD" }).format(x) : "—"),
  x: (x, d = 1) => (isNum(x) ? `${x.toFixed(d)}×` : "—"),
};
export const signClass = (x) => (isNum(x) ? (x >= 0 ? "pos" : "neg") : "");
export const METHOD_LABEL = {
  equal_weight: "Equal weight (1/N)", inverse_vol: "Inverse volatility", min_variance: "Minimum variance",
  max_sharpe: "Maximum Sharpe", mean_variance: "Mean-variance", risk_parity: "Risk parity (ERC)", hrp: "HRP",
  max_diversification: "Max diversification", min_cvar: "Minimum CVaR", black_litterman: "Black-Litterman",
};
export const label = (m) => METHOD_LABEL[m] || m;

// ------------------------------------------------------------ glossary tooltips
export const GLOSSARY = {
  cagr: "Compound annual growth rate: the constant yearly return that turns the starting value into the final value.",
  vol: "Annualised standard deviation of daily returns (daily σ × √252).",
  sharpe: "(Return − risk-free rate) ÷ volatility, annualised. Risk-free = 13-week T-bill yield (^IRX).",
  sortino: "Like Sharpe, but divides by downside deviation only, so upside volatility is not penalised.",
  mdd: "Largest peak-to-trough fall in portfolio value.",
  total: "Cumulative return over the whole out-of-sample period.",
  turnover: "Annual sum of |weight changes|. 1.0× = the whole portfolio traded once a year.",
  var: "Value at Risk: the loss not exceeded with the given confidence over one day.",
  cvar: "Conditional VaR (expected shortfall): the average loss on the days worse than VaR.",
  cf: "Cornish-Fisher: adjusts the Gaussian quantile for the skewness and kurtosis of returns.",
  effn: "Effective number of bets = 1 / Σ w². 1 = one asset; N = perfectly equal weights.",
  dr: "Diversification ratio = Σ wᵢσᵢ / σₚ. Higher = more volatility cancelled by low correlation.",
  rc: "Euler risk contribution: wᵢ(Σw)ᵢ / σₚ. The shares sum exactly to 100% of portfolio volatility.",
  psr: "Probabilistic Sharpe Ratio: probability the true Sharpe exceeds 0, given sample length, skew and kurtosis.",
  dsr: "Deflated Sharpe Ratio: PSR against the best Sharpe expected from luck across all strategies tried.",
  holm: "Holm-Bonferroni adjusted p-value of the Jobson-Korkie-Memmel test vs 1/N, corrected for testing many strategies.",
  ploss: "Share of simulated paths that end below the starting value.",
};
export const tip = (key) => `<span class="tip" tabindex="0" data-tip="${esc(GLOSSARY[key] || key)}" aria-label="${esc(GLOSSARY[key] || key)}">?</span>`;

let tipEl;
export function initTooltips() {
  tipEl = document.createElement("div");
  tipEl.className = "tooltip";
  tipEl.setAttribute("role", "tooltip");
  document.body.appendChild(tipEl);
  const show = (e) => {
    const t = e.target.closest?.("[data-tip]");
    if (!t) return;
    tipEl.textContent = t.dataset.tip;
    const r = t.getBoundingClientRect();
    tipEl.classList.add("show");
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    tipEl.style.left = `${Math.min(window.innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2))}px`;
    tipEl.style.top = `${r.top - h - 10 < 8 ? r.bottom + 10 : r.top - h - 10}px`;
  };
  const hide = (e) => { if (e.target.closest?.("[data-tip]")) tipEl.classList.remove("show"); };
  document.addEventListener("mouseover", show);
  document.addEventListener("focusin", show);
  document.addEventListener("mouseout", hide);
  document.addEventListener("focusout", hide);
}

// ------------------------------------------------------------ toasts
export function toast(msg, kind = "success") {
  const host = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<i>${kind === "error" ? "Error" : kind === "info" ? "Note" : "Done"}</i><div>${esc(msg)}</div>`;
  host.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, kind === "error" ? 6500 : 3500);
}

// ------------------------------------------------------------ animated counters
export function countUp(el, value, formatter, duration = 1100) {
  if (!Number.isFinite(value) || reducedMotion()) { el.textContent = formatter(value); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / duration);
    el.textContent = formatter(value * (1 - Math.pow(1 - k, 4)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
export function animateCounters(root) {
  // Editorial: figures are set, not animated.
  $$("[data-count]", root).forEach((el) => {
    const v = parseFloat(el.dataset.count);
    const f = fmt[el.dataset.fmt || "num"];
    const d = el.dataset.dec !== undefined ? +el.dataset.dec : undefined;
    el.textContent = d === undefined ? f(v) : f(v, d);
  });
}

/** Metric card markup. kind: hist | bt | sim | ante | exp (data provenance). */
export function metric({ label: l, value, format = "pct", dec, tipKey, foot = "", tint = "65,105,255", cls = "" }) {
  const valid = Number.isFinite(value);
  return `<div class="metric">
    <div class="label">${esc(l)} ${tipKey ? tip(tipKey) : ""}</div>
    <div class="value num ${cls}" ${valid ? `data-count="${value}" data-fmt="${format}" ${dec !== undefined ? `data-dec="${dec}"` : ""}` : ""}>${valid ? "0" : "—"}</div>
    ${foot ? `<div class="foot">${foot}</div>` : ""}</div>`;
}

export const SOURCE = {
  hist: '<span class="badge badge-hist" title="Computed from historical prices">Historical</span>',
  bt: '<span class="badge badge-bt" title="Walk-forward backtest: weights estimated only from past data">Backtest · out-of-sample</span>',
  sim: '<span class="badge badge-sim" title="Monte Carlo simulation">Simulated</span>',
  ante: '<span class="badge badge-ante" title="Forward-looking estimate from the current estimation window">Ex-ante estimate</span>',
  exp: '<span class="badge badge-exp" title="Read from results/experiments">Saved experiment</span>',
};

// ------------------------------------------------------------ states
export const loadingPanel = (msg = "Computing", stage = "") =>
  `<div class="glass loading-panel"><div class="orbit" aria-hidden="true"></div><p>${esc(msg)}…</p>${stage ? `<p class="stage">${esc(stage)}</p>` : ""}</div>`;
export const emptyPanel = (title, text, action = "") =>
  `<div class="glass empty"><div class="em-icon" aria-hidden="true">◆</div><h3>${esc(title)}</h3><p>${text}</p>${action}</div>`;
export const errorPanel = (msg, action = "") =>
  `<div class="glass empty"><h3>Something went wrong</h3><p>${esc(msg)}</p>${action}</div>`;

// ------------------------------------------------------------ tables + CSV
/**
 * Sortable table. columns: [{key, label, fmt?: (v,row)=>string, num?: bool}]. rows: objects.
 */
export function table(host, columns, rows, { highlight, id } = {}) {
  let sortKey = null, dir = -1;
  const render = () => {
    const data = [...rows];
    if (sortKey) data.sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
    });
    host.innerHTML = `<div class="table-wrap"><table class="data" ${id ? `id="${id}"` : ""}><thead><tr>${columns.map((c) =>
      `<th scope="col" class="${c.left ? "l" : ""}" data-k="${c.key}" ${c.key === sortKey ? `aria-sort="${dir > 0 ? "ascending" : "descending"}"` : 'aria-sort="none"'} tabindex="0">${c.label}</th>`).join("")}</tr></thead>
      <tbody>${data.map((r) => `<tr class="${highlight && highlight(r) ? "hl" : ""}">${columns.map((c) =>
        `<td class="${c.left ? "l" : ""}">${c.fmt ? c.fmt(r[c.key], r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    $$("th", host).forEach((th) => {
      const go = () => { const k = th.dataset.k; dir = sortKey === k ? -dir : -1; sortKey = k; render(); };
      th.addEventListener("click", go);
      th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
  };
  render();
}

export function downloadCSV(filename, columns, rows) {
  const q = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = [columns.map((c) => q(c.label ?? c.key)).join(","), ...rows.map((r) => columns.map((c) => q(r[c.key])).join(","))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast(`Downloaded ${filename}`);
}

/** {index, columns, data} frame from the API -> array of row objects keyed by column (index under `_id`). */
export const frameRows = (f) => f.index.map((id, i) => Object.fromEntries([["_id", id], ...f.columns.map((c, j) => [c, f.data[i][j]])]));

// ------------------------------------------------------------ inputs
/** Wire a range input so its gradient fill and <output> follow the value. */
export function bindRange(input, out, format = (v) => v) {
  const sync = () => {
    const p = ((input.value - input.min) / (input.max - input.min)) * 100;
    input.style.setProperty("--p", `${p}%`);
    if (out) out.textContent = format(+input.value);
  };
  input.addEventListener("input", sync);
  sync();
}

export function segmented(host, options, value, onChange) {
  host.classList.add("segmented");
  host.setAttribute("role", "group");
  host.innerHTML = options.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === value}">${esc(l)}</button>`).join("");
  host.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    $$("button", host).forEach((x) => x.setAttribute("aria-pressed", x === b));
    onChange(b.dataset.v);
  });
}

export function setBusy(btn, busy, text) {
  if (!btn) return;
  btn.disabled = !!busy;
  btn.classList.toggle("loading", !!busy);
  const span = btn.querySelector(".lbl");
  if (span && text) span.textContent = busy ? text : span.dataset.idle;
}
