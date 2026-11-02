"""QuantFolio web server: a JSON API over the existing `portfolio` engine plus the static frontend in web/.

    python server.py                      # http://127.0.0.1:8000
    python server.py --port 8080

Every number the frontend shows comes from these endpoints, which call the same functions as
run_analysis.py / app.py (or read the saved outputs of run_experiments.py). Nothing is hard-coded.
"""
from __future__ import annotations

import argparse
import json
import math
import threading
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from portfolio import optimizers as opt
from portfolio.data import (SNAPSHOT_PATH, TRADING_DAYS, download_prices, download_risk_free, prepare_prices,
                            to_returns)
from portfolio.estimators import COV_METHODS, MU_METHODS, covariance, expected_returns
from portfolio.pipeline import DEFAULT_BACKTEST, DEFAULT_UNIVERSE, STRESS_START, PortfolioConfig, run_pipeline
from portfolio.report import strategist_brief
from portfolio.risk import daily_rf, drawdown
from portfolio.simulation import simulate_paths, summarize_paths

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
EXPERIMENTS = ROOT / "results" / "experiments"
app = FastAPI(title="QuantFolio API", version="1.0")


# ------------------------------------------------------------------ helpers
def clean(x):
    """JSON-safe: numpy -> python, NaN/inf -> None, recursively."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else round(x, 8)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.strftime("%Y-%m-%d")
    if isinstance(x, np.ndarray):
        return clean(x.tolist())
    return x


def series(s: pd.Series, step: int = 1) -> dict:
    s = s.dropna()
    if step > 1:
        s = pd.concat([s.iloc[::step], s.iloc[-1:]]).loc[lambda z: ~z.index.duplicated()]
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": clean(s.values.round(6))}


def frame(df: pd.DataFrame) -> dict:
    return {"index": [str(i) for i in df.index], "columns": [str(c) for c in df.columns],
            "data": clean(df.values)}


@lru_cache(maxsize=16)
def load(tickers: tuple[str, ...], start: str, end: str | None, offline: bool):
    raw = download_prices(list(tickers), start, end, offline=offline)
    rf = download_risk_free(start, end, offline=offline)
    return raw, rf


class Memo:
    """Results cache keyed by the exact request. Concurrent identical requests wait for one computation."""

    def __init__(self, size: int = 48):
        self.size, self.data, self.locks, self.guard = size, {}, {}, threading.Lock()

    def get(self, key: str, compute):
        with self.guard:
            if key in self.data:
                return self.data[key]
            lock = self.locks.setdefault(key, threading.Lock())
        with lock:
            if key in self.data:
                return self.data[key]
            value = compute()
            with self.guard:
                if len(self.data) >= self.size:
                    self.data.pop(next(iter(self.data)))
                self.data[key] = value
            return value


MEMO = Memo()


class Config(BaseModel):
    tickers: list[str] = Field(default_factory=lambda: list(DEFAULT_UNIVERSE))
    start: str = "2010-01-01"
    end: str | None = None
    offline: bool = True
    capital: float = 100_000.0
    risk_appetite: str = "moderate"
    method: str = "max_sharpe"
    mu_method: str = "james_stein"
    cov_method: str = "ledoit_wolf"
    max_weight: float | None = None
    risk_aversion: float | None = None
    cvar_beta: float = 0.95
    views: str = ""
    lookback: int = 504
    oos_start: str | None = None   # optional holdout date: optimise on data before it, backtest from it
    rebalance_every: int = 21
    cost_bps: float = 10.0
    benchmark: str = "SPY"
    run_backtest: bool = False
    backtest_methods: list[str] = Field(default_factory=list)
    mc_method: str = "bootstrap"
    mc_paths: int = 2000
    mc_horizon: int = 252


def fetch(cfg: Config):
    tickers = list(dict.fromkeys(t.strip().upper() for t in cfg.tickers if t.strip()))
    if len(tickers) < 2:
        raise HTTPException(400, "Select at least two assets.")
    allt = tuple(sorted(set(tickers) | {cfg.benchmark.upper()}))
    raw, rf = load(allt, min(cfg.start, STRESS_START), cfg.end, cfg.offline)
    if raw.empty:
        raise HTTPException(503, "No price data: Yahoo unreachable and no snapshot. Switch on offline mode.")
    return tickers, raw, rf


def mc_payload(paths: np.ndarray, capital: float, alpha: float, method: str, n_show: int = 40) -> dict:
    T = paths.shape[1]
    step = max(1, T // 120)
    idx = np.unique(np.r_[np.arange(0, T, step), T - 1])
    q = np.quantile(paths[:, idx], [0.05, 0.25, 0.5, 0.75, 0.95], axis=0) * capital
    sample = paths[:n_show][:, idx] * capital
    terminal = paths[:, -1] * capital
    mdd = (paths / np.maximum.accumulate(paths, axis=1) - 1).min(axis=1)
    th, te = np.histogram(terminal, bins=60)
    dh, de = np.histogram(mdd, bins=40)
    return {"days": idx.tolist(), "bands": {"p5": q[0], "p25": q[1], "p50": q[2], "p75": q[3], "p95": q[4]},
            "sample": sample, "terminal_hist": {"counts": th, "edges": te},
            "drawdown_hist": {"counts": dh, "edges": de},
            "summary": summarize_paths(paths, capital, alpha), "n_paths": int(paths.shape[0]),
            "horizon": int(T - 1), "alpha": alpha, "capital": capital, "method": method}


# ------------------------------------------------------------------- routes
@app.get("/api/meta")
def meta():
    manifest = pd.read_csv(SNAPSHOT_PATH.parent / "snapshot_manifest.csv") if SNAPSHOT_PATH.exists() else pd.DataFrame()
    return clean({
        "methods": opt.METHODS, "mu_methods": MU_METHODS, "cov_methods": COV_METHODS,
        "risk_profiles": opt.RISK_PROFILES, "default_universe": DEFAULT_UNIVERSE,
        "default_backtest": DEFAULT_BACKTEST,
        "snapshot": manifest.to_dict(orient="records") if not manifest.empty else [],
        "snapshot_available": SNAPSHOT_PATH.exists(),
        "experiments_available": (EXPERIMENTS / "ablation.csv").exists(),
    })


@app.post("/api/universe")
def universe(cfg: Config):
    tickers, raw, rf = fetch(cfg)
    try:
        prices, synthetic, notes = prepare_prices(raw, tickers, cfg.start, cfg.end, allow_synthetic=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    R = to_returns(prices)
    # Historical statistics use the risk-free rate that prevailed on each day (as the backtest does),
    # not today's rate: subtracting a 2026 T-bill yield from 2010-2026 returns would bias every Sharpe down.
    rf_hist = rf if rf is not None and len(rf) else 0.04
    rf_d = daily_rf(rf_hist, R.index)
    excess = R.sub(rf_d, axis=0)
    rf_avg = float((1 + rf_d).prod() ** (TRADING_DAYS / len(rf_d)) - 1)
    stats = pd.DataFrame({
        "ann_return": R.mean() * TRADING_DAYS,
        "cagr": (prices.iloc[-1] / prices.iloc[0]) ** (TRADING_DAYS / len(R)) - 1,
        "volatility": R.std() * np.sqrt(TRADING_DAYS),
        "max_drawdown": [drawdown(R[c]).min() for c in R],
        "last_price": prices.iloc[-1],
    })
    stats["sharpe"] = excess.mean() / excess.std() * np.sqrt(TRADING_DAYS)
    norm = prices / prices.iloc[0] * 100
    step = max(1, len(norm) // 600)
    return clean({
        "tickers": list(prices.columns), "start": prices.index[0], "end": prices.index[-1],
        "observations": len(R), "rf": rf_avg, "notes": notes,
        "stats": stats.reset_index(names="ticker").to_dict(orient="records"),
        "prices": {t: series(norm[t], step) for t in norm.columns},
        "correlation": frame(R.corr().round(4)),
    })


@app.post("/api/analyze")
def analyze(cfg: Config):
    key = json.dumps(cfg.model_dump(), sort_keys=True)
    return MEMO.get(key, lambda: _analyze(cfg))


def _analyze(cfg: Config):
    tickers, raw, rf = fetch(cfg)
    pc = PortfolioConfig(
        tickers=tickers, start=cfg.start, end=cfg.end, capital=cfg.capital, risk_appetite=cfg.risk_appetite,
        method=cfg.method, mu_method=cfg.mu_method, cov_method=cfg.cov_method, max_weight=cfg.max_weight,
        risk_aversion=cfg.risk_aversion, views=opt.parse_views(cfg.views), lookback=cfg.lookback,
        rebalance_every=cfg.rebalance_every, cost_bps=cfg.cost_bps, benchmark=cfg.benchmark.upper(),
        backtest_methods=cfg.backtest_methods, run_backtest=cfg.run_backtest, mc_method=cfg.mc_method,
        mc_paths=cfg.mc_paths, mc_horizon=cfg.mc_horizon, offline=cfg.offline, allow_synthetic=False,
        cvar_beta=cfg.cvar_beta, oos_start=cfg.oos_start or None)
    try:
        res = run_pipeline(pc, raw_prices=raw, rf_series=rf)
    except ValueError as e:
        raise HTTPException(400, str(e))

    w = res.allocation.weights
    train = res.returns.loc[:pd.Timestamp(cfg.oos_start) - pd.Timedelta(days=1)] if cfg.oos_start else res.returns
    window = train.iloc[-cfg.lookback:]
    hist_port = res.returns @ w
    out = {
        "config": cfg.model_dump(), "notes": res.notes, "rf": res.rf,
        "data_range": [res.prices.index[0], res.prices.index[-1]], "assets": list(res.prices.columns),
        "estimation": {"start": window.index[0], "end": window.index[-1]},   # data the allocation was fitted on
        "split": cfg.oos_start or None,
        "weights": w.to_dict(),
        "asset_stats": res.asset_stats.reset_index(names="ticker").to_dict(orient="records"),
        "risk_contrib": res.risk_contrib.reset_index(names="ticker").to_dict(orient="records"),
        "ex_ante": res.ex_ante,
        "frontier": res.frontier.to_dict(orient="list"),
        "correlation": frame(window.corr().round(4)),
        "historical": {   # today's weights applied to past data (not a backtest)
            "returns_hist": dict(zip(["counts", "edges"], np.histogram(hist_port, bins=80))),
            "rolling_vol": series(hist_port.rolling(63).std() * np.sqrt(TRADING_DAYS), 5),
            "drawdown": series(drawdown(hist_port), 5),
            "max_drawdown": float(drawdown(hist_port).min()),
        },
        "stress": res.stress_hist.reset_index().to_dict(orient="records") if not res.stress_hist.empty else [],
        "shock": res.stress_shock.reset_index().to_dict(orient="records") if not res.stress_shock.empty else [],
        "trades": res.trades.reset_index(names="ticker").to_dict(orient="records"),
        "trade_summary": res.trade_summary,
        "montecarlo": mc_payload(res.mc_paths, cfg.capital, 0.95, cfg.mc_method),
        "brief": strategist_brief(res),
        "backtest": None,
    }
    if res.backtests:
        bts = res.backtests
        first = next(iter(bts.values())).returns.index[0]
        warm = res.returns.index[max(0, res.returns.index.get_loc(first) - cfg.lookback)]
        curves, dds, rolling = {}, {}, {}
        for m, bt in bts.items():
            wealth = (1 + bt.returns).cumprod()
            curves[m] = series(wealth, 5)
            dds[m] = series(wealth / wealth.cummax().clip(lower=1) - 1, 5)
            ex = bt.returns - daily_rf(res.rf_series if res.rf_series is not None else res.rf, bt.returns.index)
            rolling[m] = series(ex.rolling(252).mean() / ex.rolling(252).std() * np.sqrt(TRADING_DAYS), 5)
        if res.benchmark_returns is not None:
            b = res.benchmark_returns.loc[first:]
            curves[f"{pc.benchmark} (buy & hold)"] = series((1 + b).cumprod(), 5)
            bw = (1 + b).cumprod()
            dds[f"{pc.benchmark} (buy & hold)"] = series(bw / bw.cummax().clip(lower=1) - 1, 5)
        table = res.backtest_table.copy()
        table["Total Return"] = [((1 + bts[m].returns).prod() - 1) if m in bts else
                                 ((1 + res.benchmark_returns.loc[first:]).prod() - 1) for m in table.index]
        annual = pd.DataFrame({m: (1 + bt.returns).groupby(bt.returns.index.year).prod() - 1 for m, bt in bts.items()})
        sel = bts[cfg.method]
        out["backtest"] = {
            "start": first, "warmup_start": warm, "lookback": cfg.lookback,
            "curves": curves, "drawdowns": dds, "rolling_sharpe": rolling,
            "table": frame(table), "annual": frame(annual),
            "weights": {"dates": [d.strftime("%Y-%m-%d") for d in sel.weights.index],
                        "assets": list(sel.weights.columns), "values": clean(sel.weights.T.values)},
            "turnover": series(sel.turnover),
        }
    return clean(out)


class MCRequest(Config):
    weights: dict[str, float] = Field(default_factory=dict)
    alpha: float = 0.95


@app.post("/api/montecarlo")
def montecarlo(req: MCRequest):
    tickers, raw, rf = fetch(req)
    try:
        prices, _, _ = prepare_prices(raw, tickers, req.start, req.end, allow_synthetic=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    R = to_returns(prices)
    if req.oos_start:   # same information set as the optimiser
        R = R.loc[:pd.Timestamp(req.oos_start) - pd.Timedelta(days=1)]
    window = R.iloc[-req.lookback:]
    w = pd.Series(req.weights).reindex(R.columns).fillna(0.0)
    if w.sum() <= 0:
        raise HTTPException(400, "Run an optimisation first (no weights).")
    w = w / w.sum()
    n_paths = int(np.clip(req.mc_paths, 100, 20000))
    horizon = int(np.clip(req.mc_horizon, 5, 2520))
    paths = simulate_paths(R, w, horizon, n_paths, req.mc_method,
                           mu=expected_returns(window, req.mu_method), cov=covariance(window, req.cov_method),
                           rebalance_every=req.rebalance_every, cost_bps=req.cost_bps)
    return clean(mc_payload(paths, req.capital, float(np.clip(req.alpha, 0.5, 0.999)), req.mc_method))


@app.get("/api/experiments")
def experiments():
    if not (EXPERIMENTS / "ablation.csv").exists():
        raise HTTPException(404, "No saved experiments. Run: python run_experiments.py")
    read = lambda n: pd.read_csv(EXPERIMENTS / n, index_col=0)
    out = {"ablation": frame(read("ablation.csv")), "holdout": frame(read("holdout.csv"))}
    for key, name in [("window", "sens_window_sharpe.csv"), ("window_mdd", "sens_window_mdd.csv"),
                      ("costs", "sens_costs_sharpe.csv"), ("cap", "sens_cap_sharpe.csv"),
                      ("cvar", "sens_cvar_beta.csv")]:
        if (EXPERIMENTS / name).exists():
            out[key] = frame(read(name))
    return clean(out)


# The frontend's default configuration (web/js/store.js). Computing it at startup makes the
# landing page, Overview, Strategies and Backtesting load instantly on first visit.
DEFAULT_UI = dict(max_weight=0.35, risk_aversion=4.0)
DEFAULT_COMPARISON = ["equal_weight", "mean_variance", "min_variance", "min_cvar", "hrp", "risk_parity"]


def warm_cache():
    try:
        analyze(Config(**DEFAULT_UI))
        analyze(Config(**DEFAULT_UI, run_backtest=True, backtest_methods=DEFAULT_COMPARISON))
        print("QuantFolio: default analysis and backtest cached.", flush=True)
    except Exception as e:  # warming is best-effort
        print(f"QuantFolio: cache warm-up skipped ({e})", flush=True)


@app.on_event("startup")
def _startup():
    threading.Thread(target=warm_cache, daemon=True).start()


@app.get("/vendor/plotly.min.js")
def plotly_js():
    return FileResponse(Path(plotly.__file__).parent / "package_data" / "plotly.min.js",
                        media_type="application/javascript", headers={"Cache-Control": "public, max-age=604800"})


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")


if __name__ == "__main__":
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    print(f"QuantFolio running at http://{a.host}:{a.port}")
    uvicorn.run(app, host=a.host, port=a.port)
