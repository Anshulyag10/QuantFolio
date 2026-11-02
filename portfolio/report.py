"""Deterministic analyst brief generated from the computed numbers (no LLM needed,
so every sentence is traceable to a figure in the analysis)."""
from __future__ import annotations

from .optimizers import METHODS


def _pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def strategist_brief(res) -> str:
    cfg, w, ea, rc = res.config, res.allocation.weights, res.ex_ante, res.risk_contrib
    top = w[w > 0.001].sort_values(ascending=False)
    lines = [f"## Strategist brief - {METHODS[cfg.method]}"]
    lines.append(
        f"**Allocation.** {len(top)} of {len(w)} assets held; largest positions "
        + ", ".join(f"{t} {_pct(v)}" for t, v in top.head(4).items())
        + f". Effective number of bets 1/HHI = {ea['Effective N (1/HHI)']:.1f}, "
        f"diversification ratio {ea['Diversification ratio']:.2f}.")

    lines.append(
        f"**Ex-ante profile.** Expected return {_pct(ea['Expected return (ann.)'])}, volatility "
        f"{_pct(ea['Volatility (ann.)'])}, Sharpe {ea['Sharpe (ex-ante)']:.2f} at rf = {_pct(res.rf, 2)}. "
        "Expected returns are the noisiest input; treat the return figure as a shrunk estimate, not a forecast.")

    hog = rc.sort_values("pct_risk", ascending=False).iloc[0]
    lines.append(
        f"**Risk budget.** {hog.name} carries {_pct(hog.pct_risk)} of portfolio volatility with "
        f"{_pct(hog.weight)} of capital" + (" - risk is more concentrated than capital."
                                           if hog.pct_risk > 1.5 * hog.weight else "."))

    v_h, v_cf = ea["VaR 95% 1d (historical)"], ea["VaR 95% 1d (cornish_fisher)"]
    v_g, cv_h = ea["VaR 95% 1d (gaussian)"], ea["CVaR 95% 1d (historical)"]
    tail = ("fatter than Gaussian" if max(v_h, v_cf) > 1.05 * v_g else "close to Gaussian")
    lines.append(
        f"**Tail risk.** 1-day 95% VaR {_pct(v_h, 2)} (historical) vs {_pct(v_g, 2)} (Gaussian): tails are {tail}. "
        f"Expected shortfall beyond VaR is {_pct(cv_h, 2)} (about ${ea['CVaR 95% 1d ($, historical)']:,.0f} "
        f"on ${cfg.capital:,.0f}).")

    if not res.stress_hist.empty:
        worst = res.stress_hist["portfolio return"].idxmin()
        row = res.stress_hist.loc[worst]
        lines.append(
            f"**Stress.** Worst replayed crisis: {worst} at {_pct(row['portfolio return'])} "
            f"(worst holding {row['worst asset']} {_pct(row['worst asset return'])}"
            + (f"; only {_pct(row['coverage'], 0)} of weight had data" if row["coverage"] < 0.99 else "") + ").")

    mc = res.mc_summary
    lines.append(
        f"**Monte Carlo ({cfg.mc_method}, {cfg.mc_horizon} days).** Median value ${mc['Median terminal value']:,.0f}, "
        f"5th percentile ${mc['5th percentile value']:,.0f}, P(loss) {_pct(mc['P(loss)'], 0)}, "
        f"P(drawdown > 20%) {_pct(mc['P(max drawdown > 20%)'], 0)}.")

    t = res.backtest_table
    if not t.empty and cfg.method in t.index:
        r = t.loc[cfg.method]
        ew = t.loc["equal_weight"]
        p_raw, p_holm = r.get("p-value vs 1/N", float("nan")), r.get("p Holm vs 1/N", float("nan"))
        sig = ("statistically significant" if p_holm < 0.05 else "NOT statistically significant after "
               f"Holm correction for {len(t) - 2} comparisons")
        verdict = ("beat" if r["Sharpe"] > ew["Sharpe"] else "lagged")
        lines.append(
            f"**Out-of-sample evidence.** In the walk-forward backtest (costs {cfg.cost_bps:.0f} bps) this rule "
            f"{verdict} 1/N on Sharpe ({r['Sharpe']:.2f} vs {ew['Sharpe']:.2f}); the difference is {sig} "
            f"(Jobson-Korkie-Memmel p = {p_raw:.3f}, Holm-adjusted {p_holm:.3f}). "
            f"95% block-bootstrap CI for its Sharpe: [{r['Sharpe CI low']:.2f}, {r['Sharpe CI high']:.2f}]. "
            f"Max drawdown {_pct(r['Max Drawdown'])}, annual turnover {r['Turnover (ann.)']:.1f}x. "
            f"PSR = {r['PSR (SR>0)']:.2f}; Deflated Sharpe Ratio (adjusting for {len(t) - 1} strategies tried) "
            f"= {r['DSR']:.2f}.")
        best = t.drop(index=[i for i in t.index if "buy & hold" in i])["Sharpe"].idxmax()
        if best != cfg.method:
            lines.append(f"The best out-of-sample Sharpe among tested rules was **{best}** "
                         f"({t.loc[best, 'Sharpe']:.2f}).")

    if res.trade_summary["gross traded"] > 0:
        n = int((res.trades["action"] != "HOLD").sum())
        lines.append(
            f"**Execution.** {n} trades, gross ${res.trade_summary['gross traded']:,.0f}, "
            f"estimated cost ${res.trade_summary['estimated cost']:,.0f}.")
    if res.synthetic:
        lines.append(f"**Warning.** Synthetic prices used for {', '.join(res.synthetic)} - results for those are illustrative only.")
    lines.append("_Research/educational tool, not investment advice._")
    return "\n\n".join(lines)
