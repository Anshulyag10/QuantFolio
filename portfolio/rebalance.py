"""Turn target weights into a trade list for an existing (or empty) account."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rebalance_plan(target: pd.Series, last_prices: pd.Series, holdings: dict[str, float] | None = None,
                   cash: float = 0.0, threshold: float = 0.02, cost_bps: float = 10.0,
                   whole_shares: bool = True) -> tuple[pd.DataFrame, dict]:
    """Trades needed to move from ``holdings`` (shares) + ``cash`` to ``target`` weights.

    Only positions whose |target - current| weight drift exceeds ``threshold`` are
    traded (a no-trade band that avoids paying costs for tiny deviations). Holdings
    outside the target universe are sold.
    """
    holdings = {k.upper(): v for k, v in (holdings or {}).items()}
    universe = sorted(set(target.index) | set(holdings))
    px = last_prices.reindex(universe)
    if px.isna().any():
        missing = list(px[px.isna()].index)
        raise ValueError(f"No price for {missing}; add them to the universe or remove from holdings.")
    shares = pd.Series({t: holdings.get(t, 0.0) for t in universe})
    value = shares * px
    total = value.sum() + cash
    if total <= 0:
        raise ValueError("Portfolio value must be positive (enter capital as cash or holdings).")
    cur_w = value / total
    tgt_w = target.reindex(universe).fillna(0.0)
    drift = tgt_w - cur_w
    trade_value = np.where(drift.abs() >= threshold, drift * total, 0.0)
    trade_shares = trade_value / px
    if whole_shares:
        trade_shares = np.trunc(trade_shares)
        trade_value = trade_shares * px
    plan = pd.DataFrame({
        "price": px, "current shares": shares, "current weight": cur_w, "target weight": tgt_w,
        "drift": drift, "action": np.where(trade_shares > 0, "BUY", np.where(trade_shares < 0, "SELL", "HOLD")),
        "trade shares": trade_shares, "trade value": trade_value,
    })
    traded = np.abs(plan["trade value"]).sum()
    summary = {
        "portfolio value": total,
        "gross traded": traded,
        "turnover (% of value)": traded / total,
        "estimated cost": traded * cost_bps / 1e4,
        "cash after trades": cash - plan["trade value"].sum() - traded * cost_bps / 1e4,
    }
    return plan, summary
