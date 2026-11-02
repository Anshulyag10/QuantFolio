// Monte Carlo lab: calls /api/montecarlo with the current allocation's weights.
import { fan, histogram } from "../charts.js";
import { runMonteCarlo, setConfig, state } from "../store.js";
import { $, animateCounters, bindRange, emptyPanel, esc, fmt, label, loadingPanel, metric, segmented, setBusy, SOURCE, toast } from "../ui.js";
import { ensure, watch } from "./common.js";

const MODELS = [["bootstrap", "Block bootstrap"], ["student_t", "Student-t"], ["gaussian", "Gaussian"]];
const DESC = {
  bootstrap: "Resamples 20-day blocks of real historical return vectors: keeps fat tails, correlations and volatility clustering.",
  student_t: "Multivariate t (ν = 5) with the estimated mean and covariance: fat, jointly occurring tails.",
  gaussian: "Multivariate normal with the estimated mean and covariance: the textbook model, thin tails.",
};
let alpha = 0.95;

export default {
  kicker: "Simulate",
  mount(host) {
    const c = state.config;
    host.innerHTML = `
      <div class="workbench">
        <form class="glass controls" id="mc-form" aria-label="Simulation settings">
          <h3>Simulation laboratory</h3>
          <div class="field"><span>Return model</span><div id="mc-model"></div><p class="source-note" id="mc-desc" style="margin:2px 0 0"></p></div>
          <label class="field"><span>Number of paths <output id="o-paths"></output></span><input type="range" id="mc-paths" min="500" max="20000" step="500" value="${c.mc_paths}"></label>
          <label class="field"><span>Horizon <output id="o-hor"></output></span><input type="range" id="mc-hor" min="21" max="1260" step="21" value="${c.mc_horizon}"></label>
          <label class="field"><span>Initial investment</span><input class="input num" type="number" id="mc-cap" min="1000" step="1000" value="${c.capital}"></label>
          <label class="field"><span>Confidence level</span><select class="select" id="mc-alpha">${[0.9, 0.95, 0.99].map((a) => `<option value="${a}" ${a === alpha ? "selected" : ""}>${a * 100}%</option>`).join("")}</select></label>
          <button class="btn btn-primary btn-run" type="submit" id="mc-run"><span class="spinner" aria-hidden="true"></span><span class="lbl" data-idle="Run simulation">Run simulation</span></button>
          <p class="source-note" id="mc-proc"></p>
        </form>
        <div class="results" id="mc-results" aria-live="polite"></div>
      </div>`;
    segmented($("#mc-model"), MODELS, c.mc_method, (m) => { setConfig({ mc_method: m }); $("#mc-desc").textContent = DESC[m]; });
    $("#mc-desc").textContent = DESC[c.mc_method];
    bindRange($("#mc-paths"), $("#o-paths"), (v) => v.toLocaleString());
    bindRange($("#mc-hor"), $("#o-hor"), (v) => `${v} d · ${(v / 252).toFixed(1)} y`);
    const proc = () => ($("#mc-proc").textContent = `Same process as the backtest: weights drift, rebalanced every ${state.config.rebalance_every} days, ${state.config.cost_bps} bps costs.`);
    proc();
    $("#mc-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!state.result) { toast("Optimise a portfolio first.", "info"); return; }
      alpha = +$("#mc-alpha").value;
      setConfig({ mc_paths: +$("#mc-paths").value, mc_horizon: +$("#mc-hor").value, capital: +$("#mc-cap").value });
      await runMonteCarlo({ alpha });
    });
    const off = watch((k) => {
      if (k === "busy") { setBusy($("#mc-run"), state.busy.mc, "Simulating…"); if (!state.mc) render(); }
      if (k === "mc" || k === "result") render();
    });
    ensure({ result: true });
    render();
    return off;
  },
};

function render() {
  const host = $("#mc-results");
  if (!host) return;
  // Use the dedicated run if present, else the simulation that came with the optimisation (bootstrap, 95%).
  const mc = state.mc || state.result?.montecarlo;
  if (!mc) {
    host.innerHTML = state.busy.mc || state.busy.analyze ? loadingPanel("Simulating wealth paths") :
      emptyPanel("No portfolio to simulate", "Optimise a portfolio, then simulate its future wealth.", '<a class="btn btn-primary btn-md" href="#/app/optimise">Go to optimiser</a>');
    return;
  }
  const s = mc.summary, a = Math.round(mc.alpha * 100), method = mc.method, cap = mc.capital;
  const tv = (q) => cap * (1 - q);
  host.innerHTML = `
    <p class="micro">${esc(label(state.result.config.method))} · ${mc.n_paths.toLocaleString()} paths · ${mc.horizon} trading days · ${MODELS.find((m) => m[0] === method)?.[1]}${state.mc ? "" : " · default run from the optimisation"}</p>
    <div class="grid g-metrics" id="mc-m">
      ${metric({ label: "Probability of loss", value: s["P(loss)"], tipKey: "ploss", tint: "255,92,122", dec: 1 })}
      ${metric({ label: "Median value", value: s["Median terminal value"], format: "money", tint: "146,60,255" })}
      ${metric({ label: `Horizon VaR ${a}%`, value: s[`Horizon VaR ${a}%`], tipKey: "var", tint: "255,138,82", foot: `value ≤ ${fmt.money(tv(s[`Horizon VaR ${a}%`]))} with ${100 - a}% prob.` })}
      ${metric({ label: `Horizon CVaR ${a}%`, value: s[`Horizon CVaR ${a}%`], tipKey: "cvar", tint: "231,71,175" })}
      ${metric({ label: "5th – 95th pct", value: s["5th percentile value"], format: "money", tint: "56,217,245", foot: `up to ${fmt.money(s["95th percentile value"])}` })}
      ${metric({ label: "P(drawdown > 20%)", value: s["P(max drawdown > 20%)"], tipKey: "mdd", tint: "65,105,255", foot: `median max DD ${fmt.pct(s["Median max drawdown"])}` })}
    </div>
    <div class="glass card"><div class="card-head"><div><h3>Simulated wealth paths</h3><p class="desc">${mc.sample.length} sample paths with percentile bands from all ${mc.n_paths.toLocaleString()}.</p></div>${SOURCE.sim}</div><div class="chart tall" id="mc-fan"></div></div>
    <div class="grid g-2">
      <div class="glass card"><div class="card-head"><div><h3>Terminal wealth distribution</h3><p class="desc">Red: outcomes below the ${a}% VaR.</p></div>${SOURCE.sim}</div><div class="chart" id="mc-term"></div></div>
      <div class="glass card"><div class="card-head"><div><h3>Maximum drawdown distribution</h3><p class="desc">Worst peak-to-trough fall along each path.</p></div>${SOURCE.sim}</div><div class="chart" id="mc-dd"></div></div>
    </div>`;
  animateCounters($("#mc-m"));
  fan("mc-fan", mc);
  histogram("mc-term", mc.terminal_hist.counts, mc.terminal_hist.edges, { xfmt: "$,.0f",
    vlines: [{ x: tv(s[`Horizon VaR ${a}%`]), label: `VaR ${a}% ` }] });
  histogram("mc-dd", mc.drawdown_hist.counts, mc.drawdown_hist.edges, { xfmt: ".0%" });
}
