// Application state: one shared research configuration + the latest results from the backend.
import { api } from "./api.js";
import { toast } from "./ui.js";

export const COMPARISON_SET = ["equal_weight", "mean_variance", "min_variance", "min_cvar", "hrp", "risk_parity"];

const listeners = new Set();
export const state = {
  meta: null,
  config: {
    tickers: [], start: "2010-01-01", end: null, offline: true, capital: 100000,
    risk_appetite: "moderate", method: "max_sharpe", mu_method: "james_stein", cov_method: "ledoit_wolf",
    max_weight: 0.35, risk_aversion: 4, cvar_beta: 0.95, views: "", lookback: 504, oos_start: null, rebalance_every: 21,
    cost_bps: 10, benchmark: "SPY", backtest_methods: [...COMPARISON_SET],
    mc_method: "bootstrap", mc_paths: 2000, mc_horizon: 252,
  },
  result: null,          // last /api/analyze (allocation, risk, Monte Carlo)
  backtest: null,        // last /api/analyze run with the walk-forward backtest
  universe: null,        // last /api/universe
  mc: null,              // last /api/montecarlo
  experiments: null,
  pinned: [],            // optimisation results pinned for comparison
  busy: {},              // { analyze: "message" | null, backtest: ..., mc: ... }
};

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit(key) { listeners.forEach((fn) => fn(key)); }
export function setConfig(patch) { Object.assign(state.config, patch); emit("config"); }
function busy(key, msg) { state.busy[key] = msg; emit("busy"); }

const seq = { analyze: 0, backtest: 0 };
/** Run the full pipeline. `backtest` adds the walk-forward comparison (slower). */
export async function runAnalysis({ backtest = false, methods } = {}) {
  const key = backtest ? "backtest" : "analyze";
  const my = ++seq[key];
  const cfg = { ...state.config, run_backtest: backtest,
    backtest_methods: backtest ? (methods || state.config.backtest_methods) : [] };
  const n = new Set([...cfg.backtest_methods, cfg.method, "equal_weight"]).size;
  busy(key, backtest ? `Walk-forward backtest · ${n} strategies + benchmark` : "Optimising portfolio");
  try {
    const res = await api.analyze(cfg);
    if (my < seq[key]) return state.result;                       // a newer request of this kind superseded it
    state.result = res;                                           // latest allocation + risk
    if (backtest) state.backtest = res;                           // latest walk-forward run (kept separately)
    state.mc = null;
    emit("result");
    return res;
  } catch (e) {
    toast(e.message, "error");
    throw e;
  } finally {
    busy(key, null);
  }
}

export async function runMonteCarlo(params) {
  if (!state.result) { toast("Optimise a portfolio first.", "info"); return; }
  busy("mc", "Simulating wealth paths");
  try {
    state.mc = await api.montecarlo({ ...state.config, ...params, weights: state.result.weights });
    emit("mc");
    return state.mc;
  } catch (e) {
    toast(e.message, "error");
  } finally {
    busy("mc", null);
  }
}

export async function loadUniverse() {
  busy("universe", "Loading prices");
  try {
    state.universe = await api.universe(state.config);
    emit("universe");
    return state.universe;
  } catch (e) {
    toast(e.message, "error");
  } finally {
    busy("universe", null);
  }
}

export async function loadExperiments() {
  if (state.experiments) return state.experiments;
  state.experiments = await api.experiments();
  return state.experiments;
}

/** Fields of the config that make an existing result stale. */
export function resultMatchesConfig() {
  const r = state.result?.config, c = state.config;
  if (!r) return false;
  return ["tickers", "start", "end", "offline", "method", "mu_method", "cov_method", "max_weight", "risk_aversion",
    "cvar_beta", "views", "lookback", "oos_start", "capital"].every((k) => JSON.stringify(r[k]) === JSON.stringify(c[k]));
}
