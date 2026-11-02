// Asset universe: dataset choice, search/add/remove assets, per-asset statistics, prices and correlations.
import { heatmap, lines, plot, colorFor } from "../charts.js";
import { loadUniverse, setConfig, state } from "../store.js";
import { $, $$, downloadCSV, emptyPanel, esc, fmt, loadingPanel, setBusy, SOURCE, table, toast } from "../ui.js";
import { notesBanner, watch } from "./common.js";

let selected = null;

export default {
  kicker: "Data",
  mount(host) {
    const c = state.config;
    selected = new Set(c.tickers);
    const snap = state.meta?.snapshot || [];
    const cats = [...new Set(snap.map((r) => r.category))].sort();
    host.innerHTML = `
      <div class="workbench">
        <div class="glass controls" aria-label="Universe settings">
          <h3>Dataset</h3>
          <label class="toggle"><input type="checkbox" id="u-offline" ${c.offline ? "checked" : ""}> Offline · bundled snapshot</label>
          <p class="source-note" style="margin:-8px 0 0">${state.meta?.snapshot_available ? `${snap.length} assets saved locally. Off = live Yahoo Finance, falling back to the snapshot per asset.` : "No snapshot found: live data only."}</p>
          <div class="two">
            <label class="field"><span>Start</span><input class="input" type="date" id="u-start" value="${c.start}" min="2005-01-01"></label>
            <label class="field"><span>End</span><input class="input" type="date" id="u-end" value="${c.end || ""}"></label>
          </div>
          <hr>
          <div class="field"><span>Selected · <b id="u-count"></b></span><div class="row" id="u-selected"></div></div>
          <label class="field"><span>Search or add a ticker</span><input class="input" id="u-search" placeholder="e.g. GLD, energy, XOM" autocomplete="off"></label>
          <div class="assets-pick" id="u-pick"></div>
          <div class="row"><button class="btn btn-ghost btn-sm" id="u-reset" type="button">Reset to default</button></div>
          <button class="btn btn-primary btn-run" id="u-apply" type="button"><span class="spinner" aria-hidden="true"></span><span class="lbl" data-idle="Load universe">Load universe</span></button>
          <p class="source-note">Loading a new universe clears previous optimisation and backtest results so nothing stale is shown.</p>
        </div>
        <div class="results" id="u-results" aria-live="polite"></div>
      </div>`;

    const drawPick = () => {
      const q = $("#u-search").value.trim().toLowerCase();
      const match = (r) => !q || r.ticker.toLowerCase().includes(q) || r.category.toLowerCase().includes(q);
      $("#u-pick").innerHTML = cats.map((cat) => {
        const items = snap.filter((r) => r.category === cat && match(r));
        return items.length ? `<span class="cat-title">${esc(cat)}</span>${items.map((r) =>
          `<button type="button" class="chip ${selected.has(r.ticker) ? "on" : ""}" data-t="${esc(r.ticker)}" aria-pressed="${selected.has(r.ticker)}" title="${esc(r.category)} · ${r["first date"]} → ${r["last date"]}">${esc(r.ticker)}</button>`).join("")}` : "";
      }).join("") || `<p class="source-note">No bundled asset matches. Press Enter to add “${esc(q.toUpperCase())}” from Yahoo (live mode).</p>`;
      $("#u-selected").innerHTML = [...selected].map((t) => `<button type="button" class="chip on" data-t="${esc(t)}" aria-label="Remove ${esc(t)}">${esc(t)} <span class="x">×</span></button>`).join("");
      $("#u-count").textContent = `${selected.size} assets`;
    };
    const toggle = (e) => {
      const b = e.target.closest(".chip");
      if (!b) return;
      const t = b.dataset.t;
      selected.has(t) ? selected.delete(t) : selected.add(t);
      drawPick();
    };
    $("#u-pick").addEventListener("click", toggle);
    $("#u-selected").addEventListener("click", toggle);
    $("#u-search").addEventListener("input", drawPick);
    $("#u-search").addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const t = e.target.value.trim().toUpperCase();
      if (!/^[A-Z0-9.^=-]{1,12}$/.test(t)) return;
      const inSnap = snap.some((r) => r.ticker === t);
      if (!inSnap && $("#u-offline").checked) { toast(`${t} is not in the snapshot; switch off offline mode to fetch it live.`, "info"); return; }
      selected.add(t); e.target.value = ""; drawPick();
    });
    $("#u-reset").addEventListener("click", () => { selected = new Set(state.meta.default_universe); drawPick(); });
    $("#u-apply").addEventListener("click", async () => {
      if (selected.size < 2) { toast("Select at least two assets.", "error"); return; }
      const start = $("#u-start").value, end = $("#u-end").value || null;
      if (end && end <= start) { toast("End date must be after the start date.", "error"); return; }
      setConfig({ tickers: [...selected], offline: $("#u-offline").checked, start, end });
      if (!state.config.tickers.includes(state.config.benchmark) && !snap.some((r) => r.ticker === state.config.benchmark)) setConfig({ benchmark: "SPY" });
      Object.assign(state, { result: null, backtest: null, mc: null });
      window.dispatchEvent(new Event("qf:config"));
      const u = await loadUniverse();
      if (u) toast(`Loaded ${u.tickers.length} assets · ${u.observations.toLocaleString()} days`);
    });
    drawPick();

    const off = watch((k) => {
      if (k === "busy") setBusy($("#u-apply"), state.busy.universe, "Loading…");
      if (k === "universe" || (k === "busy" && !state.universe)) render();
    });
    if (!state.universe && !state.busy.universe) loadUniverse();
    render();
    return off;
  },
};

