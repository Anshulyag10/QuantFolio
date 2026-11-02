"""Risk and performance analytics.

Conventions: returns are simple daily returns; VaR/CVaR are reported as positive
loss fractions (0.02 = a 2% loss); annualisation uses 252 trading days.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .data import TRADING_DAYS


def daily_rf(rf: float | pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Convert an annual risk-free rate (constant or a time series) to daily simple returns."""
    if isinstance(rf, pd.Series):
        annual = rf.reindex(index.union(rf.index)).ffill().reindex(index).fillna(rf.iloc[0])
    else:
        annual = pd.Series(float(rf), index=index)
    return (1 + annual) ** (1 / TRADING_DAYS) - 1


# ------------------------------------------------------------- tail risk
def var_cvar(returns: pd.Series | np.ndarray, alpha: float = 0.95,
             method: str = "historical") -> tuple[float, float]:
    """One-period VaR and CVaR (expected shortfall) at confidence ``alpha``.

    historical:     empirical quantile; CVaR = mean loss beyond VaR
    gaussian:       VaR = -(m + z s),  CVaR = -m + s phi(z) / (1 - alpha),  z = Phi^-1(1 - alpha)
    cornish_fisher: z replaced by the skew/kurtosis adjusted quantile
                    z_cf = z + (z^2-1)S/6 + (z^3-3z)K/24 - (2z^3-5z)S^2/36   (K = excess kurtosis)
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if method == "historical":
        q = np.quantile(r, 1 - alpha)
        tail = r[r <= q]
        return float(-q), float(-tail.mean())
    m, s = r.mean(), r.std(ddof=1)
    z = stats.norm.ppf(1 - alpha)
    if method == "gaussian":
        return float(-(m + z * s)), float(-m + s * stats.norm.pdf(z) / (1 - alpha))
    if method == "cornish_fisher":
        S, K = stats.skew(r), stats.kurtosis(r)
        z_cf = z + (z**2 - 1) * S / 6 + (z**3 - 3 * z) * K / 24 - (2 * z**3 - 5 * z) * S**2 / 36
        var = -(m + z_cf * s)
        # CVaR: average the CF quantile over the tail by numerical integration
        grid = (np.arange(400) + 0.5) / 400 * (1 - alpha)  # midpoints of (0, 1-alpha)
        zg = stats.norm.ppf(grid)
        zg_cf = zg + (zg**2 - 1) * S / 6 + (zg**3 - 3 * zg) * K / 24 - (2 * zg**3 - 5 * zg) * S**2 / 36
        cvar = -(m + s * zg_cf.mean())
        return float(var), float(max(cvar, var))
    raise ValueError(method)


def drawdown(returns: pd.Series) -> pd.Series:
    """Drawdown from running peak of wealth W_t = prod(1 + r), with initial wealth 1 as a peak."""
    wealth = (1 + returns).cumprod()
    peak = wealth.cummax().clip(lower=1.0)
    return wealth / peak - 1


# --------------------------------------------------- Sharpe ratio inference
def probabilistic_sharpe_ratio(excess: pd.Series, sr_benchmark: float = 0.0) -> float:
    """PSR of Bailey & Lopez de Prado (2012): P(true SR > SR*) given T, skew and kurtosis.

    PSR = Phi( (SR - SR*) sqrt(T-1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2) ),
    with SR per period, g3 = skewness, g4 = (non-excess) kurtosis.
    ``sr_benchmark`` is annualised.
    """
    x = np.asarray(excess.dropna(), dtype=float)
    T = len(x)
    if T < 3 or x.std(ddof=1) == 0:
        return float("nan")
    sr = x.mean() / x.std(ddof=1)
    sr_star = sr_benchmark / np.sqrt(TRADING_DAYS)
    g3, g4 = stats.skew(x), stats.kurtosis(x, fisher=False)
    denom = np.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    return float(stats.norm.cdf((sr - sr_star) * np.sqrt(T - 1) / denom))


def sharpe_difference_test(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    """Jobson-Korkie test with Memmel (2003) correction for H0: SR_a = SR_b.

    z = (s_b m_a - s_a m_b) / sqrt(theta),
    theta = [2 s_a^2 s_b^2 - 2 s_a s_b s_ab + m_a^2 s_b^2 / 2 + m_b^2 s_a^2 / 2
             - (m_a m_b / (s_a s_b)) s_ab^2] / T
    (as used in DeMiguel, Garlappi & Uppal 2009). Inputs are excess returns.
    Returns (z, two-sided p-value).
    """
    df = pd.concat([a, b], axis=1).dropna()
    x, y = df.iloc[:, 0].values, df.iloc[:, 1].values
    T = len(x)
    ma, mb = x.mean(), y.mean()
    sa, sb = x.std(ddof=1), y.std(ddof=1)
    sab = np.cov(x, y)[0, 1]
    theta = (2 * sa**2 * sb**2 - 2 * sa * sb * sab + 0.5 * ma**2 * sb**2 + 0.5 * mb**2 * sa**2
             - (ma * mb / (sa * sb)) * sab**2) / T
    if theta <= 0:
        return 0.0, 1.0
    z = (sb * ma - sa * mb) / np.sqrt(theta)
    return float(z), float(2 * (1 - stats.norm.cdf(abs(z))))


def holm_bonferroni(pvalues: pd.Series) -> pd.Series:
    """Holm (1979) step-down adjustment controlling the family-wise error rate:
    sort p_(1) <= ... <= p_(m);  p~_(k) = max_{j<=k} min(1, (m - j + 1) p_(j))."""
    p = pvalues.dropna().sort_values()
    m = len(p)
    adj = np.minimum(1.0, np.maximum.accumulate((m - np.arange(m)) * p.values))
    return pd.Series(adj, index=p.index).reindex(pvalues.index)


def sharpe_bootstrap_ci(excess: pd.Series, n_boot: int = 2000, block: int = 20,
                        level: float = 0.95, seed: int = 0) -> tuple[float, float]:
    """Circular block-bootstrap confidence interval for the annualised Sharpe ratio.
    Blocks keep volatility clustering and autocorrelation that an i.i.d. bootstrap would destroy."""
    x = np.asarray(excess.dropna(), dtype=float)
    T = len(x)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(T / block))
    srs = np.empty(n_boot)
    for start in range(0, n_boot, 250):                  # chunks keep memory small
        k = min(250, n_boot - start)
        idx = (rng.integers(0, T, (k, n_blocks))[:, :, None] + np.arange(block)) % T
        s = x[idx.reshape(k, -1)[:, :T]]
        srs[start:start + k] = s.mean(axis=1) / s.std(axis=1, ddof=1) * np.sqrt(TRADING_DAYS)
    a = (1 - level) / 2
    return float(np.quantile(srs, a)), float(np.quantile(srs, 1 - a))


def deflated_sharpe_ratio(excess: pd.Series, trial_srs: np.ndarray) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

    When the best of N strategies is reported, its Sharpe is biased upward. The DSR is
    the PSR evaluated against the expected maximum Sharpe of N unskilled trials:
      SR* = sqrt(V[SR_n]) [ (1 - g) Phi^-1(1 - 1/N) + g Phi^-1(1 - 1/(N e)) ],  g = 0.5772...
    ``trial_srs``: annualised Sharpe ratios of all N strategies tried.
    """
    trial = np.asarray(trial_srs, dtype=float) / np.sqrt(TRADING_DAYS)
    N = len(trial)
    if N < 2:
        return probabilistic_sharpe_ratio(excess, 0.0)
    g = 0.5772156649
    sr_star = np.sqrt(trial.var(ddof=1)) * ((1 - g) * stats.norm.ppf(1 - 1 / N)
                                            + g * stats.norm.ppf(1 - 1 / (N * np.e)))
    return probabilistic_sharpe_ratio(excess, sr_star * np.sqrt(TRADING_DAYS))


