"""Streamlit dashboard.   Run:  streamlit run app.py"""
from __future__ import annotations

import warnings
from datetime import date

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio.data import download_prices, download_risk_free
from portfolio.estimators import COV_METHODS, MU_METHODS
from portfolio.optimizers import METHODS, RISK_PROFILES, parse_views
from portfolio.pipeline import DEFAULT_BACKTEST, DEFAULT_UNIVERSE, STRESS_START, PortfolioConfig, run_pipeline
from portfolio.report import strategist_brief

warnings.filterwarnings("ignore")
st.set_page_config(page_title="Quant Portfolio Lab", layout="wide")


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def load(tickers: tuple[str, ...], start: str, end: str, offline: bool):
    return (download_prices(list(tickers), start, end, offline=offline),
            download_risk_free(start, end, offline=offline))


def parse_holdings(text: str) -> dict[str, float]:
    out = {}
    for line in text.strip().splitlines():
        if ":" in line:
            t, n = line.split(":", 1)
            out[t.strip().upper()] = float(n)
    return out


def pct_table(df: pd.DataFrame, pct_cols=(), dec_cols=()):
    fmt = {c: "{:.2%}" for c in pct_cols if c in df.columns}
    fmt.update({c: "{:.3f}" for c in dec_cols if c in df.columns})
    return df.style.format(fmt, na_rep="")


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Inputs")
    tickers = st.text_input("Universe (comma separated)", ", ".join(DEFAULT_UNIVERSE))
    c1, c2 = st.columns(2)
    start = c1.date_input("Start", date(2010, 1, 1))
    end = c2.date_input("End", date.today())
    offline = st.toggle("Offline: use bundled dataset only", False,
                        help="Uses data/prices_snapshot.csv.gz instead of Yahoo Finance (reproducible results).")
    capital = st.number_input("Capital ($)", 1_000.0, 1e9, 100_000.0, step=10_000.0)
    appetite = st.select_slider("Risk appetite", list(RISK_PROFILES), "moderate")
    method = st.selectbox("Optimiser", list(METHODS), format_func=lambda m: METHODS[m])
    with st.expander("Estimation & constraints"):
        mu_m = st.selectbox("Expected returns", list(MU_METHODS), format_func=lambda m: MU_METHODS[m])
        cov_m = st.selectbox("Covariance", list(COV_METHODS), format_func=lambda m: COV_METHODS[m])
        prof = RISK_PROFILES[appetite]
        max_w = st.slider("Max weight per asset", 0.05, 1.0, prof["max_weight"], 0.05)
        gamma = st.slider("Risk aversion gamma", 0.5, 20.0, prof["risk_aversion"], 0.5)
        lookback = st.slider("Estimation window (days)", 126, 1260, 504, 21)
        rf_override = st.number_input("Risk-free rate (blank = live T-bill)", value=None, format="%.4f")
    with st.expander("Black-Litterman views"):
        st.caption("One per line: `QQQ = 0.12 @ 0.6` (absolute) or `SPY - TLT = 0.03 @ 0.5` (relative). "
                   "Number after @ = confidence in (0,1].")
        views_txt = st.text_area("Views", "QQQ = 0.12 @ 0.6\nGLD - TLT = 0.02 @ 0.4")
    with st.expander("Current holdings (rebalance)"):
        st.caption("`TICKER: shares` per line. Leave empty for a fresh account funded with Capital.")
        hold_txt = st.text_area("Holdings", "")
        cash = st.number_input("Cash ($)", 0.0, 1e9, 0.0)
        threshold = st.slider("No-trade band (weight drift)", 0.0, 0.10, 0.02, 0.005)
    with st.expander("Backtest & simulation"):
        bt_methods = st.multiselect("Strategies to backtest", list(METHODS), DEFAULT_BACKTEST)
        rebal = st.selectbox("Rebalance every", [5, 21, 63], 1, format_func=lambda d: f"{d} days")
        cost = st.slider("Transaction cost (bps)", 0.0, 50.0, 10.0, 1.0)
        mc_method = st.selectbox("Monte Carlo model", ["bootstrap", "student_t", "gaussian"])
        horizon = st.slider("Horizon (days)", 21, 1260, 252, 21)
    go_btn = st.button("Run analysis", type="primary", use_container_width=True)

st.title("Quant Portfolio Lab")
st.caption("Portfolio construction with shrinkage estimators, ten optimisers, out-of-sample walk-forward "
           "testing, tail-risk analytics, Monte Carlo and stress tests. Educational tool - not investment advice.")

if not go_btn and "res" not in st.session_state:
    st.info("Set inputs in the sidebar and press **Run analysis**.")
    st.stop()

