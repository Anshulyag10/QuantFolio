"""Stress testing: replay historical crises and apply hypothetical market shocks."""
from __future__ import annotations

import numpy as np
import pandas as pd

SCENARIOS = {
    "Global Financial Crisis": ("2008-09-01", "2009-03-09"),
    "Euro debt crisis 2011": ("2011-07-22", "2011-10-03"),
    "Q4 2018 sell-off": ("2018-09-20", "2018-12-24"),
    "COVID-19 crash": ("2020-02-19", "2020-03-23"),
    "2022 inflation / rate shock": ("2022-01-03", "2022-10-12"),
}


def historical_stress(weights: pd.Series, raw_prices: pd.DataFrame,
                      exclude: list[str] | None = None) -> pd.DataFrame:
    """Buy-and-hold P&L of today's weights over each crisis window:
    R_p = sum_i w_i (P_i,end / P_i,start - 1).

    Assets without data in a window (e.g. not yet listed) are dropped and the
    remaining weights renormalised; 'coverage' reports the weight actually tested.
    """
    exclude = set(exclude or [])
    w = weights[weights > 0]
    rows = []
    for name, (s, e) in SCENARIOS.items():
        px = raw_prices.reindex(columns=w.index).loc[s:e]
        if len(px) < 2:
            continue
        ok = [t for t in w.index if t not in exclude and px[t].iloc[:5].notna().any()
              and px[t].iloc[-5:].notna().any()]
        if not ok:
            continue
        first = px[ok].bfill().iloc[0]
        last = px[ok].ffill().iloc[-1]
        asset_ret = last / first - 1
        cov_w = w[ok].sum()
        port = float((w[ok] / cov_w) @ asset_ret)
        worst = asset_ret.idxmin()
        rows.append({"scenario": name, "start": s, "end": e, "portfolio return": port,
                     "worst asset": worst, "worst asset return": float(asset_ret[worst]),
                     "coverage": float(cov_w)})
    return pd.DataFrame(rows).set_index("scenario") if rows else pd.DataFrame()


def betas(returns: pd.DataFrame, market: pd.Series) -> pd.Series:
    """OLS beta of each asset on the market: beta_i = Cov(r_i, r_m) / Var(r_m)."""
    df = returns.join(market.rename("_mkt"), how="inner").dropna()
    var_m = df["_mkt"].var()
    return df.drop(columns="_mkt").apply(lambda s: s.cov(df["_mkt"]) / var_m)


def market_shock(weights: pd.Series, returns: pd.DataFrame, market: pd.Series,
                 shocks=(-0.10, -0.20, -0.30, -0.40), capital: float = 1.0) -> pd.DataFrame:
    """Single-factor (CAPM) shock: asset i moves beta_i * shock, so the portfolio moves
    beta_p * shock with beta_p = sum_i w_i beta_i. Ignores idiosyncratic moves and
    correlation breakdown, so treat it as a first-order estimate."""
    b = betas(returns, market).reindex(weights.index).fillna(0)
    beta_p = float(weights @ b)
    return pd.DataFrame({"market shock": list(shocks),
                         "portfolio beta": beta_p,
                         "portfolio return": [beta_p * s for s in shocks],
                         "P&L": [beta_p * s * capital for s in shocks]}).set_index("market shock")
