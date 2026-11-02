"""Estimators for expected returns (mu) and covariance (Sigma), annualised.

Sample estimates are noisy: with N assets and T observations the sample mean has
error ~ sigma/sqrt(T) (huge for T of a few years) and the sample covariance has
N(N+1)/2 parameters. Shrinkage estimators trade a little bias for a lot less
variance, which matters because optimisers amplify estimation error.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from .data import TRADING_DAYS

MU_METHODS = {
    "james_stein": "Bayes-Stein shrinkage to the min-variance mean (Jorion 1986)",
    "historical": "Sample mean of daily returns x 252",
    "ewma": "Exponentially weighted mean (half-life 126 days)",
}
COV_METHODS = {
    "ledoit_wolf": "Ledoit-Wolf shrinkage towards scaled identity (2004)",
    "sample": "Sample covariance",
    "ewma": "RiskMetrics EWMA, lambda = 0.94",
}


def nearest_psd(cov: np.ndarray, eps: float = 1e-10) -> np.ndarray:
    """Symmetrise and clip negative eigenvalues so the matrix is positive semidefinite."""
    cov = 0.5 * (cov + cov.T)
    vals, vecs = np.linalg.eigh(cov)
    return (vecs * np.clip(vals, eps, None)) @ vecs.T


# ---------------------------------------------------------------- covariance
def cov_sample(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.cov() * TRADING_DAYS


def cov_ledoit_wolf(returns: pd.DataFrame) -> pd.DataFrame:
    lw = LedoitWolf().fit(returns.values)
    return pd.DataFrame(lw.covariance_ * TRADING_DAYS, index=returns.columns, columns=returns.columns)


def cov_ewma(returns: pd.DataFrame, lam: float = 0.94) -> pd.DataFrame:
    """Sigma = sum_t w_t (r_t - m)(r_t - m)',  w_t proportional to lam^(T-1-t)."""
    X = returns.values
    T = len(X)
    w = lam ** np.arange(T - 1, -1, -1)
    w /= w.sum()
    m = w @ X
    Xc = X - m
    cov = (Xc * w[:, None]).T @ Xc
    return pd.DataFrame(cov * TRADING_DAYS, index=returns.columns, columns=returns.columns)


def covariance(returns: pd.DataFrame, method: str = "ledoit_wolf") -> pd.DataFrame:
    fn = {"sample": cov_sample, "ledoit_wolf": cov_ledoit_wolf, "ewma": cov_ewma}[method]
    cov = fn(returns)
    return pd.DataFrame(nearest_psd(cov.values), index=cov.index, columns=cov.columns)


# ---------------------------------------------------------- expected returns
def mu_historical(returns: pd.DataFrame) -> pd.Series:
    return returns.mean() * TRADING_DAYS


def mu_ewma(returns: pd.DataFrame, halflife: int = 126) -> pd.Series:
    return returns.ewm(halflife=halflife).mean().iloc[-1] * TRADING_DAYS


def mu_james_stein(returns: pd.DataFrame) -> pd.Series:
    """Bayes-Stein estimator of Jorion (1986), computed on daily data then annualised.

    mu_BS = (1 - phi) mu_hat + phi mu_0 1,  where mu_0 is the mean of the global
    minimum-variance portfolio and
    phi = (N + 2) / [(N + 2) + T (mu_hat - mu_0 1)' S^-1 (mu_hat - mu_0 1)],
    S = sample covariance scaled by (T - 1)/(T - N - 2).
    """
    X = returns.values
    T, N = X.shape
    mu_hat = X.mean(axis=0)
    if T <= N + 2:
        return mu_historical(returns)
    S = np.cov(X, rowvar=False) * (T - 1) / (T - N - 2)
    S_inv = np.linalg.pinv(S)
    ones = np.ones(N)
    mu0 = (ones @ S_inv @ mu_hat) / (ones @ S_inv @ ones)
    d = mu_hat - mu0
    phi = (N + 2) / ((N + 2) + T * d @ S_inv @ d)
    phi = float(np.clip(phi, 0.0, 1.0))
    mu_bs = (1 - phi) * mu_hat + phi * mu0
    return pd.Series(mu_bs * TRADING_DAYS, index=returns.columns)


def expected_returns(returns: pd.DataFrame, method: str = "james_stein") -> pd.Series:
    fn = {"historical": mu_historical, "ewma": mu_ewma, "james_stein": mu_james_stein}[method]
    return fn(returns)