if go_btn:
    holdings = parse_holdings(hold_txt)
    cfg = PortfolioConfig(
        tickers=[t.strip().upper() for t in tickers.split(",") if t.strip()],
        start=str(start), end=str(end), capital=capital, risk_appetite=appetite, method=method,
        mu_method=mu_m, cov_method=cov_m, rf=rf_override, max_weight=max_w, risk_aversion=gamma,
        views=parse_views(views_txt), holdings=holdings, cash=cash if holdings or cash else None,
        rebalance_threshold=threshold, lookback=lookback, rebalance_every=rebal, cost_bps=cost,
        backtest_methods=bt_methods, mc_horizon=horizon, mc_method=mc_method)
    all_t = sorted(set(cfg.tickers) | set(holdings) | {cfg.benchmark})
    with st.status("Running pipeline...", expanded=False) as status:
        raw, rf = load(tuple(all_t), min(str(start), STRESS_START), str(end), offline)
        try:
            st.session_state.res = run_pipeline(cfg, raw, rf, progress=status.write)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        status.update(label="Done", state="complete")

res = st.session_state.res
cfg = res.config
for n in res.notes:
    st.warning(n)

w = res.allocation.weights
ea = res.ex_ante
k = st.columns(6)
k[0].metric("Expected return", f"{ea['Expected return (ann.)']:.1%}")
k[1].metric("Volatility", f"{ea['Volatility (ann.)']:.1%}")
k[2].metric("Sharpe (ex-ante)", f"{ea['Sharpe (ex-ante)']:.2f}")
k[3].metric("VaR 95% 1d", f"${ea['VaR 95% 1d ($, historical)']:,.0f}")
k[4].metric("Effective N", f"{ea['Effective N (1/HHI)']:.1f}")
k[5].metric("Risk-free", f"{res.rf:.2%}")

tabs = st.tabs(["Allocation", "Risk", "Frontier", "Backtest", "Monte Carlo", "Stress", "Rebalance", "Brief"])

with tabs[0]:
    c1, c2 = st.columns(2)
    nz = w[w > 1e-4].sort_values(ascending=False)
    c1.plotly_chart(px.pie(values=nz.values, names=nz.index, hole=0.5, title="Capital allocation"),
                    use_container_width=True)
    rc = res.risk_contrib
    comp = pd.DataFrame({"capital": rc["weight"], "risk": rc["pct_risk"]}).loc[nz.index]
    c2.plotly_chart(px.bar(comp, barmode="group", title="Capital vs risk contribution"),
                    use_container_width=True)
    tbl = res.asset_stats.join(w.rename("weight")).join(rc["pct_risk"].rename("% of risk"))
    tbl["dollars"] = tbl["weight"] * cfg.capital
    st.dataframe(tbl.sort_values("weight", ascending=False).style.format(
        {"exp. return": "{:.2%}", "volatility": "{:.2%}", "weight": "{:.2%}", "% of risk": "{:.2%}",
         "dollars": "${:,.0f}"}), use_container_width=True)

with tabs[1]:
    c1, c2 = st.columns(2)
    var_rows = []
    for a in (95, 99):
        for m in ("historical", "gaussian", "cornish_fisher"):
            var_rows.append({"confidence": f"{a}%", "model": m, "VaR": ea[f"VaR {a}% 1d ({m})"],
                             "CVaR": ea[f"CVaR {a}% 1d ({m})"]})
    c1.subheader("1-day tail risk")
    c1.dataframe(pd.DataFrame(var_rows).style.format({"VaR": "{:.2%}", "CVaR": "{:.2%}"}),
                 use_container_width=True, hide_index=True)
    c1.caption("Historical > Gaussian signals fat left tails; Cornish-Fisher adjusts for skew and kurtosis.")
    corr = res.returns.iloc[-cfg.lookback:].corr()
    c2.plotly_chart(px.imshow(corr, zmin=-1, zmax=1, color_continuous_scale="RdBu_r",
                              title="Correlation (estimation window)"), use_container_width=True)
    port = res.returns @ w
    hist = go.Figure(go.Histogram(x=port, nbinsx=120, name="daily return"))
    hist.add_vline(-ea["VaR 95% 1d (historical)"], line_dash="dash", annotation_text="VaR 95%")
    hist.update_layout(title="Distribution of daily portfolio returns (full history, today's weights)")
    st.plotly_chart(hist, use_container_width=True)

with tabs[2]:
    fr = res.frontier
    mu, cov = res.allocation.mu, res.allocation.cov
    fig = go.Figure()
    if not fr.empty:
        fig.add_trace(go.Scatter(x=fr["volatility"], y=fr["return"], mode="lines", name="Efficient frontier"))
    fig.add_trace(go.Scatter(x=np.sqrt(np.diag(cov.values)), y=mu.values, mode="markers+text",
                             text=mu.index, textposition="top center", name="Assets"))
    fig.add_trace(go.Scatter(x=[ea["Volatility (ann.)"]], y=[ea["Expected return (ann.)"]], mode="markers",
                             marker=dict(size=16, symbol="star"), name="Chosen portfolio"))
    if not fr.empty:
        sr = (fr["return"] - res.rf) / fr["volatility"]
        t = sr.idxmax()
        xs = np.linspace(0, fr["volatility"].max() * 1.1, 20)
        fig.add_trace(go.Scatter(x=xs, y=res.rf + sr[t] * xs, mode="lines", line=dict(dash="dot"),
                                 name="Capital market line"))
    fig.update_layout(xaxis_title="Volatility (ann.)", yaxis_title="Expected return (ann.)",
                      xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=550,
                      title=f"Long-only frontier (max weight {cfg.max_weight:.0%})")
    st.plotly_chart(fig, use_container_width=True)

