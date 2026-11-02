// Backtesting workspace: walk-forward equity, drawdowns, rolling Sharpe, weights, turnover, annual returns.
import { bars, heatmap, lines, stacked } from "../charts.js";
import { runAnalysis, setConfig, state } from "../store.js";
import { $, bindRange, downloadCSV, emptyPanel, esc, fmt, frameRows, label, loadingPanel, setBusy, SOURCE, toast } from "../ui.js";
import { labelled, notesBanner, provenance, splitField, warmup, watch } from "./common.js";

const METHODS = ["max_sharpe", "mean_variance", "min_variance", "min_cvar", "risk_parity", "hrp", "black_litterman",
  "max_diversification", "inverse_vol", "equal_weight"];

export default {
  kicker: "Validate",
  mount(host) {
    const c = state.config;
    const benches = [...new Set(["SPY", "QQQ", "VTI", "AGG", "EFA", ...(state.meta?.snapshot || []).filter((r) => /equity|bond/.test(r.category)).map((r) => r.ticker)])];
    host.innerHTML = `
      <div class="workbench">
        <form class="glass controls" id="bt-form" aria-label="Backtest settings">
          <h3>Backtest settings</h3>
          <div class="two">
            <label class="field"><span>Start</span><input class="input" type="date" id="bt-start" value="${c.start}" min="2005-01-01"></label>
            <label class="field"><span>End</span><input class="input" type="date" id="bt-end" value="${c.end || ""}"></label>
          </div>
          <label class="field"><span>Strategy</span><select class="select" id="bt-method">${METHODS.map((m) => `<option value="${m}" ${m === c.method ? "selected" : ""}>${label(m)}</option>`).join("")}</select></label>
          <label class="field"><span>Initial capital</span><input class="input num" type="number" id="bt-capital" min="1000" step="1000" value="${c.capital}"></label>
          <label class="field"><span>Estimation window <output id="o-blb"></output></span><input type="range" id="bt-lb" min="126" max="1260" step="21" value="${c.lookback}"></label>
          ${splitField("bt-oos", c.oos_start)}
          <div class="two">
            <label class="field"><span>Rebalance</span><select class="select" id="bt-reb">${[[5, "Weekly"], [21, "Monthly"], [63, "Quarterly"]].map(([v, l]) => `<option value="${v}" ${v === c.rebalance_every ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <label class="field"><span>Benchmark</span><select class="select" id="bt-bench">${benches.map((b) => `<option ${b === c.benchmark ? "selected" : ""}>${esc(b)}</option>`).join("")}</select></label>
          </div>
          <label class="field"><span>Transaction costs <output id="o-bcost"></output></span><input type="range" id="bt-cost" min="0" max="50" step="1" value="${c.cost_bps}"></label>
          <button class="btn btn-primary btn-run" type="submit" id="bt-run"><span class="spinner" aria-hidden="true"></span><span class="lbl" data-idle="Run backtest">Run backtest</span></button>
          <p class="source-note">Compared against equal weight, the benchmark and the strategies selected on the Strategies page (${c.backtest_methods.length}). Returns before the out-of-sample date are never scored.</p>
        </form>
        <div class="results" id="bt-results" aria-live="polite"></div>
      </div>`;
    bindRange($("#bt-lb"), $("#o-blb"), (v) => `${v} d`);
    bindRange($("#bt-cost"), $("#o-bcost"), (v) => `${v} bps`);
    $("#bt-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const start = $("#bt-start").value, end = $("#bt-end").value || null;
      const oos = $("#bt-oos").value || null;
      if (end && end <= start) { toast("End date must be after the start date.", "error"); return; }
      if (oos && (oos <= start || (end && oos >= end))) { toast("Out-of-sample start must lie between the start and end dates.", "error"); return; }
      setConfig({ start, end, oos_start: oos, method: $("#bt-method").value, capital: +$("#bt-capital").value, lookback: +$("#bt-lb").value,
        rebalance_every: +$("#bt-reb").value, benchmark: $("#bt-bench").value, cost_bps: +$("#bt-cost").value });
      runAnalysis({ backtest: true }).then(() => toast("Backtest complete")).catch(() => {});
    });
    const off = watch((k) => {
      if (k === "busy") { setBusy($("#bt-run"), state.busy.backtest, "Backtesting…"); if (!state.backtest) render(); }
      if (k === "result") render();
    });
    if (!state.backtest && !state.busy.backtest) runAnalysis({ backtest: true }).catch(() => {});
    render();
    return off;
  },
};

function render() {
  const host = $("#bt-results");
  if (!host) return;
  const bt = state.backtest;
  if (!bt) {
    host.innerHTML = state.busy.backtest ? loadingPanel(state.busy.backtest, "Re-estimating on past data at every rebalance") : emptyPanel("No backtest yet", "Configure and press <b>Run backtest</b>.");
    return;
  }
  const b = bt.backtest, m = bt.config.method, cap = bt.config.capital;
  host.innerHTML = `
    ${notesBanner(bt.notes)}
    <p class="micro">${label(m)} · ${provenance(bt)} · window ${b.lookback} d · rebalance ${bt.config.rebalance_every} d · ${bt.config.cost_bps} bps</p>
    <div class="banner info">ⓘ <div><b>In-sample vs out-of-sample.</b> ${bt.split ? `Data before ${bt.split} is the in-sample period: the Optimise page fits its allocation on it, and the backtest never scores it. ` : ""}The shaded ${b.lookback} trading days (${b.warmup_start} → ${b.start}) only estimate the first portfolio. Every return from ${b.start} is out-of-sample: at each monthly rebalance the optimiser sees only the ${b.lookback} days before that date.</div></div>
    <div class="glass card"><div class="card-head"><div><h3>Portfolio value</h3><p class="desc">${fmt.money(cap)} invested, net of costs (log scale).</p></div>${SOURCE.bt}</div><div class="chart tall" id="bt-eq"></div></div>
    <div class="grid g-12">
      <div class="glass card span-6"><div class="card-head"><div><h3>Drawdowns</h3><p class="desc">Highlighted: ${label(m)}. Hover for every strategy.</p></div>${SOURCE.bt}</div><div class="chart" id="bt-dd"></div></div>
      <div class="glass card span-6"><div class="card-head"><div><h3>Rolling 1-year Sharpe</h3><p class="desc">252-day window on excess returns.</p></div>${SOURCE.bt}</div><div class="chart" id="bt-rs"></div></div>
      <div class="glass card span-8"><div class="card-head"><div><h3>Weights through time · ${label(m)}</h3><p class="desc">Target weights set at each rebalance.</p></div><button class="link-btn" id="bt-wcsv">Download CSV</button></div><div class="chart" id="bt-w"></div></div>
      <div class="glass card span-4"><div class="card-head"><div><h3>Turnover per rebalance</h3><p class="desc">Σ|Δw| traded.</p></div></div><div class="chart" id="bt-to"></div></div>
      <div class="glass card span-12"><div class="card-head"><div><h3>Annual returns</h3><p class="desc">Calendar-year returns (partial first and last years).</p></div><button class="link-btn" id="bt-acsv">Download CSV</button></div><div class="chart tall" id="bt-annual"></div></div>
    </div>`;
  const wu = warmup(bt);
  lines("bt-eq", labelled(b.curves), { yfmt: "$,.0f", log: true, highlight: label(m), scale: cap, ...wu });
  lines("bt-dd", labelled(b.drawdowns), { yfmt: ".0%", highlight: label(m), legend: false });
  lines("bt-rs", labelled(b.rolling_sharpe), { yfmt: ".2f", highlight: label(m), legend: false,
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { width: 1, dash: "dot", color: "#9A8F7B" } }] });
  stacked("bt-w", b.weights.dates, b.weights.assets, b.weights.values);
  bars("bt-to", b.turnover.dates, [b.turnover.values], { yfmt: ".0%" });
  const an = b.annual;
  heatmap("bt-annual", { index: an.columns.map(label), columns: an.index, data: an.columns.map((_, j) => an.index.map((_, i) => an.data[i][j])) },
    { zmin: -0.3, zmax: 0.3, fmt: ".1%", });

  $("#bt-wcsv").addEventListener("click", () => {
    const rows = b.weights.dates.map((d, i) => Object.fromEntries([["date", d], ...b.weights.assets.map((a, j) => [a, b.weights.values[j][i]])]));
    downloadCSV(`quantfolio_weights_${m}.csv`, [{ key: "date", label: "date" }, ...b.weights.assets.map((a) => ({ key: a, label: a }))], rows);
  });
  $("#bt-acsv").addEventListener("click", () => downloadCSV("quantfolio_annual_returns.csv",
    [{ key: "_id", label: "year" }, ...an.columns.map((c) => ({ key: c, label: c }))], frameRows(an)));
}
