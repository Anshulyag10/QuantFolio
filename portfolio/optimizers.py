"""Portfolio construction methods. All portfolios are long-only and fully invested:

    sum_i w_i = 1,   lb <= w_i <= ub.

Convex problems are solved with cvxpy. If a solver fails the method falls back
to inverse-volatility weights and records a note, so the pipeline never crashes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from .estimators import covariance, expected_returns

METHODS = {
    "max_sharpe": "Max Sharpe (tangency) portfolio",
    "mean_variance": "Mean-variance utility  max mu'w - (gamma/2) w'Sigma w",
    "min_variance": "Global minimum variance",
    "risk_parity": "Equal risk contribution (ERC)",
    "hrp": "Hierarchical Risk Parity (Lopez de Prado 2016)",
    "max_diversification": "Maximum diversification ratio (Choueifaty 2008)",
    "min_cvar": "Minimum CVaR, Rockafellar-Uryasev LP",
    "black_litterman": "Black-Litterman posterior + mean-variance",
    "inverse_vol": "Inverse volatility (naive risk parity)",
    "equal_weight": "Equal weight 1/N (DeMiguel et al. 2009 benchmark)",
}

RISK_PROFILES = {
    # gamma: risk aversion in mean-variance utility; max_weight: single-asset cap
    "conservative": {"risk_aversion": 10.0, "max_weight": 0.25},
    "moderate": {"risk_aversion": 4.0, "max_weight": 0.35},
    "aggressive": {"risk_aversion": 1.5, "max_weight": 0.60},
}


@dataclass
class View:
    """A Black-Litterman view: sum_i p_i * E[r_i] = q (annual total return).

    Absolute: View({"QQQ": 1}, 0.10, 0.6)          -> QQQ returns 10%
    Relative: View({"SPY": 1, "TLT": -1}, 0.03, 0.5) -> SPY beats TLT by 3%
    confidence in (0, 1]: Idzorek-style, Omega_k = (1-c)/c * p_k' tau Sigma p_k.
    """
    assets: dict[str, float]
    q: float
    confidence: float = 0.5


def parse_views(text: str) -> list[View]:
    """Parse lines like 'QQQ = 0.12 @ 0.6' or 'SPY - TLT = 0.03 @ 0.5' (confidence defaults to 0.5).
    Operators must be separated by spaces so tickers such as BRK-B still parse."""
    views = []
    for line in text.strip().splitlines():
        if "=" not in line:
            continue
        lhs, rhs = line.split("=", 1)
        rhs, conf = (rhs.split("@", 1) + ["0.5"])[:2]
        assets, sign = {}, 1.0
        for tok in lhs.split():
            if tok in ("+", "-"):
                sign = -1.0 if tok == "-" else 1.0
            else:
                assets[tok.upper()], sign = sign, 1.0
        views.append(View(assets, float(rhs), float(conf)))
    return views


@dataclass
class OptimizationResult:
    weights: pd.Series
    method: str
    mu: pd.Series
    cov: pd.DataFrame
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------- helpers
def _feasible_bounds(n: int, lb: float, ub: float) -> tuple[float, float]:
    return min(lb, 1.0 / n), max(ub, 1.0 / n)


def _psd(cov: pd.DataFrame):
    return cp.psd_wrap(0.5 * (cov.values + cov.values.T))


def _solve(prob: cp.Problem) -> bool:
    for solver in (None, cp.SCS):
        try:
            prob.solve(solver=solver) if solver else prob.solve()
            if prob.status in ("optimal", "optimal_inaccurate"):
                return True
        except (cp.SolverError, ValueError):
            continue
    return False


def _clean(w: np.ndarray, index) -> pd.Series:
    w = np.clip(np.asarray(w, dtype=float).ravel(), 0.0, None)
    w[w < 1e-7] = 0.0
    return pd.Series(w / w.sum(), index=index)


def cap_weights(w: pd.Series, max_w: float) -> pd.Series:
    """Project heuristic weights onto {w <= max_w}: cap, then redistribute the excess
    pro rata among uncapped names (repeat until no weight exceeds the cap)."""
    w = w.clip(lower=0) / w.clip(lower=0).sum()
    max_w = max(max_w, 1.0 / len(w))
    capped = pd.Series(False, index=w.index)
    for _ in range(len(w)):
        over = w > max_w + 1e-12
        if not over.any():
            break
        capped |= over
        excess = (w[over] - max_w).sum()
        w[over] = max_w
        free = ~capped
        base = w[free].sum()
        w[free] += excess * (w[free] / base if base > 0 else 1.0 / free.sum())
    return w


# ------------------------------------------------------------- heuristics
def equal_weight(cols) -> pd.Series:
    return pd.Series(1.0 / len(cols), index=cols)


def inverse_vol(cov: pd.DataFrame) -> pd.Series:
    iv = 1.0 / np.sqrt(np.diag(cov.values))
    return pd.Series(iv / iv.sum(), index=cov.index)


def hrp(cov: pd.DataFrame) -> pd.Series:
    """Hierarchical Risk Parity.

    1. distance d_ij = sqrt((1 - rho_ij) / 2), single-linkage clustering
    2. quasi-diagonalise: order assets by the dendrogram leaves
    3. recursive bisection: split each cluster in two halves and allocate
       alpha = 1 - V_0 / (V_0 + V_1) to the first half, where V is the variance of
       the inverse-variance portfolio inside each half.
    """
    sd = np.sqrt(np.diag(cov.values))
    corr = np.clip(cov.values / np.outer(sd, sd), -1, 1)
    if len(cov) == 1:
        return pd.Series(1.0, index=cov.index)
    dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))
    np.fill_diagonal(dist, 0.0)
    order = list(leaves_list(linkage(squareform(dist, checks=False), method="single")))

    def cluster_var(idx):
        c = cov.values[np.ix_(idx, idx)]
        ivp = 1.0 / np.diag(c)
        ivp /= ivp.sum()
        return ivp @ c @ ivp

    w = np.ones(len(cov))
    clusters = [order]
    while clusters:
        clusters = [c[s:e] for c in clusters if len(c) > 1
                    for s, e in ((0, len(c) // 2), (len(c) // 2, len(c)))]
        for i in range(0, len(clusters), 2):
            left, right = clusters[i], clusters[i + 1]
            v_l, v_r = cluster_var(left), cluster_var(right)
            alpha = 1 - v_l / (v_l + v_r)
            w[left] *= alpha
            w[right] *= 1 - alpha
    return pd.Series(w / w.sum(), index=cov.index)


# ------------------------------------------------------- convex optimisers
def min_variance(cov: pd.DataFrame, lb=0.0, ub=1.0) -> pd.Series | None:
    n = len(cov)
    lb, ub = _feasible_bounds(n, lb, ub)
    w = cp.Variable(n)
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, _psd(cov))),
                      [cp.sum(w) == 1, w >= lb, w <= ub])
    return _clean(w.value, cov.index) if _solve(prob) else None


def mean_variance(mu: pd.Series, cov: pd.DataFrame, gamma: float, lb=0.0, ub=1.0) -> pd.Series | None:
    n = len(cov)
    lb, ub = _feasible_bounds(n, lb, ub)
    w = cp.Variable(n)
    obj = mu.values @ w - 0.5 * gamma * cp.quad_form(w, _psd(cov))
    prob = cp.Problem(cp.Maximize(obj), [cp.sum(w) == 1, w >= lb, w <= ub])
    return _clean(w.value, cov.index) if _solve(prob) else None


def max_sharpe(mu: pd.Series, cov: pd.DataFrame, rf: float, lb=0.0, ub=1.0) -> pd.Series | None:
    """Tangency portfolio via the homogenisation trick (Cornuejols & Tutuncu):
    min y'Sigma y  s.t. (mu - rf)'y = 1, y >= 0, lb*kappa <= y <= ub*kappa, kappa = 1'y;
    then w = y / kappa. Requires at least one asset with mu_i > rf."""
    n = len(cov)
    if (mu.values - rf).max() <= 0:
        return None
    lb, ub = _feasible_bounds(n, lb, ub)
    y = cp.Variable(n)
    kappa = cp.sum(y)
    cons = [(mu.values - rf) @ y == 1, y >= lb * kappa, y <= ub * kappa, y >= 0]
    prob = cp.Problem(cp.Minimize(cp.quad_form(y, _psd(cov))), cons)
    return _clean(y.value, cov.index) if _solve(prob) else None


def max_diversification(cov: pd.DataFrame, lb=0.0, ub=1.0) -> pd.Series | None:
    """max DR(w) = w'sigma / sqrt(w'Sigma w); same homogenisation as max Sharpe with sigma in place of mu - rf."""
    n = len(cov)
    lb, ub = _feasible_bounds(n, lb, ub)
    sig = np.sqrt(np.diag(cov.values))
    y = cp.Variable(n)
    kappa = cp.sum(y)
    cons = [sig @ y == 1, y >= lb * kappa, y <= ub * kappa, y >= 0]
    prob = cp.Problem(cp.Minimize(cp.quad_form(y, _psd(cov))), cons)
    return _clean(y.value, cov.index) if _solve(prob) else None


def risk_parity(cov: pd.DataFrame, budget: np.ndarray | None = None) -> pd.Series | None:
    """Equal risk contribution via the convex program of Spinu (2013):
    min 0.5 y'Sigma y - sum_i b_i log y_i,  y > 0;  w = y / 1'y.
    At the optimum w_i (Sigma w)_i is proportional to b_i."""
    n = len(cov)
    b = np.full(n, 1.0 / n) if budget is None else np.asarray(budget) / np.sum(budget)
    y = cp.Variable(n, pos=True)
    prob = cp.Problem(cp.Minimize(0.5 * cp.quad_form(y, _psd(cov)) - b @ cp.log(y)))
    return _clean(y.value, cov.index) if _solve(prob) else None


def min_cvar(returns: pd.DataFrame, beta: float = 0.95, lb=0.0, ub=1.0) -> pd.Series | None:
    """Rockafellar & Uryasev (2000) LP on historical scenarios r_t:
    min_{w, a, u} a + 1/((1-beta) T) sum_t u_t,  u_t >= -r_t'w - a,  u_t >= 0.
    At the optimum a is the beta-VaR and the objective is the beta-CVaR of daily loss."""
    R = returns.values
    T, n = R.shape
    lb, ub = _feasible_bounds(n, lb, ub)
    w, a, u = cp.Variable(n), cp.Variable(), cp.Variable(T)
    obj = a + cp.sum(u) / ((1 - beta) * T)
    cons = [u >= -R @ w - a, u >= 0, cp.sum(w) == 1, w >= lb, w <= ub]
    prob = cp.Problem(cp.Minimize(obj), cons)
    return _clean(w.value, returns.columns) if _solve(prob) else None


# ---------------------------------------------------------- Black-Litterman
def black_litterman(cov: pd.DataFrame, views: list[View], w_prior: pd.Series,
                    delta: float = 2.5, tau: float = 0.05, rf: float = 0.0
                    ) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    """Black-Litterman posterior (He & Litterman 1999 form).

    Prior (reverse optimisation): pi = delta * Sigma w_prior  (excess returns).
    Views: P mu = Q + eps, eps ~ N(0, Omega).
    Posterior mean:  mu_BL = pi + tau Sigma P' (P tau Sigma P' + Omega)^-1 (Q - P pi)
    Posterior cov:   M = tau Sigma - tau Sigma P' (P tau Sigma P' + Omega)^-1 P tau Sigma,
                     Sigma_BL = Sigma + M.
    This form needs no Omega^-1, so 100% confidence (Omega = 0) is well defined.
    Returns (mu_BL total returns, Sigma_BL, pi total returns).
    """
    S = cov.values
    assets = list(cov.index)
    pi = delta * S @ w_prior.reindex(assets).fillna(0).values
    tS = tau * S
    views = [v for v in views if any(a in assets for a in v.assets)]
    if not views:
        mu_bl, post = pi, S + tS
    else:
        P = np.array([[v.assets.get(a, 0.0) for a in assets] for v in views])
        # views are on total returns; convert to excess: q - rf * sum_i p_i
        Q = np.array([v.q - rf * sum(v.assets.get(a, 0.0) for a in assets) for v in views])
        c = np.clip([v.confidence for v in views], 1e-3, 1.0)
        omega = np.diag((1 - c) / c * np.diag(P @ tS @ P.T))
        K = tS @ P.T @ np.linalg.inv(P @ tS @ P.T + omega)
        mu_bl = pi + K @ (Q - P @ pi)
        post = S + tS - K @ P @ tS
    idx = cov.index
    return (pd.Series(mu_bl + rf, index=idx),
            pd.DataFrame(0.5 * (post + post.T), index=idx, columns=idx),
            pd.Series(pi + rf, index=idx))


# ---------------------------------------------------------------- dispatch
def optimize(method: str, returns: pd.DataFrame, *, mu_method: str = "james_stein",
             cov_method: str = "ledoit_wolf", rf: float = 0.04, risk_aversion: float = 4.0,
             max_weight: float = 1.0, min_weight: float = 0.0, views: list[View] | None = None,
             bl_prior: pd.Series | None = None, bl_delta: float = 2.5, bl_tau: float = 0.05,
             cvar_beta: float = 0.95) -> OptimizationResult:
    """Estimate (mu, Sigma) from ``returns`` (daily) and build the ``method`` portfolio."""
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}; choose from {list(METHODS)}")
    cov = covariance(returns, cov_method)
    mu = expected_returns(returns, mu_method)
    cols = returns.columns
    notes: list[str] = []
    w: pd.Series | None

    if method == "equal_weight":
        w = equal_weight(cols)
    elif method == "inverse_vol":
        w = cap_weights(inverse_vol(cov), max_weight)
    elif method == "hrp":
        w = cap_weights(hrp(cov), max_weight)
    elif method == "risk_parity":
        w = risk_parity(cov)
        w = cap_weights(w, max_weight) if w is not None else None
    elif method == "min_variance":
        w = min_variance(cov, min_weight, max_weight)
    elif method == "max_diversification":
        w = max_diversification(cov, min_weight, max_weight)
    elif method == "mean_variance":
        w = mean_variance(mu, cov, risk_aversion, min_weight, max_weight)
    elif method == "max_sharpe":
        w = max_sharpe(mu, cov, rf, min_weight, max_weight)
        if w is None:
            notes.append("No asset has expected return above rf; max Sharpe undefined -> min variance used.")
            w = min_variance(cov, min_weight, max_weight)
    elif method == "min_cvar":
        w = min_cvar(returns, cvar_beta, min_weight, max_weight)
    elif method == "black_litterman":
        prior = bl_prior if bl_prior is not None else equal_weight(cols)
        mu, cov_bl, _ = black_litterman(cov, views or [], prior, bl_delta, bl_tau, rf)
        w = mean_variance(mu, cov_bl, risk_aversion, min_weight, max_weight)
        cov = cov_bl

    if w is None:
        notes.append(f"{method}: solver failed, fell back to inverse volatility.")
        w = cap_weights(inverse_vol(cov), max_weight)
    return OptimizationResult(w.reindex(cols).fillna(0.0), method, mu, cov, notes)


def efficient_frontier(mu: pd.Series, cov: pd.DataFrame, lb=0.0, ub=1.0,
                       n_points: int = 40) -> pd.DataFrame:
    """Long-only frontier: min w'Sigma w s.t. mu'w >= target, for targets between the
    min-variance return and the max attainable return under the bounds."""
    n = len(cov)
    lb, ub = _feasible_bounds(n, lb, ub)
    w_mv = min_variance(cov, lb, ub)
    if w_mv is None:
        return pd.DataFrame(columns=["volatility", "return"])
    w = cp.Variable(n)
    r_max_prob = cp.Problem(cp.Maximize(mu.values @ w), [cp.sum(w) == 1, w >= lb, w <= ub])
    _solve(r_max_prob)
    r_lo, r_hi = float(mu @ w_mv), float(r_max_prob.value)
    target = cp.Parameter()
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, _psd(cov))),
                      [cp.sum(w) == 1, w >= lb, w <= ub, mu.values @ w >= target])
    rows = []
    for t in np.linspace(r_lo, r_hi, n_points):
        target.value = t
        if _solve(prob):
            wv = np.clip(w.value, 0, None)
            wv /= wv.sum()
            rows.append({"volatility": float(np.sqrt(wv @ cov.values @ wv)), "return": float(mu @ wv)})
    return pd.DataFrame(rows)
