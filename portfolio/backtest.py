"""Walk-forward (out-of-sample) backtest with weight drift and transaction costs.

At each rebalance date t the strategy sees ONLY returns r_{t-L}, ..., r_{t-1}
(the previous ``lookback`` days) and outputs target weights that earn r_t onwards.
Between rebalances weights drift with prices:

    w_{t+1,i} = w_{t,i} (1 + r_{t,i}) / (1 + w_t' r_t).

Trading from drifted weights w- to target w+ costs  c * sum_i |w+_i - w-_i|
(``cost_bps`` per unit of value traded), charged on the rebalance day.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .data import TRADING_DAYS

Strategy = Callable[[pd.DataFrame], pd.Series]


@dataclass
class BacktestResult:
    name: str
    returns: pd.Series            # net daily portfolio returns
    weights: pd.DataFrame         # target weights at each rebalance date
    turnover: pd.Series           # sum |w+ - w-| at each rebalance date
    costs: pd.Series              # cost fraction at each rebalance date

    @property
    def annual_turnover(self) -> float:
        years = len(self.returns) / TRADING_DAYS
        return float(self.turnover.sum() / years) if years > 0 else np.nan


def memoize(strategy: Strategy) -> Strategy:
    """Cache a strategy's weights by estimation window, so backtests that differ only in
    transaction costs re-use the same optimisations."""
    cache: dict = {}

    def run(window: pd.DataFrame) -> pd.Series:
        key = (window.index[0], window.index[-1])
        if key not in cache:
            cache[key] = strategy(window)
        return cache[key]
    return run


def walk_forward(returns: pd.DataFrame, strategy: Strategy, name: str = "strategy",
                 lookback: int = 504, rebalance_every: int = 21,
                 cost_bps: float = 10.0, start=None) -> BacktestResult:
    """``start`` (optional date) delays the first out-of-sample day, e.g. to hold out 2022 onwards."""
    R = returns.values
    T, n = R.shape
    if T <= lookback + 1:
        raise ValueError(f"Need more than lookback={lookback} days of returns, got {T}.")
    cols, dates = returns.columns, returns.index
    t0 = lookback if start is None else max(lookback, int(dates.searchsorted(pd.Timestamp(start))))
    if t0 >= T - 1:
        raise ValueError(f"No out-of-sample days after {start}.")
    w = np.zeros(n)
    port = np.empty(T - t0)
    w_hist, to_hist, cost_hist, reb_dates = [], [], [], []

    for k, t in enumerate(range(t0, T)):
        cost = 0.0
        if k % rebalance_every == 0:
            window = returns.iloc[t - lookback:t]          # strictly before t: no look-ahead
            target = strategy(window).reindex(cols).fillna(0.0).values
            target = target / target.sum()
            turnover = np.abs(target - w).sum()
            cost = turnover * cost_bps / 1e4
            w = target
            w_hist.append(target)
            to_hist.append(turnover)
            cost_hist.append(cost)
            reb_dates.append(dates[t])
        gross = float(w @ R[t])
        port[k] = (1 - cost) * (1 + gross) - 1
        w = w * (1 + R[t]) / (1 + gross)                    # drift to next day

    idx = pd.DatetimeIndex(reb_dates)
    return BacktestResult(
        name=name,
        returns=pd.Series(port, index=dates[t0:], name=name),
        weights=pd.DataFrame(w_hist, index=idx, columns=cols),
        turnover=pd.Series(to_hist, index=idx),
        costs=pd.Series(cost_hist, index=idx),
    )
