// Risk analytics for the current allocation: tail risk, drawdowns, rolling volatility, correlations, risk budget, stress.
import { bars, heatmap, histogram, lines } from "../charts.js";
import { state } from "../store.js";
import { $, animateCounters, downloadCSV, emptyPanel, esc, fmt, label, loadingPanel, metric, SOURCE, table, tip } from "../ui.js";
import { ensure, provenance, watch } from "./common.js";

export default {
  kicker: "Measure",
  mount(host) {
    host.innerHTML = '<div id="rk" class="results"></div>';
    const off = watch((k) => (k === "result" || (k === "busy" && !state.result)) && render());
    ensure({ result: true });
    render();
    return off;
  },
};

function render() {
  const host = $("#rk");
  if (!host) return;
  const res = state.result;
  if (!res) {
    host.innerHTML = state.busy.analyze || state.busy.backtest ? loadingPanel("Computing risk", "") : emptyPanel("No portfolio yet", "Optimise a portfolio first.", '<a class="btn btn-primary btn-md" href="#/app/optimise">Go to optimiser</a>');
    return;
  }
  const ea = res.ex_ante, cap = res.config.capital, h = res.historical;
  const v = (a, m) => ea[`VaR ${a}% 1d (${m})`], cv = (a, m) => ea[`CVaR ${a}% 1d (${m})`];
  host.innerHTML = `
    <p class="micro">${esc(label(res.config.method))} · ${provenance(res)} · tail risk from the ${res.config.lookback} days to ${res.estimation?.end ?? res.data_range[1]}</p>
    <div class="grid g-metrics" id="rk-m">
      ${metric({ label: "Historical VaR 95%", value: v(95, "historical"), dec: 2, tipKey: "var", tint: "255,92,122", foot: `${fmt.money(v(95, "historical") * cap)} on ${fmt.compact(cap)}` })}
      ${metric({ label: "Parametric VaR 95%", value: v(95, "gaussian"), dec: 2, tipKey: "var", tint: "65,105,255", foot: "Gaussian" })}
      ${metric({ label: "Historical CVaR 95%", value: cv(95, "historical"), dec: 2, tipKey: "cvar", tint: "231,71,175", foot: `${fmt.money(cv(95, "historical") * cap)}` })}
      ${metric({ label: "Parametric CVaR 95%", value: cv(95, "gaussian"), dec: 2, tipKey: "cvar", tint: "146,60,255", foot: "Gaussian" })}
      ${metric({ label: "Max drawdown", value: h.max_drawdown, tipKey: "mdd", cls: "neg", tint: "255,138,82", foot: "today's weights on full history" })}
      ${metric({ label: "Volatility", value: ea["Volatility (ann.)"], tipKey: "vol", tint: "56,217,245", foot: "ex-ante, annualised" })}
    </div>
    <div class="grid g-12">
      <div class="glass card span-7"><div class="card-head"><div><h3>Daily return distribution</h3><p class="desc">Today's weights applied to every day in the sample. Red bars lie beyond the historical 95% VaR.</p></div>${SOURCE.hist}</div><div class="chart" id="rk-hist"></div></div>
      <div class="glass card span-5"><div class="card-head"><div><h3>VaR & CVaR by model</h3><p class="desc">One-day loss, % of value ${tip("cf")}</p></div><button class="link-btn" id="rk-csv">CSV</button></div><div id="rk-table"></div>
        <p class="source-note">Historical &gt; Gaussian means fatter left tails than the normal model assumes.</p></div>
      <div class="glass card span-6"><div class="card-head"><div><h3>Rolling volatility</h3><p class="desc">63-day window, annualised.</p></div>${SOURCE.hist}</div><div class="chart" id="rk-vol"></div></div>
      <div class="glass card span-6"><div class="card-head"><div><h3>Historical drawdown</h3><p class="desc">Today's weights, rebalanced daily, over the full sample.</p></div>${SOURCE.hist}</div><div class="chart" id="rk-dd"></div></div>
      <div class="glass card span-6"><div class="card-head"><div><h3>Risk contribution by asset</h3><p class="desc">Capital weight vs share of volatility ${tip("rc")}</p></div>${SOURCE.ante}</div><div class="chart tall" id="rk-rc"></div></div>
      <div class="glass card span-6"><div class="card-head"><div><h3>Correlation</h3><p class="desc">Estimation window.</p></div>${SOURCE.hist}</div><div class="chart tall" id="rk-corr"></div></div>
      <div class="glass card span-7"><div class="card-head"><div><h3>Historical crisis replay</h3><p class="desc">Today's weights held through past crises (buy &amp; hold). Not a replay of the rebalanced strategy; coverage &lt; 100% means some assets had no data then.</p></div>${SOURCE.hist}</div><div id="rk-stress"></div></div>
      <div class="glass card span-5"><div class="card-head"><div><h3>Market shock</h3><p class="desc">First-order CAPM estimate: ΔV ≈ β<sub>p</sub> × shock.</p></div></div><div id="rk-shock"></div></div>
    </div>`;
  animateCounters($("#rk-m"));
  histogram("rk-hist", h.returns_hist.counts, h.returns_hist.edges, { xfmt: ".1%", vlines: [{ x: -v(95, "historical"), label: "VaR 95% " }] });
  const models = ["historical", "gaussian", "cornish_fisher"];
  const vr = [95, 99].flatMap((a) => models.map((m) => ({ conf: `${a}%`, model: m.replace("_", "-"), var: v(a, m), cvar: cv(a, m), usd: cv(a, m) * cap })));
  const vcols = [{ key: "conf", label: "Conf." }, { key: "model", label: "Model", left: true }, { key: "var", label: "VaR", fmt: (x) => fmt.pct(x, 2) },
    { key: "cvar", label: "CVaR", fmt: (x) => fmt.pct(x, 2) }, { key: "usd", label: "CVaR $", fmt: (x) => fmt.money(x) }];
  table($("#rk-table"), vcols, vr);
  $("#rk-csv").addEventListener("click", () => downloadCSV("quantfolio_var.csv", vcols, vr));
  lines("rk-vol", { "Rolling volatility": h.rolling_vol }, { yfmt: ".0%", fill: true });
  lines("rk-dd", { Drawdown: h.drawdown }, { yfmt: ".0%", fill: true });
  const rc = [...res.risk_contrib].filter((r) => r.weight > 0.0005).sort((a, b) => b.pct_risk - a.pct_risk);
  bars("rk-rc", rc.map((r) => r.ticker), [rc.map((r) => r.weight), rc.map((r) => r.pct_risk)], { yfmt: ".0%", names: ["Capital weight", "Risk contribution"], colors: ["#1A2E26", "#9A8F7B"] });
  heatmap("rk-corr", res.correlation);
  if (res.stress.length) table($("#rk-stress"), [
    { key: "scenario", label: "Scenario" }, { key: "start", label: "From" }, { key: "end", label: "To" },
    { key: "portfolio return", label: "Portfolio", fmt: (x) => `<span class="${x >= 0 ? "pos" : "neg"}">${fmt.pct(x)}</span>` },
    { key: "worst asset", label: "Worst asset", left: true }, { key: "worst asset return", label: "Worst", fmt: (x) => fmt.pct(x) },
    { key: "coverage", label: "Coverage", fmt: (x) => fmt.pct(x, 0) }], res.stress);
  else $("#rk-stress").innerHTML = '<p class="source-note">No crisis window is covered by the selected assets.</p>';
  if (res.shock.length) table($("#rk-shock"), [
    { key: "market shock", label: `${esc(res.config.benchmark)} shock`, fmt: (x) => fmt.pct(x, 0) },
    { key: "portfolio beta", label: "β", fmt: (x) => fmt.num(x) },
    { key: "portfolio return", label: "Portfolio", fmt: (x) => `<span class="neg">${fmt.pct(x)}</span>` },
    { key: "P&L", label: "P&L", fmt: (x) => fmt.money(x) }], res.shock);
}
