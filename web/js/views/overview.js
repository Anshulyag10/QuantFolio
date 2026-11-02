// Overview: headline out-of-sample metrics + allocation, correlation and strategy comparison.
import { bars, donut, heatmap, lines } from "../charts.js";
import { runAnalysis, state } from "../store.js";
import { $, animateCounters, emptyPanel, esc, fmt, label, loadingPanel, metric, SOURCE } from "../ui.js";
import { btRow, btTable, ensure, labelled, notesBanner, provenance, warmup, watch } from "./common.js";

export default {
  kicker: "Portfolio intelligence",
  mount(host) {
    host.innerHTML = `
      <div class="row between">
        <p class="micro" id="ov-prov">Loading…</p>
        <button class="btn btn-ghost btn-sm" id="ov-refresh">↻ Re-run with current settings</button>
      </div>
      <div id="ov-notes"></div>
      <section aria-label="Key metrics"><div class="row between" style="margin-bottom:12px"><h2 class="micro" id="ov-mtitle">Out-of-sample performance</h2>${SOURCE.bt}</div>
        <div class="grid g-metrics" id="ov-metrics"></div></section>
      <div class="grid g-12">
        <div class="glass card span-8"><div class="card-head"><div><h3>Portfolio growth</h3><p class="desc">Value of $1 invested, walk-forward with costs. Shaded: initial estimation window.</p></div>${SOURCE.bt}</div><div class="chart tall" id="ov-growth"></div></div>
        <div class="glass card span-4"><div class="card-head"><div><h3>Current allocation</h3><p class="desc" id="ov-alloc-desc"></p></div>${SOURCE.ante}</div><div class="chart tall" id="ov-donut"></div></div>
        <div class="glass card span-6"><div class="card-head"><div><h3>Drawdowns</h3><p class="desc">Fall from the running peak.</p></div>${SOURCE.bt}</div><div class="chart" id="ov-dd"></div></div>
        <div class="glass card span-6"><div class="card-head"><div><h3>Strategy comparison</h3><p class="desc">Out-of-sample Sharpe ratio with 95% block-bootstrap interval.</p></div>${SOURCE.bt}</div><div class="chart" id="ov-cmp"></div></div>
        <div class="glass card span-6"><div class="card-head"><div><h3>Asset correlation</h3><p class="desc">Daily returns over the estimation window.</p></div>${SOURCE.hist}</div><div class="chart tall" id="ov-corr"></div></div>
        <div class="glass card span-6"><div class="card-head"><div><h3>Strategist brief</h3><p class="desc">Generated from the computed figures; every sentence traces to a number.</p></div></div><div class="brief" id="ov-brief"></div></div>
      </div>`;
    $("#ov-refresh").addEventListener("click", async () => {
      await runAnalysis().catch(() => {});
      runAnalysis({ backtest: true }).catch(() => {});
    });
    const off = watch((k) => (k === "result" || k === "busy") && render());
    ensure({ result: true, backtest: true });
    render();
    return off;
  },
};

function render() {
  const res = state.result, bt = state.backtest;
  if (!$("#ov-metrics")) return;
  if (res) {
    $("#ov-prov").textContent = provenance(res);
    $("#ov-notes").innerHTML = notesBanner(res.notes);
    const w = Object.entries(res.weights).filter(([, v]) => v > 0.001);
    $("#ov-alloc-desc").textContent = `${label(res.config.method)} · ${fmt.money(res.config.capital)}`;
    donut("ov-donut", w.map(([t]) => t), w.map(([, v]) => v), { center: `<b>${w.length}</b> assets` });
    heatmap("ov-corr", res.correlation);
    $("#ov-brief").innerHTML = mdToHtml(res.brief);
  } else {
    ["ov-donut", "ov-corr"].forEach((id) => ($(`#${id}`).innerHTML = '<div class="skeleton fill"></div>'));
  }

  if (!bt) {
    const msg = state.busy.backtest;
    $("#ov-metrics").innerHTML = msg ? Array(7).fill('<div class="glass card metric skeleton" style="min-height:104px"></div>').join("") : "";
    const placeholder = msg ? loadingPanel(msg, "Re-estimating every 21 days on past data only") :
      emptyPanel("No backtest yet", "Run the walk-forward comparison to see out-of-sample results.");
    ["ov-growth", "ov-dd", "ov-cmp"].forEach((id) => ($(`#${id}`).innerHTML = id === "ov-growth" ? placeholder : '<div class="skeleton fill"></div>'));
    return;
  }
  const m = bt.config.method, r = btRow(bt, m);
  $("#ov-mtitle").textContent = `Out-of-sample performance · ${label(m)}`;
  $("#ov-metrics").innerHTML = [
    metric({ label: "CAGR", value: r.CAGR, tipKey: "cagr", cls: r.CAGR >= 0 ? "pos" : "neg", foot: `${bt.backtest.start} → ${bt.data_range[1]}` }),
    metric({ label: "Volatility", value: r.Volatility, tipKey: "vol", tint: "56,217,245" }),
    metric({ label: "Sharpe ratio", value: r.Sharpe, format: "num", tipKey: "sharpe", tint: "146,60,255", foot: `95% CI ${fmt.num(r["Sharpe CI low"])} – ${fmt.num(r["Sharpe CI high"])}` }),
    metric({ label: "Sortino ratio", value: r.Sortino, format: "num", tipKey: "sortino", tint: "146,60,255" }),
    metric({ label: "Max drawdown", value: r["Max Drawdown"], tipKey: "mdd", cls: "neg", tint: "255,92,122" }),
    metric({ label: "Total return", value: r["Total Return"], format: "pct", dec: 0, tipKey: "total", cls: "pos", tint: "52,211,153" }),
    metric({ label: "Turnover", value: r["Turnover (ann.)"], format: "x", tipKey: "turnover", tint: "255,138,82", foot: "per year" }),
  ].join("");
  animateCounters($("#ov-metrics"));

  const keep = [m, "equal_weight", ...Object.keys(bt.backtest.curves).filter((k) => k.includes("buy & hold"))];
  const pick = (map) => Object.fromEntries(keep.filter((k) => map[k]).map((k) => [k, map[k]]));
  const wu = warmup(bt);
  lines("ov-growth", labelled(pick(bt.backtest.curves)), { yfmt: "$.2f", log: true, highlight: label(m), ...wu });
  lines("ov-dd", labelled(pick(bt.backtest.drawdowns)), { yfmt: ".0%", fill: true, highlight: label(m) });
  const rows = btTable(bt).filter((x) => x["Sharpe CI low"] != null);
  rows.sort((a, b) => b.Sharpe - a.Sharpe);
  bars("ov-cmp", rows.map((x) => label(x._id)), [rows.map((x) => x.Sharpe)], { horizontal: true,
    errors: [{ plus: rows.map((x) => x["Sharpe CI high"] - x.Sharpe), minus: rows.map((x) => x.Sharpe - x["Sharpe CI low"]) }],
  });
}

/** Minimal markdown (## headings, **bold**, _italic_, paragraphs) for the engine's brief. */
export function mdToHtml(md) {
  return esc(md).split(/\n\n+/).map((p) => p.startsWith("## ") ? `<h2>${p.slice(3)}</h2>` : `<p>${p}</p>`).join("")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|\s)_(.+?)_(?=\s|$|<)/g, "$1<em>$2</em>");
}