with tabs[3]:
    if not res.backtests:
        st.info("Backtest not run (history too short for the chosen window).")
    else:
        st.caption(f"Walk-forward: re-estimate on the previous {cfg.lookback} days, rebalance every "
                   f"{cfg.rebalance_every} days, {cfg.cost_bps:.0f} bps cost per unit traded. "
                   "No information from after the rebalance date is used.")
        eq = pd.DataFrame({m: (1 + bt.returns).cumprod() for m, bt in res.backtests.items()})
        if res.benchmark_returns is not None:
            eq[f"{cfg.benchmark}"] = (1 + res.benchmark_returns.loc[eq.index[0]:]).cumprod()
        st.plotly_chart(px.line(eq, log_y=True, title="Growth of $1 (log scale)"), use_container_width=True)
        t = res.backtest_table
        st.dataframe(pct_table(t, ["CAGR", "Volatility", "Max Drawdown", "VaR 95% (1d)", "CVaR 95% (1d)"],
                               ["Sharpe", "Sortino", "Calmar", "Skewness", "Excess Kurtosis", "PSR (SR>0)",
                                "Beta", "Turnover (ann.)", "JKM z vs 1/N", "p-value vs 1/N", "p Holm vs 1/N",
                                "Sharpe CI low", "Sharpe CI high", "DSR", "Avg effective N"]),
                     use_container_width=True)
        st.caption("PSR: probability the true Sharpe > 0 given sample length, skew and kurtosis. "
                   "JKM: Jobson-Korkie-Memmel test of equal Sharpe ratios vs 1/N; 'p Holm' corrects for testing many "
                   "strategies at once. Sharpe CI: 95% block bootstrap. DSR: Deflated Sharpe Ratio, i.e. the PSR "
                   "against the best Sharpe expected from luck alone across all strategies tried.")
        dd = pd.DataFrame({m: (1 + bt.returns).cumprod() / (1 + bt.returns).cumprod().cummax() - 1
                           for m, bt in res.backtests.items()})
        st.plotly_chart(px.line(dd, title="Drawdowns"), use_container_width=True)
        bt = res.backtests[cfg.method]
        st.plotly_chart(px.area(bt.weights, title=f"{cfg.method}: weights through time"),
                        use_container_width=True)

with tabs[4]:
    paths = res.mc_paths * cfg.capital
    q = np.quantile(paths, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    x = np.arange(paths.shape[1])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=q[4], line=dict(width=0), showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=q[0], fill="tonexty", line=dict(width=0), name="5-95%"))
    fig.add_trace(go.Scatter(x=x, y=q[3], line=dict(width=0), showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=q[1], fill="tonexty", line=dict(width=0), name="25-75%"))
    fig.add_trace(go.Scatter(x=x, y=q[2], name="median", line=dict(width=2)))
    fig.update_layout(title=f"{paths.shape[0]:,} simulated paths ({cfg.mc_method}; weights drift, rebalanced "
                            f"every {cfg.rebalance_every}d, {cfg.cost_bps:.0f} bps costs - same process as the backtest)",
                      xaxis_title="trading days", yaxis_title="portfolio value ($)")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(pd.Series(res.mc_summary, name="value").to_frame(), use_container_width=True)

with tabs[5]:
    st.subheader("Historical crisis replay (today's weights, buy & hold)")
    st.caption("Applies TODAY's weights to past crisis windows without rebalancing; this is not a replay of the "
               "backtested strategy. Coverage < 100% means some assets had no data then: the return shown is "
               "conditional on the covered assets, with their weights renormalised.")
    if res.stress_hist.empty:
        st.info("No crisis windows covered by the data.")
    else:
        st.dataframe(res.stress_hist.style.format({"portfolio return": "{:.2%}", "worst asset return": "{:.2%}",
                                                   "coverage": "{:.0%}"}), use_container_width=True)
    if not res.stress_shock.empty:
        st.subheader(f"Market shock via beta to {cfg.benchmark}")
        st.dataframe(res.stress_shock.style.format({"portfolio beta": "{:.2f}", "portfolio return": "{:.2%}",
                                                    "P&L": "${:,.0f}"}), use_container_width=True)

with tabs[6]:
    s = res.trade_summary
    c = st.columns(4)
    c[0].metric("Portfolio value", f"${s['portfolio value']:,.0f}")
    c[1].metric("Gross traded", f"${s['gross traded']:,.0f}")
    c[2].metric("Est. cost", f"${s['estimated cost']:,.2f}")
    c[3].metric("Cash after", f"${s['cash after trades']:,.0f}")
    st.dataframe(res.trades.style.format({"price": "${:,.2f}", "current weight": "{:.2%}", "target weight": "{:.2%}",
                                          "drift": "{:+.2%}", "trade shares": "{:,.0f}", "trade value": "${:,.0f}",
                                          "current shares": "{:,.2f}"}), use_container_width=True)

with tabs[7]:
    st.markdown(strategist_brief(res))
