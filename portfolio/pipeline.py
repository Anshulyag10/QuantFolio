"""End-to-end pipeline: data -> estimation -> allocation -> risk -> backtest -> simulation -> stress -> trades."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import optimizers as opt
from .backtest import BacktestResult, walk_forward
from .data import download_prices, download_risk_free, prepare_prices, to_returns
from .risk import (daily_rf, deflated_sharpe_ratio, ex_ante_report, holm_bonferroni, performance_metrics,
                   risk_contributions, sharpe_bootstrap_ci, sharpe_difference_test)
from .simulation import simulate_paths, summarize_paths
from .stress import historical_stress, market_shock
from .rebalance import rebalance_plan

DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "GLD", "VNQ", "DBC"]
DEFAULT_BACKTEST = ["equal_weight", "inverse_vol", "min_variance", "max_sharpe", "mean_variance",
                    "risk_parity", "hrp", "max_diversification", "min_cvar"]
STRESS_START = "2007-01-01"


@dataclass
class PortfolioConfig:
    tickers: list[str] = field(default_factory=lambda: list(DEFAULT_UNIVERSE))
    start: str = "2010-01-01"
    end: str | None = None
    capital: float = 100_000.0
    risk_appetite: str = "moderate"
    method: str = "max_sharpe"
    mu_method: str = "james_stein"
    cov_method: str = "ledoit_wolf"
    rf: float | None = None                  # None -> latest 13-week T-bill yield
    max_weight: float | None = None          # None -> from risk appetite
    risk_aversion: float | None = None       # None -> from risk appetite
    cvar_beta: float = 0.95                  # confidence level for min_cvar
    views: list[opt.View] = field(default_factory=list)
    holdings: dict[str, float] = field(default_factory=dict)
    cash: float | None = None                # None -> capital (fresh account) when no holdings
    rebalance_threshold: float = 0.02
    benchmark: str = "SPY"
    lookback: int = 504                      # estimation window, used for BOTH today's allocation and the backtest
    oos_start: str | None = None             # e.g. "2022-01-01": optimise on data before it, backtest from it
    rebalance_every: int = 21
    cost_bps: float = 10.0
    backtest_methods: list[str] = field(default_factory=lambda: list(DEFAULT_BACKTEST))
    run_backtest: bool = True
    mc_horizon: int = 252
    mc_paths: int = 5000
    mc_method: str = "bootstrap"
    allow_synthetic: bool = True
    offline: bool = False                    # True -> use only the bundled snapshot in data/


@dataclass
class PipelineResult:
    config: PortfolioConfig
    prices: pd.DataFrame
    returns: pd.DataFrame
    rf: float
    rf_series: pd.Series | None
    allocation: opt.OptimizationResult
    ex_ante: dict
    risk_contrib: pd.DataFrame
    frontier: pd.DataFrame
    asset_stats: pd.DataFrame
    backtests: dict[str, BacktestResult]
    backtest_table: pd.DataFrame
    benchmark_returns: pd.Series | None
    mc_paths: object
    mc_summary: dict
    stress_hist: pd.DataFrame
    stress_shock: pd.DataFrame
    trades: pd.DataFrame
    trade_summary: dict
    synthetic: list[str]
    notes: list[str]


def evaluate_backtests(backtests: dict[str, BacktestResult], rf, bench=None,
                       baseline: str = "equal_weight", n_boot: int = 2000) -> pd.DataFrame:
    """Performance table with inference that accounts for testing several strategies at once:
    JKM test vs 1/N, Holm-adjusted p-values, block-bootstrap Sharpe CI, Deflated Sharpe Ratio."""
    excess = {m: bt.returns - daily_rf(rf, bt.returns.index) for m, bt in backtests.items()}
    rows = {}
    for m, bt in backtests.items():
        met = performance_metrics(bt.returns, rf, bench)
        lo, hi = sharpe_bootstrap_ci(excess[m], n_boot)
        met["Sharpe CI low"], met["Sharpe CI high"] = lo, hi
        met["Turnover (ann.)"] = bt.annual_turnover
        met["Avg effective N"] = float((1 / (bt.weights**2).sum(axis=1)).mean())
        if m != baseline and baseline in excess:
            met["JKM z vs 1/N"], met["p-value vs 1/N"] = sharpe_difference_test(excess[m], excess[baseline])
        rows[m] = met
    table = pd.DataFrame(rows).T
    if "p-value vs 1/N" in table:
        table["p Holm vs 1/N"] = holm_bonferroni(table["p-value vs 1/N"])
    table["DSR"] = [deflated_sharpe_ratio(excess[m], table["Sharpe"].values) for m in table.index]
    return table


def strategy_fn(method: str, cfg: PortfolioConfig, rf_lookup, risk_aversion: float, max_weight: float):
    """Closure the backtester calls with a returns window -> weights."""
    def run(window: pd.DataFrame) -> pd.Series:
        return opt.optimize(method, window, mu_method=cfg.mu_method, cov_method=cfg.cov_method,
                            rf=rf_lookup(window.index[-1]), risk_aversion=risk_aversion,
                            max_weight=max_weight, views=cfg.views, cvar_beta=cfg.cvar_beta).weights
    return run


def run_pipeline(cfg: PortfolioConfig, raw_prices: pd.DataFrame | None = None,
                 rf_series: pd.Series | None = None, progress=None) -> PipelineResult:
    say = progress or (lambda msg: None)
    tickers = list(dict.fromkeys(t.strip().upper() for t in cfg.tickers if t.strip()))
    if len(tickers) < 2:
        raise ValueError("Need at least two tickers.")
    profile = opt.RISK_PROFILES[cfg.risk_appetite]
    gamma = cfg.risk_aversion if cfg.risk_aversion is not None else profile["risk_aversion"]
    max_w = cfg.max_weight if cfg.max_weight is not None else profile["max_weight"]

    # 1. data ------------------------------------------------------------
    say("Downloading prices")
    data_start = min(cfg.start, STRESS_START)
    if raw_prices is None:
        held = [t.upper() for t in cfg.holdings]
        raw_prices = download_prices(sorted(set(tickers + held + [cfg.benchmark])), data_start, cfg.end,
                                     offline=cfg.offline)
        rf_series = download_risk_free(data_start, cfg.end, offline=cfg.offline)
    prices, synthetic, notes = prepare_prices(raw_prices, tickers, cfg.start, cfg.end, cfg.allow_synthetic)
    returns = to_returns(prices)
    # In-sample / out-of-sample split: the allocation, its risk report and the Monte Carlo only see `train`.
    train = returns.loc[:pd.Timestamp(cfg.oos_start) - pd.Timedelta(days=1)] if cfg.oos_start else returns
    if len(train) < 126:
        raise ValueError(f"Only {len(train)} trading days before {cfg.oos_start}; need at least 126 to optimise.")
    if cfg.rf is not None:
        rf_now, rf_hist = cfg.rf, cfg.rf
    elif rf_series is not None and not rf_series.empty:
        rf_known = rf_series.loc[:train.index[-1]]
        rf_now, rf_hist = float((rf_known if len(rf_known) else rf_series).iloc[-1]), rf_series
    else:
        rf_now, rf_hist = 0.04, 0.04
        notes.append("Risk-free series unavailable; using constant 4%.")

    def rf_lookup(ts):
        if isinstance(rf_hist, pd.Series):
            s = rf_hist.loc[:ts]
            return float(s.iloc[-1]) if len(s) else float(rf_hist.iloc[0])
        return float(rf_hist)

    bench = None
    if cfg.benchmark in raw_prices.columns and raw_prices[cfg.benchmark].notna().sum() > 60:
        bench = raw_prices[cfg.benchmark].loc[prices.index[0]:prices.index[-1]].ffill().pct_change().dropna()

    # 2. today's allocation (same estimation window as the backtest) ---------
    say("Optimising")
    window = train.iloc[-cfg.lookback:]
    alloc = opt.optimize(cfg.method, window, mu_method=cfg.mu_method, cov_method=cfg.cov_method,
                         rf=rf_now, risk_aversion=gamma, max_weight=max_w, views=cfg.views,
                         cvar_beta=cfg.cvar_beta)
    notes += alloc.notes
    ex_ante = ex_ante_report(alloc.weights, alloc.mu, alloc.cov, window, rf_now, cfg.capital)
    rc = risk_contributions(alloc.weights, alloc.cov)
    frontier = opt.efficient_frontier(alloc.mu, alloc.cov, 0.0, max_w)
    asset_stats = pd.DataFrame({"exp. return": alloc.mu, "volatility": np.sqrt(np.diag(alloc.cov.values))},
                               index=alloc.cov.index)

    # 3. walk-forward backtest -----------------------------------------------
    backtests: dict[str, BacktestResult] = {}
    table = pd.DataFrame()
    oos_days = len(returns) - max(cfg.lookback, len(train) if cfg.oos_start else 0)
    if cfg.run_backtest and len(returns) > cfg.lookback + 63 and oos_days > 63:
        methods = list(dict.fromkeys(cfg.backtest_methods + [cfg.method, "equal_weight"]))
        for m in methods:
            say(f"Backtesting {m}")
            backtests[m] = walk_forward(returns, strategy_fn(m, cfg, rf_lookup, gamma, max_w), m,
                                        cfg.lookback, cfg.rebalance_every, cfg.cost_bps, start=cfg.oos_start)
        say("Statistical tests")
        table = evaluate_backtests(backtests, rf_hist, bench)
        if bench is not None:
            b = bench.loc[backtests["equal_weight"].returns.index[0]:]
            table.loc[f"{cfg.benchmark} (buy & hold)"] = pd.Series(performance_metrics(b, rf_hist, bench))
    elif cfg.run_backtest:
        notes.append("History too short for a walk-forward backtest with this lookback and out-of-sample start.")

    # 4. Monte Carlo ----------------------------------------------------------
    say("Simulating")
    paths = simulate_paths(train, alloc.weights, cfg.mc_horizon, cfg.mc_paths, cfg.mc_method,
                           mu=alloc.mu, cov=alloc.cov, rebalance_every=cfg.rebalance_every,
                           cost_bps=cfg.cost_bps)
    mc = summarize_paths(paths, cfg.capital)

    # 5. stress tests ---------------------------------------------------------
    say("Stress testing")
    stress_h = historical_stress(alloc.weights, raw_prices, exclude=synthetic)
    stress_s = market_shock(alloc.weights, window, bench, capital=cfg.capital) if bench is not None else pd.DataFrame()

    # 6. trades ---------------------------------------------------------------
    cash = cfg.cash if cfg.cash is not None else (0.0 if cfg.holdings else cfg.capital)
    last_px = raw_prices.ffill().iloc[-1].combine_first(prices.iloc[-1])
    last_px.update(prices.iloc[-1])
    trades, trade_sum = rebalance_plan(alloc.weights, last_px, cfg.holdings, cash,
                                       cfg.rebalance_threshold, cfg.cost_bps)

    return PipelineResult(cfg, prices, returns, rf_now, rf_series, alloc, ex_ante, rc, frontier,
                          asset_stats, backtests, table, bench, paths, mc, stress_h, stress_s,
                          trades, trade_sum, synthetic, notes)