# ------------------------------------------------------ performance table
def performance_metrics(returns: pd.Series, rf: float | pd.Series = 0.0,
                        benchmark: pd.Series | None = None) -> dict:
    r = returns.dropna()
    T = len(r)
    ex = r - daily_rf(rf, r.index)
    wealth = (1 + r).prod()
    years = T / TRADING_DAYS
    cagr = wealth ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std(ddof=1) * np.sqrt(TRADING_DAYS)
    downside = np.sqrt(np.mean(np.minimum(ex.values, 0.0) ** 2)) * np.sqrt(TRADING_DAYS)
    mdd = drawdown(r).min()
    var95, cvar95 = var_cvar(r, 0.95)
    out = {
        "CAGR": cagr,
        "Volatility": vol,
        "Sharpe": ex.mean() / ex.std(ddof=1) * np.sqrt(TRADING_DAYS),
        "Sortino": ex.mean() * TRADING_DAYS / downside if downside > 0 else np.nan,
        "Max Drawdown": mdd,
        "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "VaR 95% (1d)": var95,
        "CVaR 95% (1d)": cvar95,
        "Skewness": stats.skew(r),
        "Excess Kurtosis": stats.kurtosis(r),
        "PSR (SR>0)": probabilistic_sharpe_ratio(ex, 0.0),
    }
    if benchmark is not None:
        df = pd.concat([r, benchmark], axis=1).dropna()
        if len(df) > 20:
            c = np.cov(df.iloc[:, 0], df.iloc[:, 1])
            out["Beta"] = c[0, 1] / c[1, 1]
    return out


