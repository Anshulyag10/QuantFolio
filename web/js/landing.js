// Landing page: live hero computation + research highlights from saved experiment outputs.
import { bars, colorFor, frontier } from "./charts.js";
import { loadExperiments, runAnalysis, state } from "./store.js";
import { $, $$, esc, fmt, frameRows, label } from "./ui.js";

let started = false;

export function initLanding() { /* static editorial layout: no scroll effects */ }

export async function enterLanding() {
  observeReveals(document.getElementById("landing"));
  if (started) return;
  started = true;
  heroStats();
  hero();
  research();
}

export function observeReveals(root) {
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }), { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  $$(".reveal", root).forEach((el, i) => {
    if (!el.style.getPropertyValue("--d")) el.style.setProperty("--d", `${(i % 6) * 0.07}s`);
    io.observe(el);
  });
}

function heroStats() {
  const m = state.meta;
  if (!m) return;
  const first = m.snapshot.map((r) => r["first date"]).sort()[0];
  const last = m.snapshot.map((r) => r["last date"]).sort().at(-1);
  const years = first && last ? (new Date(last) - new Date(first)) / (365.25 * 864e5) : NaN;
  const items = [
    ["Bundled assets", m.snapshot.length, (x) => Math.round(x)],
    ["Portfolio rules", Object.keys(m.methods).length, (x) => Math.round(x)],
    ["Years of daily data", years, (x) => x.toFixed(0)],
  ];
  $("#hero-stats").innerHTML = items.map(([k, v, f]) => `<div><dt>${k}</dt><dd>${f(v)}</dd></div>`).join("");
}

async function hero() {
  try {
    const res = state.result || await runAnalysis();
    const ea = res.ex_ante;
    $("#hero-card-title").textContent = `Efficient frontier · ${label(res.config.method)}`;
    frontier("hero-frontier", res.frontier, res.asset_stats,
      { vol: ea["Volatility (ann.)"], ret: ea["Expected return (ann.)"] }, res.rf, { legend: false });
    const w = Object.entries(res.weights).filter(([, v]) => v > 0.002).sort((a, b) => b[1] - a[1]);
    $("#hero-alloc").innerHTML = w.map(([t, v], i) =>
      `<span style="flex-grow:${v};background:${colorFor(i)}" title="${esc(t)} ${fmt.pct(v)}"></span>`).join("");
    $("#chip-1").innerHTML = `<span class="k">Ex-ante Sharpe</span><span class="v num">${fmt.num(ea["Sharpe (ex-ante)"])}</span><span class="s">at rf ${fmt.pct(res.rf, 2)}</span>`;
    $("#chip-2").innerHTML = `<span class="k">1-day VaR 95%</span><span class="v num">${fmt.pct(ea["VaR 95% 1d (historical)"], 2)}</span><span class="s">historical simulation</span>`;
    $("#hero-source").innerHTML = `<b>Fig. 1.</b> Long-only efficient frontier for ${res.assets.length} multi-asset ETFs, with the capital market line. `
      + `The square marks the maximum-Sharpe portfolio: expected return ${fmt.pct(ea["Expected return (ann.)"])}, volatility ${fmt.pct(ea["Volatility (ann.)"])}, `
      + `ex-ante Sharpe ${fmt.num(ea["Sharpe (ex-ante)"])}. Computed live from ${res.config.offline ? "the bundled snapshot" : "Yahoo Finance"}, ${res.data_range[0]} to ${res.data_range[1]}. Bar: allocation.`;
  } catch (e) {
    $("#hero-card-title").textContent = "Engine offline";
    $("#hero-frontier").innerHTML = `<p class="source-note" style="padding:20px">${esc(e.message)}</p>`;
  }
}

async function research() {
  const grid = $("#research-grid");
  let ex;
  try { ex = await loadExperiments(); } catch (e) {
    grid.innerHTML = `<div class="stat-tile" style="grid-column:1/-1"><p>${esc(e.message)}</p></div>`;
    $("#research-chart").innerHTML = "";
    return;
  }
  const rows = Object.fromEntries(frameRows(ex.ablation).map((r) => [r._id, r]));
  const hold = frameRows(ex.holdout);
  const holm = Math.min(...Object.values(rows).map((r) => r["p Holm vs 1/N"]).filter((x) => x != null));
  const rho = spearman(hold.map((r) => r["Sharpe (selection)"]), hold.map((r) => r["Sharpe (holdout)"]));
  const tiles = [
    { big: fmt.pct(rows.E9["Max Drawdown"], 1), c: "", text: `Max drawdown of minimum-CVaR, vs <b>${fmt.pct(rows.E0["Max Drawdown"], 1)}</b> for equal weight.` },
    { big: `${fmt.num(rows.E1.Sharpe)} → ${fmt.num(rows.E3.Sharpe)}`, c: "", text: "Mean-variance Sharpe when Bayes-Stein shrinks the noisy expected returns." },
    { big: fmt.num(holm, 2), c: "", text: "Smallest Holm-adjusted p-value vs 1/N: no strategy is significant after correcting for multiple tests." },
    { big: fmt.num(rho, 2), c: "", text: "Rank correlation between pre-2022 and untouched 2022+ Sharpe ratios: past rankings did not persist." },
  ];
  grid.innerHTML = tiles.map((t) => `<div class="stat-tile"><span class="big">${t.big}</span><p>${t.text}</p><span class="src">Walk-forward, after 10 bps costs</span></div>`).join("");
  observeReveals(grid);
  const ids = Object.keys(rows);
  bars("research-chart", ids.map((k) => `${k} ${rows[k].experiment.replace(/\s+/g, " ")}`), [ids.map((k) => rows[k].Sharpe)], {
    errors: [{ plus: ids.map((k) => rows[k]["Sharpe CI high"] - rows[k].Sharpe), minus: ids.map((k) => rows[k].Sharpe - rows[k]["Sharpe CI low"]) }],
    horizontal: true,
  });
}

function spearman(a, b) {
  const rank = (v) => { const s = [...v].map((x, i) => [x, i]).sort((p, q) => p[0] - q[0]); const r = []; s.forEach(([, i], k) => (r[i] = k + 1)); return r; };
  const ra = rank(a), rb = rank(b), n = a.length, ma = (n + 1) / 2;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) { num += (ra[i] - ma) * (rb[i] - ma); da += (ra[i] - ma) ** 2; db += (rb[i] - ma) ** 2; }
  return num / Math.sqrt(da * db);
}
