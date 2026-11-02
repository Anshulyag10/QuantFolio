// Optimisation workspace: every control maps to a parameter of portfolio.optimizers.optimize / PortfolioConfig.
import { donut, frontier } from "../charts.js";
import { runAnalysis, setConfig, state } from "../store.js";
import { $, animateCounters, bindRange, downloadCSV, emptyPanel, esc, fmt, label, loadingPanel, metric, segmented, setBusy, SOURCE, table, tip, toast } from "../ui.js";
import { notesBanner, provenance, splitField, watch, weightsRows } from "./common.js";

const METHODS = ["mean_variance", "min_variance", "max_sharpe", "min_cvar", "risk_parity", "hrp", "black_litterman",
  "max_diversification", "inverse_vol", "equal_weight"];
const USES = {
  gamma: ["mean_variance", "black_litterman"], cvar: ["min_cvar"], views: ["black_litterman"],
  mu: ["mean_variance", "max_sharpe"], cap: METHODS.filter((m) => m !== "equal_weight"),
};

export default {
  kicker: "Construct",
  mount(host) {
    const c = state.config, P = state.meta?.risk_profiles || {};
    host.innerHTML = `
      <div class="workbench">
        <form class="glass controls" id="opt-form" aria-label="Optimisation settings">
          <div><h3>Optimiser</h3><p class="source-note" style="margin-top:4px">Long-only, fully invested. Hidden controls do not apply to the selected method.</p></div>
          <div id="opt-method"></div>
          <div class="field"><span>Risk appetite ${tip("Presets for risk aversion γ and the per-asset cap: conservative γ=10, cap 25% · moderate γ=4, 35% · aggressive γ=1.5, 60%.")}</span><div id="opt-appetite"></div></div>
          <label class="field"><span>Investment amount</span><input class="input num" id="opt-capital" type="number" min="1000" step="1000" value="${c.capital}"></label>
          <label class="field" data-uses="cap"><span>Maximum weight per asset <output id="o-cap"></output></span><input type="range" id="opt-cap" min="0.1" max="1" step="0.05" value="${c.max_weight}"></label>
          <label class="field" data-uses="gamma"><span>Risk aversion γ <output id="o-gamma"></output></span><input type="range" id="opt-gamma" min="0.5" max="20" step="0.5" value="${c.risk_aversion}"></label>
          <label class="field" data-uses="cvar"><span>CVaR confidence β</span><select class="select" id="opt-beta">${[0.9, 0.95, 0.99].map((b) => `<option value="${b}" ${b === c.cvar_beta ? "selected" : ""}>${b * 100}%</option>`).join("")}</select></label>
          <label class="field" data-uses="views"><span>Black-Litterman views ${tip("One per line. Absolute: QQQ = 0.12 @ 0.6 (12% return, 60% confidence). Relative: SPY - TLT = 0.03 @ 0.5.")}</span><textarea class="input" id="opt-views" placeholder="QQQ = 0.12 @ 0.6&#10;SPY - TLT = 0.03 @ 0.5">${esc(c.views)}</textarea></label>
          <hr>
          <label class="field"><span>Estimation window <output id="o-lb"></output></span><input type="range" id="opt-lb" min="126" max="1260" step="21" value="${c.lookback}"></label>
          ${splitField("opt-oos", c.oos_start)}
          <div class="two">
            <label class="field" data-uses="mu"><span>Expected returns</span><select class="select" id="opt-mu">${opts(state.meta?.mu_methods, c.mu_method)}</select></label>
            <label class="field"><span>Covariance</span><select class="select" id="opt-cov">${opts(state.meta?.cov_methods, c.cov_method)}</select></label>
          </div>
          <div class="two">
            <label class="field"><span>Rebalance</span><select class="select" id="opt-reb">${[[5, "Weekly"], [21, "Monthly"], [63, "Quarterly"]].map(([v, l]) => `<option value="${v}" ${v === c.rebalance_every ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <label class="field"><span>Costs <output id="o-cost"></output></span><input type="range" id="opt-cost" min="0" max="50" step="1" value="${c.cost_bps}"></label>
          </div>
          <button class="btn btn-primary btn-run" type="submit" id="opt-run"><span class="spinner" aria-hidden="true"></span><span class="lbl" data-idle="Optimise portfolio">Optimise portfolio</span></button>
          <p class="source-note">Rebalance frequency and costs feed the Monte Carlo and backtest; the optimiser itself uses the window, estimators, cap and method parameters.</p>
        </form>
        <div class="results" id="opt-results" aria-live="polite"></div>
      </div>`;

    segmented($("#opt-method"), METHODS.map((m) => [m, label(m)]), c.method, (m) => { setConfig({ method: m }); syncVisibility(); });
    segmented($("#opt-appetite"), Object.keys(P).map((k) => [k, k[0].toUpperCase() + k.slice(1)]), c.risk_appetite, (k) => {
      setConfig({ risk_appetite: k, max_weight: P[k].max_weight, risk_aversion: P[k].risk_aversion });
      $("#opt-cap").value = P[k].max_weight; $("#opt-gamma").value = P[k].risk_aversion;
      ["#opt-cap", "#opt-gamma"].forEach((s) => $(s).dispatchEvent(new Event("input")));
    });
    bindRange($("#opt-cap"), $("#o-cap"), (v) => fmt.pct(v, 0));
    bindRange($("#opt-gamma"), $("#o-gamma"), (v) => v.toFixed(1));
    bindRange($("#opt-lb"), $("#o-lb"), (v) => `${v} d · ${(v / 252).toFixed(1)} y`);
    bindRange($("#opt-cost"), $("#o-cost"), (v) => `${v} bps`);
    syncVisibility();

    $("#opt-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const capital = +$("#opt-capital").value;
      if (!(capital > 0)) { toast("Investment amount must be positive.", "error"); return; }
      setConfig({
        capital, max_weight: +$("#opt-cap").value, risk_aversion: +$("#opt-gamma").value, cvar_beta: +$("#opt-beta").value,
        views: $("#opt-views").value, lookback: +$("#opt-lb").value, oos_start: $("#opt-oos").value || null, mu_method: $("#opt-mu").value, cov_method: $("#opt-cov").value,
        rebalance_every: +$("#opt-reb").value, cost_bps: +$("#opt-cost").value,
      });
      try { await runAnalysis(); toast(`${label(state.config.method)} optimised`); } catch (err) { /* toast shown by store */ }
    });

    const off = watch((k) => {
      if (k === "busy") {
        setBusy($("#opt-run"), state.busy.analyze, "Optimising…");
        const r = $("#opt-results");
        if (r && r.dataset.has) r.style.opacity = state.busy.analyze ? 0.55 : 1; else render();
      }
      if (k === "result") render();
    });
    render();
    return off;
  },
};

const opts = (map = {}, sel) => Object.entries(map).map(([k, v]) => `<option value="${k}" ${k === sel ? "selected" : ""} title="${esc(v)}">${esc(v.split(" (")[0].split(",")[0])}</option>`).join("");

function syncVisibility() {
  const m = state.config.method;
  document.querySelectorAll("#opt-form [data-uses]").forEach((el) => { el.hidden = !USES[el.dataset.uses].includes(m); });
}

function render() {
  const host = $("#opt-results");
  if (!host) return;
  const res = state.result;
  if (!res) {
    host.innerHTML = state.busy.analyze ? loadingPanel("Solving the optimisation", "cvxpy · convex program") :
      emptyPanel("Ready when you are", "Choose a method and press <b>Optimise portfolio</b>.");
    return;
  }
  host.style.opacity = 1;
  host.dataset.has = "1";
  const ea = res.ex_ante, cfg = res.config;
  host.innerHTML = `
    ${notesBanner(res.notes)}
    <div class="row between"><p class="micro">${esc(label(cfg.method))} · ${provenance(res)}</p>
      <div class="row"><button class="btn btn-ghost btn-sm" id="opt-pin">＋ Pin for comparison</button>
      <a class="btn btn-ghost btn-sm" href="#/app/montecarlo">Simulate →</a></div></div>
    <div class="grid g-metrics" id="opt-metrics">
      ${metric({ label: "Expected return", value: ea["Expected return (ann.)"], tipKey: "cagr", foot: "annualised, shrunk estimate" })}
      ${metric({ label: "Volatility", value: ea["Volatility (ann.)"], tipKey: "vol", tint: "56,217,245" })}
      ${metric({ label: "Sharpe (ex-ante)", value: ea["Sharpe (ex-ante)"], format: "num", tipKey: "sharpe", tint: "146,60,255", foot: `rf ${fmt.pct(res.rf, 2)}` })}
      ${metric({ label: "1-day VaR 95%", value: ea["VaR 95% 1d ($, historical)"], format: "money", tipKey: "var", tint: "255,92,122", foot: "historical simulation" })}
      ${metric({ label: "Effective N", value: ea["Effective N (1/HHI)"], format: "num", dec: 1, tipKey: "effn", tint: "255,138,82" })}
      ${metric({ label: "Diversification ratio", value: ea["Diversification ratio"], format: "num", tipKey: "dr", tint: "52,211,153" })}
    </div>
    <div class="grid g-12">
      <div class="glass card span-7"><div class="card-head"><div><h3>Weights & risk contribution</h3><p class="desc">Bar = capital weight · thin line = share of portfolio volatility ${tip("rc")}</p></div>${SOURCE.ante}</div><div class="weights-list" id="opt-w"></div></div>
      <div class="glass card span-5"><div class="card-head"><h3>Allocation</h3><span class="micro">${fmt.money(cfg.capital)}</span></div><div class="chart" id="opt-donut"></div></div>
      <div class="glass card span-12"><div class="card-head"><div><h3>Efficient frontier</h3><p class="desc">Long-only frontier under the ${fmt.pct(cfg.max_weight, 0)} cap, with the capital market line.</p></div>${SOURCE.ante}</div><div class="chart tall" id="opt-frontier"></div></div>
      <div class="glass card span-12"><div class="card-head"><div><h3>Trade list</h3><p class="desc">Orders to fund this portfolio from cash (whole shares, ${cfg.cost_bps} bps estimated cost).</p></div><button class="link-btn" id="opt-csv">Download CSV</button></div><div id="opt-trades"></div></div>
      <div class="glass card span-12" id="opt-compare-card" ${state.pinned.length ? "" : "hidden"}><div class="card-head"><div><h3>Pinned comparison</h3><p class="desc">Ex-ante metrics of pinned optimisations.</p></div><button class="link-btn" id="opt-clear">Clear</button></div><div id="opt-compare"></div></div>
    </div>`;
  animateCounters($("#opt-metrics"));

  const rows = weightsRows(res).filter((r) => r.weight > 0.0005 || r.pct_risk > 0.0005);
  $("#opt-w").innerHTML = rows.map((r) => `<div class="wrow"><b>${esc(r.ticker)}</b>
      <div class="wbar"><i style="width:0" data-w="${r.weight}"></i><i class="risk" style="width:0" data-w="${Math.max(0, r.pct_risk)}"></i></div>
      <span>${fmt.pct(r.weight)}</span></div>`).join("");
  requestAnimationFrame(() => document.querySelectorAll("#opt-w i").forEach((i) => (i.style.width = `${Math.min(100, i.dataset.w * 100 / Math.max(...rows.map((r) => Math.max(r.weight, r.pct_risk))))}%`)));
  const nz = rows.filter((r) => r.weight > 0.0005);
  donut("opt-donut", nz.map((r) => r.ticker), nz.map((r) => r.weight));
  frontier("opt-frontier", res.frontier, res.asset_stats, { vol: ea["Volatility (ann.)"], ret: ea["Expected return (ann.)"] }, res.rf);

  const tcols = [
    { key: "ticker", label: "Asset" }, { key: "action", label: "Action", fmt: (v) => `<span class="${v === "BUY" ? "pos" : v === "SELL" ? "neg" : ""}">${v}</span>` },
    { key: "price", label: "Price", fmt: (v) => fmt.money(v, 2) }, { key: "target weight", label: "Target", fmt: (v) => fmt.pct(v) },
    { key: "trade shares", label: "Shares", fmt: (v) => fmt.num(v, 0) }, { key: "trade value", label: "Value", fmt: (v) => fmt.money(v) },
  ];
  const trades = res.trades.filter((t) => t.action !== "HOLD" || t["target weight"] > 0);
  table($("#opt-trades"), tcols, trades);
  $("#opt-csv").addEventListener("click", () => downloadCSV(`quantfolio_trades_${cfg.method}.csv`, tcols, trades));

  $("#opt-pin").addEventListener("click", () => {
    state.pinned.push({ method: label(cfg.method), exp: ea["Expected return (ann.)"], vol: ea["Volatility (ann.)"], sharpe: ea["Sharpe (ex-ante)"],
      var95: ea["VaR 95% 1d (historical)"], cvar95: ea["CVaR 95% 1d (historical)"], effn: ea["Effective N (1/HHI)"], dr: ea["Diversification ratio"],
      cap: cfg.max_weight, window: cfg.lookback, top: Object.entries(res.weights).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([t, w]) => `${t} ${fmt.pct(w, 0)}`).join(", ") });
    toast("Pinned for comparison");
    renderPinned();
  });
  $("#opt-clear").addEventListener("click", () => { state.pinned = []; renderPinned(); });
  renderPinned();
}

function renderPinned() {
  const card = $("#opt-compare-card");
  if (!card) return;
  card.hidden = !state.pinned.length;
  if (!state.pinned.length) return;
  table($("#opt-compare"), [
    { key: "method", label: "Method" }, { key: "exp", label: "Exp. return", fmt: (v) => fmt.pct(v) }, { key: "vol", label: "Volatility", fmt: (v) => fmt.pct(v) },
    { key: "sharpe", label: "Sharpe", fmt: (v) => fmt.num(v) }, { key: "var95", label: "VaR 95%", fmt: (v) => fmt.pct(v, 2) },
    { key: "cvar95", label: "CVaR 95%", fmt: (v) => fmt.pct(v, 2) }, { key: "effn", label: "Eff. N", fmt: (v) => fmt.num(v, 1) },
    { key: "dr", label: "Div. ratio", fmt: (v) => fmt.num(v) }, { key: "cap", label: "Cap", fmt: (v) => fmt.pct(v, 0) },
    { key: "window", label: "Window", fmt: (v) => `${v}d` }, { key: "top", label: "Top holdings", fmt: (v) => esc(v), left: true },
  ], state.pinned);
}
