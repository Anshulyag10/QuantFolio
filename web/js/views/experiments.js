// Experiments: read-only view of results/experiments produced by run_experiments.py.
import { bars, heatmap, plot } from "../charts.js";
import { loadExperiments } from "../store.js";
import { $, downloadCSV, emptyPanel, errorPanel, esc, fmt, frameRows, loadingPanel, SOURCE, table, tip } from "../ui.js";

export default {
  kicker: "Research",
  mount(host) {
    host.innerHTML = loadingPanel("Reading saved experiments");
    loadExperiments().then((ex) => render(host, ex)).catch((e) => {
      host.innerHTML = /No saved/.test(e.message)
        ? emptyPanel("No saved experiments", "Generate them with <code>python run_experiments.py</code> (about 3 minutes), then reload.")
        : errorPanel(e.message);
    });
  },
};

function render(host, ex) {
  const ab = frameRows(ex.ablation), ho = frameRows(ex.holdout);
  const best = ho.reduce((a, b) => (b["Sharpe (selection)"] > a["Sharpe (selection)"] ? b : a));
  host.innerHTML = `
    <div class="banner info">ⓘ <div><b>Research question:</b> can risk-aware optimisation produce more stable portfolios than 1/N and mean-variance on a commodity-heavy universe, after costs and out of sample? These results are read from <code>results/experiments/</code>; re-run <code>python run_experiments.py</code> to regenerate them.</div></div>
    <div class="glass card"><div class="card-head"><div><h3>Estimator ablation</h3><p class="desc">Each row changes one ingredient. Compare E1→E3 (mean shrinkage), E1→E2 (covariance shrinkage), E7→E8 and E10→E11 (covariance only).</p></div>
      <div class="row">${SOURCE.exp}<button class="link-btn" id="ex-csv">Download CSV</button></div></div><div id="ex-table"></div></div>
    <div class="grid g-12">
      <div class="glass card span-7"><div class="card-head"><div><h3>Sharpe with 95% bootstrap interval</h3><p class="desc">Intervals crossing zero cannot rule out zero skill.</p></div>${SOURCE.exp}</div><div class="chart tall" id="ex-sharpe"></div></div>
      <div class="glass card span-5"><div class="card-head"><div><h3>Selection vs untouched holdout</h3><p class="desc">Sharpe before 2022 vs from 2022. Best in selection: <b>${esc(best._id)}</b>, holdout rank ${fmt.num(best["rank (holdout)"], 0)} of ${ho.length}.</p></div>${SOURCE.exp}</div><div class="chart tall" id="ex-hold"></div></div>
      ${ex.window ? `<div class="glass card span-6"><div class="card-head"><div><h3>Sensitivity: window × rebalance</h3><p class="desc">Out-of-sample Sharpe.</p></div>${SOURCE.exp}</div><div class="chart" id="ex-win"></div></div>` : ""}
      ${ex.costs ? `<div class="glass card span-6"><div class="card-head"><div><h3>Sensitivity: transaction costs</h3><p class="desc">Out-of-sample Sharpe.</p></div>${SOURCE.exp}</div><div class="chart" id="ex-cost"></div></div>` : ""}
      ${ex.cap ? `<div class="glass card span-6"><div class="card-head"><div><h3>Sensitivity: maximum weight</h3><p class="desc">Out-of-sample Sharpe.</p></div>${SOURCE.exp}</div><div class="chart" id="ex-cap"></div></div>` : ""}
      ${ex.cvar ? `<div class="glass card span-6"><div class="card-head"><div><h3>Min-CVaR confidence level</h3><p class="desc">A 99% tail from 504 days rests on ~5 observations.</p></div>${SOURCE.exp}</div><div id="ex-cvar"></div></div>` : ""}
    </div>`;
  const cols = [
    { key: "_id", label: "ID" }, { key: "experiment", label: "Experiment", fmt: esc, left: true },
    { key: "Sharpe", label: "Sharpe", fmt: (v) => fmt.num(v) },
    { key: "Sharpe CI low", label: "CI low", fmt: (v) => fmt.num(v) }, { key: "Sharpe CI high", label: "CI high", fmt: (v) => fmt.num(v) },
    { key: "Max Drawdown", label: "Max DD", fmt: (v) => `<span class="neg">${fmt.pct(v)}</span>` },
    { key: "Turnover (ann.)", label: "Turnover", fmt: (v) => fmt.x(v) }, { key: "Avg effective N", label: "Eff. N", fmt: (v) => fmt.num(v, 1) },
    { key: "p-value vs 1/N", label: "p raw", fmt: (v) => fmt.num(v, 3) },
    { key: "p Holm vs 1/N", label: `p Holm`, fmt: (v) => fmt.num(v, 3) }, { key: "DSR", label: "DSR", fmt: (v) => fmt.num(v) },
  ];
  table($("#ex-table"), cols, ab);
  $("#ex-csv").addEventListener("click", () => downloadCSV("quantfolio_ablation.csv", cols, ab));
  bars("ex-sharpe", ab.map((r) => `${r._id} ${r.experiment.replace(/\s+/g, " ")}`), [ab.map((r) => r.Sharpe)], { horizontal: true,
    errors: [{ plus: ab.map((r) => r["Sharpe CI high"] - r.Sharpe), minus: ab.map((r) => r.Sharpe - r["Sharpe CI low"]) }] });
  const lo = Math.min(...ho.flatMap((r) => [r["Sharpe (selection)"], r["Sharpe (holdout)"]])) - 0.1;
  const hi = Math.max(...ho.flatMap((r) => [r["Sharpe (selection)"], r["Sharpe (holdout)"]])) + 0.1;
  plot("ex-hold", [
    { type: "scatter", mode: "lines", x: [lo, hi], y: [lo, hi], line: { dash: "dot", color: "#9A8F7B", width: 1 }, hoverinfo: "skip", name: "equal" },
    { type: "scatter", mode: "markers+text", x: ho.map((r) => r["Sharpe (selection)"]), y: ho.map((r) => r["Sharpe (holdout)"]), text: ho.map((r) => r._id),
      textposition: "top center", textfont: { size: 10 }, marker: { size: 9, color: "#1A2E26", line: { width: 1.5, color: "#FDFBF7" } },
      customdata: ho.map((r) => r.experiment), hovertemplate: "<b>%{text}</b> %{customdata}<br>selection %{x:.2f} · holdout %{y:.2f}<extra></extra>" },
  ], { hovermode: "closest", showlegend: false, xaxis: { title: { text: "Sharpe, selection period" } }, yaxis: { title: { text: "Sharpe, holdout 2022+" } } });
  const greenRed = [[0, "#F5F2EB"], [1, "#1A2E26"]];
  const range = (f) => { const v = f.data.flat().filter((x) => x != null); return { zmin: Math.min(...v), zmax: Math.max(...v) }; };
  if (ex.window) heatmap("ex-win", ex.window, { ...range(ex.window), colors: greenRed });
  if (ex.costs) heatmap("ex-cost", ex.costs, { ...range(ex.costs), colors: greenRed });
  if (ex.cap) heatmap("ex-cap", ex.cap, { ...range(ex.cap), colors: greenRed });
  if (ex.cvar) table($("#ex-cvar"), [{ key: "_id", label: "Confidence" }, ...ex.cvar.columns.map((c) => ({ key: c, label: c, fmt: (v) => (c === "Sharpe" ? fmt.num(v) : fmt.pct(v, c.includes("CVaR") ? 2 : 1)) }))], frameRows(ex.cvar));
}
