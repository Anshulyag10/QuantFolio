// Entry point: hash router (#/ landing, #/app/<view>), sidebar, bootstrapping.
import { api } from "./api.js";
import { enterLanding, initLanding } from "./landing.js";
import { state } from "./store.js";
import { $, $$, esc, initTooltips, toast } from "./ui.js";
import backtest from "./views/backtest.js";
import experiments from "./views/experiments.js";
import montecarlo from "./views/montecarlo.js";
import optimise from "./views/optimise.js";
import overview from "./views/overview.js";
import risk from "./views/risk.js";
import strategies from "./views/strategies.js";
import universe from "./views/universe.js";

const VIEWS = { overview, universe, optimise, strategies, backtest, risk, montecarlo, experiments };
const NAMES = { overview: "Overview", universe: "Asset Universe", optimise: "Optimisation", strategies: "Strategies",
  backtest: "Backtesting", risk: "Risk Analytics", montecarlo: "Monte Carlo", experiments: "Experiments" };

let cleanup = null;

function buildSidebar() {
  $("#side-nav").innerHTML = Object.keys(VIEWS).map((k, i) =>
    `<a href="#/app/${k}" data-view="${k}" title="${NAMES[k]}"><span class="n">${String(i + 1).padStart(2, "0")}</span><span class="lbl">${NAMES[k]}</span></a>`).join("");
  const app = $("#app");
  $("#collapse-btn").addEventListener("click", () => {
    app.classList.toggle("collapsed");
    $("#collapse-btn").setAttribute("aria-expanded", !app.classList.contains("collapsed"));
    try { localStorage.setItem("qf-side", app.classList.contains("collapsed") ? "c" : "o"); } catch (e) { /* storage blocked */ }
    setTimeout(() => window.dispatchEvent(new Event("resize")), 280);
  });
  try { if (localStorage.getItem("qf-side") === "c") app.classList.add("collapsed"); } catch (e) { /* storage blocked */ }
  const close = () => { app.classList.remove("nav-open"); $("#scrim").hidden = true; };
  $("#menu-btn").addEventListener("click", () => { app.classList.add("nav-open"); $("#scrim").hidden = false; });
  $("#scrim").addEventListener("click", close);
  $("#side-nav").addEventListener("click", (e) => { if (e.target.closest("a")) close(); });
}

function updateDataPill() {
  const c = state.config;
  $("#data-pill").textContent = c.offline ? "Offline · bundled snapshot" : "Live · Yahoo Finance";
  $("#appbar-meta").innerHTML = `<span class="badge">${c.tickers.length} assets</span><span class="badge">${c.offline ? "Bundled snapshot" : "Yahoo Finance"}</span>`;
}

function route() {
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/app\/(\w+)/);
  if (cleanup) { cleanup(); cleanup = null; }
  if (!m) {
    $("#app").hidden = true;
    $("#landing").hidden = false;
    window.scrollTo(0, 0);
    enterLanding();
    return;
  }
  const key = VIEWS[m[1]] ? m[1] : "overview";
  $("#landing").hidden = true;
  $("#app").hidden = false;
  $$("#side-nav a").forEach((a) => (a.dataset.view === key ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  const view = VIEWS[key];
  $("#view-title").textContent = NAMES[key];
  $("#view-kicker").textContent = view.kicker;
  document.title = `${NAMES[key]} · QuantFolio`;
  updateDataPill();
  const host = $("#view");
  host.className = "view";
  host.innerHTML = "";
  window.scrollTo(0, 0);
  void host.offsetWidth;
  host.classList.add("view-enter");
  cleanup = view.mount(host) || null;
  host.focus({ preventScroll: true });
}

function initScrollLinks() {
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-scroll]");
    if (!a) return;
    e.preventDefault();
    if (!$("#landing").hidden) document.querySelector(a.getAttribute("href"))?.scrollIntoView({ behavior: "smooth" });
  });
}

async function boot() {
  initTooltips();
  initScrollLinks();
  initLanding();
  buildSidebar();
  try {
    state.meta = await api.meta();
    state.config.tickers = [...state.meta.default_universe];
    if (!state.meta.snapshot_available) state.config.offline = false;
  } catch (e) {
    toast(e.message, "error");
    $("#view").innerHTML = `<div class="empty"><h3>Server unavailable</h3><p>${esc(e.message)}</p></div>`;
  }
  window.addEventListener("hashchange", route);
  window.addEventListener("qf:config", updateDataPill);
  route();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