# ------------------------------------------------------- ex-ante analytics
def risk_contributions(weights: pd.Series, cov: pd.DataFrame) -> pd.DataFrame:
    """Euler decomposition of volatility: sigma_p = sum_i w_i (Sigma w)_i / sigma_p."""
    w = weights.reindex(cov.index).fillna(0).values
    sig_p = np.sqrt(w @ cov.values @ w)
    mrc = cov.values @ w / sig_p
    rc = w * mrc
    return pd.DataFrame({"weight": w, "vol": np.sqrt(np.diag(cov.values)), "marginal": mrc,
                         "contribution": rc, "pct_risk": rc / sig_p}, index=cov.index)


def diversification_ratio(weights: pd.Series, cov: pd.DataFrame) -> float:
    w = weights.reindex(cov.index).fillna(0).values
    return float(w @ np.sqrt(np.diag(cov.values)) / np.sqrt(w @ cov.values @ w))


def ex_ante_report(weights: pd.Series, mu: pd.Series, cov: pd.DataFrame,
                   hist_returns: pd.DataFrame, rf: float, capital: float) -> dict:
    """Forward-looking risk of the proposed weights plus historical-simulation tail risk."""
    w = weights.reindex(cov.index).fillna(0)
    exp_ret = float(mu.reindex(w.index) @ w)
    vol = float(np.sqrt(w.values @ cov.values @ w.values))
    port = hist_returns[w.index] @ w.values
    hhi = float((w**2).sum())
    out = {
        "Expected return (ann.)": exp_ret,
        "Volatility (ann.)": vol,
        "Sharpe (ex-ante)": (exp_ret - rf) / vol if vol > 0 else np.nan,
        "Herfindahl (HHI)": hhi,
        "Effective N (1/HHI)": 1 / hhi,
        "Diversification ratio": diversification_ratio(w, cov),
    }
    for a in (0.95, 0.99):
        for m in ("historical", "gaussian", "cornish_fisher"):
            v, c = var_cvar(port, a, m)
            out[f"VaR {int(a*100)}% 1d ({m})"] = v
            out[f"CVaR {int(a*100)}% 1d ({m})"] = c
    out["VaR 95% 1d ($, historical)"] = out["VaR 95% 1d (historical)"] * capital
    out["CVaR 95% 1d ($, historical)"] = out["CVaR 95% 1d (historical)"] * capital
    return out
