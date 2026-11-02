// Strategy comparison: walk-forward results for several rules side by side.
import { bars, colorFor, plot } from "../charts.js";
import { COMPARISON_SET, runAnalysis, setConfig, state } from "../store.js";
import { $, $$, downloadCSV, emptyPanel, esc, fmt, label, loadingPanel, setBusy, SOURCE, table, tip } from "../ui.js";
import { btTable, provenance, watch } from "./common.js";

const ALL = ["equal_weight", "mean_variance", "min_variance", "min_cvar", "hrp", "risk_parity", "max_sharpe",
  "max_diversification", "inverse_vol", "black_litterman"];
const COLS = [
  { key: "name", label: "Strategy" },
  { key: "CAGR", label: "CAGR", fmt: (v) => `<span class="${v >= 0 ? "pos" : "neg"}">${fmt.pct(v)}</span>` },
  { key: "Sharpe", label: "Sharpe", fmt: (v) => fmt.num(v) },
  { key: "Sortino", label: "Sortino", fmt: (v) => fmt.num(v) },
  { key: "Volatility", label: "Volatility", fmt: (v) => fmt.pct(v) },
  { key: "Max Drawdown", label: "Max DD", fmt: (v) => `<span class="neg">${fmt.pct(v)}</span>` },
  { key: "Turnover (ann.)", label: "Turnover", fmt: (v) => fmt.x(v) },
  { key: "ci", label: "Sharpe 95% CI", fmt: (v) => esc(v) },
  { key: "p Holm vs 1/N", label: "p (Holm)", fmt: (v) => (v == null ? "—" : `<span class="${v < 0.05 ? "pos" : ""}">${fmt.num(v, 3)}</span>`) },
  { key: "DSR", label: "DSR", fmt: (v) => fmt.num(v) },
];
const METRICS = [["Sharpe", "Sharpe ratio", ".2f"], ["CAGR", "CAGR", ".1%"], ["Sortino", "Sortino", ".2f"],
  ["Volatility", "Volatility", ".1%"], ["Max Drawdown", "Max drawdown", ".1%"], ["Turnover (ann.)", "Turnover", ".2f"]];

export default {
  kicker: "Compare",
  mount(host) {
    const sel = new Set(state.config.backtest_methods.length ? state.config.backtest_methods : COMPARISON_SET);
    host.innerHTML = `
      <div class="glass card">
        <div class="card-head"><div><h3>Strategies to compare</h3><p class="desc">Each is re-optimised every ${state.config.rebalance_every} days on the previous ${state.config.lookback} days only, after ${state.config.cost_bps} bps costs. Equal weight and the ${esc(state.config.benchmark)} benchmark are always included.</p></div></div>
        <div class="row" id="st-chips">${ALL.map((m) => `<button type="button" class="chip ${sel.has(m) ? "on" : ""}" data-m="${m}" aria-pressed="${sel.has(m)}">${label(m)}</button>`).join("")}</div>
        <div class="row" style="margin-top:16px"><button class="btn btn-primary btn-md" id="st-run"><span class="spinner" aria-hidden="true"></span><span class="lbl" data-idle="Run comparison">Run comparison</span></button>
        <span class="source-note" style="margin:0">Typically 10–40 s depending on the strategies (min-CVaR solves an LP at each rebalance).</span></div>
      </div>
      <div id="st-results" class="results"></div>`;
    $("#st-chips").addEventListener("click", (e) => {
      const b = e.target.closest(".chip");
      if (!b || b.dataset.m === "equal_weight") return;
      b.classList.toggle("on");
      b.setAttribute("aria-pressed", b.classList.contains("on"));
    });
    $("#st-run").addEventListener("click", () => {
      const methods = $$("#st-chips .chip.on").map((b) => b.dataset.m);
      setConfig({ backtest_methods: methods });
      runAnalysis({ backtest: true, methods }).catch(() => {});
    });
    const off = watch((k) => {
      if (k === "busy") { setBusy($("#st-run"), state.busy.backtest, "Backtesting…"); if (!state.backtest) render(); }
      if (k === "result") render();
    });
    if (!state.backtest && !state.busy.backtest) runAnalysis({ backtest: true }).catch(() => {});
    render();
    return off;
  },
};