function render() {
  const host = $("#u-results");
  if (!host) return;
  const u = state.universe;
  if (!u) { host.innerHTML = state.busy.universe ? loadingPanel("Loading prices") : emptyPanel("No data loaded", "Choose assets and press <b>Load universe</b>."); return; }
  const cols = [
    { key: "ticker", label: "Asset" }, { key: "cagr", label: "CAGR", fmt: (v) => `<span class="${v >= 0 ? "pos" : "neg"}">${fmt.pct(v)}</span>` },
    { key: "ann_return", label: "Mean return", fmt: (v) => fmt.pct(v) }, { key: "volatility", label: "Volatility", fmt: (v) => fmt.pct(v) },
    { key: "sharpe", label: "Sharpe", fmt: (v) => fmt.num(v) }, { key: "max_drawdown", label: "Max DD", fmt: (v) => `<span class="neg">${fmt.pct(v)}</span>` },
    { key: "last_price", label: "Last price", fmt: (v) => fmt.money(v, 2) },
  ];
  host.innerHTML = `
    ${notesBanner(u.notes)}
    <p class="micro">${u.tickers.length} assets · ${u.start} → ${u.end} · ${u.observations.toLocaleString()} daily returns · ${state.config.offline ? "bundled snapshot" : "Yahoo Finance"}</p>
    <div class="glass card"><div class="card-head"><div><h3>Asset statistics</h3><p class="desc">Annualised from daily total returns over the common history. Sharpe subtracts each day's 13-week T-bill rate (average ${fmt.pct(u.rf, 2)} a year over this period).</p></div>
      <div class="row">${SOURCE.hist}<button class="link-btn" id="u-csv">Download CSV</button></div></div><div id="u-table"></div></div>
    <div class="glass card"><div class="card-head"><div><h3>Historical prices</h3><p class="desc">Rebased to 100 (log scale). Hover a line to isolate it; click legend items to show or hide assets.</p></div>${SOURCE.hist}</div><div class="chart tall" id="u-prices"></div></div>
    <div class="grid g-2">
      <div class="glass card"><div class="card-head"><h3>Risk vs return</h3>${SOURCE.hist}</div><div class="chart" id="u-scatter"></div></div>
      <div class="glass card"><div class="card-head"><h3>Correlation matrix</h3>${SOURCE.hist}</div><div class="chart" id="u-corr"></div></div>
    </div>`;
  table($("#u-table"), cols, u.stats);
  $("#u-csv").addEventListener("click", () => downloadCSV("quantfolio_universe.csv", cols, u.stats));
  lines("u-prices", u.prices, { yfmt: ",.0f", log: true, focus: true });
  plot("u-scatter", [{ type: "scatter", mode: "markers+text", x: u.stats.map((s) => s.volatility), y: u.stats.map((s) => s.cagr), text: u.stats.map((s) => s.ticker),
    textposition: "top center", textfont: { size: 10, color: "#4A5D55", family: "JetBrains Mono, monospace" }, marker: { size: 8, color: "#FDFBF7", line: { width: 1.2, color: "#1A2E26" } },
    hovertemplate: "<b>%{text}</b><br>vol %{x:.1%} · CAGR %{y:.1%}<extra></extra>" }],
  { hovermode: "closest", xaxis: { tickformat: ".0%", title: { text: "Volatility" } }, yaxis: { tickformat: ".0%", title: { text: "CAGR" } } });
  heatmap("u-corr", u.correlation);
}
