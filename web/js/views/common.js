// Helpers shared by dashboard views.
import { band } from "../charts.js";
import { runAnalysis, state, subscribe } from "../store.js";
import { fmt, frameRows, label, tip } from "../ui.js";

/** Backtest table rows keyed by strategy id. */
export const btTable = (bt) => (bt?.backtest ? frameRows(bt.backtest.table) : []);
export const btRow = (bt, id) => btTable(bt).find((r) => r._id === id);
export const nameOf = (id) => label(id);

/** Rename series keys to human labels (benchmark keys are already human). */
export const labelled = (map) => Object.fromEntries(Object.entries(map).map(([k, v]) => [label(k), v]));

/** Warm-up (estimation-only) shading for backtest charts. */
export function warmup(bt) {
  const b = bt.backtest;
  const w = band(b.warmup_start, b.start, "");
  w.annotation = { ...w.annotation, x: b.start, xanchor: "right", text: "← In-sample  " };
  const oos = { x: b.start, xref: "x", yref: "paper", y: 1, xanchor: "left", yanchor: "top", text: "  Out-of-sample →", showarrow: false, font: { size: 10.5, color: "#1A2E26" } };
  const last = Object.values(b.curves)[0]?.dates.at(-1);
  return { shapes: [w.shape], annotations: [w.annotation, oos], xrange: [b.warmup_start, last] };
}

/** Kick off computations a view needs, once. */
export function ensure({ result = true, backtest = false } = {}) {
  if (result && !state.result && !state.busy.analyze && !state.busy.backtest) runAnalysis().catch(() => {});
  if (backtest && !state.backtest && !state.busy.backtest) runAnalysis({ backtest: true }).catch(() => {});
}

/** Subscribe and return the unsubscribe function (views return it from mount as cleanup). */
export const watch = (fn) => subscribe(fn);

export const provenance = (res) =>
  `${res.config.offline ? "Bundled snapshot" : "Yahoo Finance"} · ${res.data_range[0]} → ${res.data_range[1]} · ${res.assets.length} assets`
  + (res.split ? ` · optimised on ${res.estimation.start} → ${res.estimation.end}` : "");

/** Out-of-sample start date field, shared by the Optimise and Backtest forms. */
export const splitField = (id, value) => `<label class="field"><span>Out-of-sample from ${tip("The optimiser only sees data before this date; the backtest is scored from it onwards. Leave empty to optimise on the latest data and backtest the whole history.")}</span><input class="input" type="date" id="${id}" value="${value || ""}"></label>`;

export const weightsRows = (res) => Object.entries(res.weights).map(([t, w]) => {
  const rc = res.risk_contrib.find((r) => r.ticker === t) || {};
  const st = res.asset_stats.find((r) => r.ticker === t) || {};
  return { ticker: t, weight: w, dollars: w * res.config.capital, pct_risk: rc.pct_risk, exp_return: st["exp. return"], volatility: st.volatility };
}).sort((a, b) => b.weight - a.weight);

export const notesBanner = (notes = []) => notes.length
  ? `<div class="banner info">ⓘ <div>${notes.map((n) => n.replace(/</g, "&lt;")).join("<br>")}</div></div>` : "";

export const pctCell = (v) => fmt.pct(v, 2);