function render() {
  const host = $("#st-results");
  if (!host) return;
  const bt = state.backtest;
  if (!bt) {
    host.innerHTML = state.busy.backtest ? loadingPanel(state.busy.backtest, "Walk-forward, no look-ahead") : emptyPanel("No comparison yet", "Pick strategies and press <b>Run comparison</b>.");
    return;
  }
  const rows = btTable(bt).map((r) => ({ ...r, name: r._id.includes("buy & hold") ? r._id : label(r._id),
    ci: r["Sharpe CI low"] == null ? "—" : `${fmt.num(r["Sharpe CI low"])} – ${fmt.num(r["Sharpe CI high"])}` }));
  const strat = rows.filter((r) => !r._id.includes("buy & hold"));
  const by = (k, dir = 1) => [...strat].sort((a, b) => (a[k] - b[k]) * dir)[0];
  const profiles = [
    ["Conservative", "Lowest realised volatility", by("Volatility"), (r) => fmt.pct(r.Volatility) + " vol", "56,217,245"],
    ["Capital preservation", "Shallowest maximum drawdown", by("Max Drawdown", -1), (r) => fmt.pct(r["Max Drawdown"]) + " max DD", "52,211,153"],
    ["Best risk-adjusted", "Highest out-of-sample Sharpe", by("Sharpe", -1), (r) => fmt.num(r.Sharpe) + " Sharpe", "146,60,255"],
    ["Growth", "Highest CAGR", by("CAGR", -1), (r) => fmt.pct(r.CAGR) + " CAGR", "231,71,175"],
  ];
  host.innerHTML = `
    <p class="micro">${provenance(bt)} · out-of-sample from ${bt.backtest.start}</p>
    <div class="grid g-metrics">${profiles.map(([t, d, r, f, c]) => `<div class="metric">
      <div class="label">${t}</div><div class="value" style="font-size:24px">${esc(r.name)}</div><div class="foot">${d} · <span class="num">${f(r)}</span></div></div>`).join("")}</div>
    <div class="glass card"><div class="card-head"><div><h3>Performance table</h3><p class="desc">Click a column to sort. p (Holm) ${tip("holm")} · DSR ${tip("dsr")}</p></div>
      <div class="row">${SOURCE.bt}<button class="link-btn" id="st-csv">Download CSV</button></div></div><div id="st-table"></div>
      <p class="source-note">Suitability cards are a ranking of these realised results, not advice. None of the Sharpe differences vs 1/N is meaningful unless p (Holm) &lt; 0.05.</p></div>
    <div class="grid g-12">
      <div class="glass card span-7"><div class="card-head"><h3>Compare by metric</h3><select class="select" id="st-metric" style="width:auto">${METRICS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></div><div class="chart" id="st-bars"></div></div>
      <div class="glass card span-5"><div class="card-head"><div><h3>Risk vs return</h3><p class="desc">Realised volatility vs CAGR.</p></div></div><div class="chart" id="st-scatter"></div></div>
    </div>`;
  table($("#st-table"), COLS, rows, { highlight: (r) => r._id === bt.config.method });
  $("#st-csv").addEventListener("click", () => downloadCSV("quantfolio_strategy_comparison.csv",
    [{ key: "name", label: "Strategy" }, ...["CAGR", "Volatility", "Sharpe", "Sortino", "Max Drawdown", "Calmar", "Turnover (ann.)", "Sharpe CI low", "Sharpe CI high", "p-value vs 1/N", "p Holm vs 1/N", "PSR (SR>0)", "DSR", "Total Return"].map((k) => ({ key: k, label: k }))], rows));
  const drawBars = () => {
    const [k, , f] = METRICS.find((m) => m[0] === $("#st-metric").value);
    const sorted = [...rows].filter((r) => r[k] != null).sort((a, b) => b[k] - a[k]);
    bars("st-bars", sorted.map((r) => r.name), [sorted.map((r) => r[k])], { yfmt: f });
  };
  $("#st-metric").addEventListener("change", drawBars);
  drawBars();
  plot("st-scatter", rows.map((r, i) => ({ type: "scatter", mode: "markers+text", name: r.name, x: [r.Volatility], y: [r.CAGR], text: [r.name],
    textposition: "top center", textfont: { size: 10, color: "#4A5D55" }, marker: { size: 8 + 22 * Math.max(0, r.Sharpe || 0), color: r._id === bt.config.method ? "#1A2E26" : "#FDFBF7", line: { width: 1.2, color: "#1A2E26" } },
    hovertemplate: `<b>${esc(r.name)}</b><br>vol %{x:.1%} · CAGR %{y:.1%}<br>Sharpe ${fmt.num(r.Sharpe)}<extra></extra>` })),
  { hovermode: "closest", showlegend: false, xaxis: { tickformat: ".0%", title: { text: "Volatility" } }, yaxis: { tickformat: ".0%", title: { text: "CAGR" } } });
}
