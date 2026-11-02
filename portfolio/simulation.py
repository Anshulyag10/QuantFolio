"""Monte Carlo simulation of future portfolio wealth, using the SAME investment process as
the backtester: asset-level returns, weights drifting between rebalances, rebalancing back
to target every ``rebalance_every`` days, and costs c * sum|w_target - w_drifted|.

Return models for the daily asset return vector r_t:
  bootstrap:  circular block bootstrap of historical return VECTORS (keeps cross-correlation,
              fat tails and short-range volatility clustering within a block)
  gaussian:   r_t ~ N(mu/252, Sigma/252) i.i.d.
  student_t:  multivariate t with nu = 5 (r = m + L z sqrt((nu-2)/W), W ~ chi2_nu),
              same mean and covariance as the Gaussian but fatter, jointly-occurring tails.

The portfolio starts fully invested at the target weights (no initial purchase cost).
With rebalance_every = 1 and cost_bps = 0 this reduces to the constant-mix model w'r_t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import TRADING_DAYS


def simulate_paths(returns: pd.DataFrame, weights: pd.Series, horizon: int = 252,
                   n_paths: int = 5000, method: str = "bootstrap", block: int = 20,
                   mu: pd.Series | None = None, cov: pd.DataFrame | None = None,
                   rebalance_every: int = 21, cost_bps: float = 10.0, nu: float = 5.0,
                   seed: int = 42) -> np.ndarray:
    """Wealth paths, shape (n_paths, horizon + 1), starting at 1."""
    rng = np.random.default_rng(seed)
    cols = returns.columns
    target = weights.reindex(cols).fillna(0).values
    n = len(cols)

    if method == "bootstrap":
        R = returns.values
        T = len(R)
        n_blocks = int(np.ceil(horizon / block))
        starts = rng.integers(0, T, size=(n_paths, n_blocks))
        idx = ((starts[:, :, None] + np.arange(block)) % T).reshape(n_paths, -1)[:, :horizon]
        draw = lambda t: R[idx[:, t]]
    elif method in ("gaussian", "student_t"):
        m = (mu if mu is not None else returns.mean() * TRADING_DAYS).reindex(cols).values / TRADING_DAYS
        S = (cov if cov is not None else returns.cov() * TRADING_DAYS).reindex(index=cols, columns=cols).values
        L = np.linalg.cholesky(S / TRADING_DAYS + 1e-12 * np.eye(n))
        if method == "gaussian":
            draw = lambda t: m + rng.standard_normal((n_paths, n)) @ L.T
        else:
            def draw(t):
                scale = np.sqrt((nu - 2) / rng.chisquare(nu, (n_paths, 1)))
                return m + (rng.standard_normal((n_paths, n)) @ L.T) * scale
    else:
        raise ValueError(method)

    c = cost_bps / 1e4
    w = np.tile(target, (n_paths, 1))                 # current (drifted) weights per path
    wealth = np.ones((n_paths, horizon + 1))
    for t in range(horizon):
        cost = 0.0
        if t > 0 and t % rebalance_every == 0:
            cost = c * np.abs(target - w).sum(axis=1)
            w = np.tile(target, (n_paths, 1))
        r = draw(t)
        gross = (w * r).sum(axis=1)
        wealth[:, t + 1] = wealth[:, t] * (1 - cost) * (1 + gross)
        w = w * (1 + r) / (1 + gross)[:, None]
    return wealth


def summarize_paths(paths: np.ndarray, capital: float, alpha: float = 0.95) -> dict:
    terminal = paths[:, -1]
    ret = terminal - 1
    q = np.quantile(ret, 1 - alpha)
    peak = np.maximum.accumulate(paths, axis=1)
    mdd = (paths / peak - 1).min(axis=1)
    return {
        "Expected terminal value": capital * terminal.mean(),
        "Median terminal value": capital * np.median(terminal),
        "5th percentile value": capital * np.quantile(terminal, 0.05),
        "95th percentile value": capital * np.quantile(terminal, 0.95),
        "P(loss)": float((terminal < 1).mean()),
        f"Horizon VaR {int(alpha*100)}%": float(-q),
        f"Horizon CVaR {int(alpha*100)}%": float(-ret[ret <= q].mean()),
        "P(max drawdown > 20%)": float((mdd < -0.20).mean()),
        "Median max drawdown": float(np.median(mdd)),
    }
