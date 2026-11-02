"""Command-line run: saves figures, CSV tables and a markdown report to ./results.

Examples
  python run_analysis.py
  python run_analysis.py --method black_litterman --view "QQQ = 0.12 @ 0.6" --appetite aggressive
  python run_analysis.py --tickers AAPL MSFT JPM XOM JNJ --start 2015-01-01 --method hrp
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from portfolio.optimizers import METHODS, RISK_PROFILES, parse_views
from portfolio.pipeline import DEFAULT_UNIVERSE, PortfolioConfig, run_pipeline
from portfolio.report import strategist_brief

warnings.filterwarnings("ignore")
plt.rcParams.update({"figure.dpi": 130, "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False,
                     "axes.spines.right": False})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tickers", nargs="+", default=DEFAULT_UNIVERSE)
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--appetite", choices=list(RISK_PROFILES), default="moderate")
    p.add_argument("--method", choices=list(METHODS), default="max_sharpe")
    p.add_argument("--mu", default="james_stein", choices=["james_stein", "historical", "ewma"])
    p.add_argument("--cov", default="ledoit_wolf", choices=["ledoit_wolf", "sample", "ewma"])
    p.add_argument("--lookback", type=int, default=504)
    p.add_argument("--rebalance", type=int, default=21)
    p.add_argument("--cost-bps", type=float, default=10)
    p.add_argument("--view", action="append", default=[], help='Black-Litterman view, e.g. "SPY - TLT = 0.03 @ 0.5"')
    p.add_argument("--mc", default="bootstrap", choices=["bootstrap", "student_t", "gaussian"])
    p.add_argument("--out", default="results")
    p.add_argument("--offline", action="store_true", help="use only the bundled snapshot in data/ (reproducible)")
    a = p.parse_args()

    views = parse_views("\n".join(a.view))
    cfg = PortfolioConfig(tickers=a.tickers, start=a.start, end=a.end, capital=a.capital,
                          risk_appetite=a.appetite, method=a.method, mu_method=a.mu, cov_method=a.cov,
                          lookback=a.lookback, rebalance_every=a.rebalance, cost_bps=a.cost_bps,
                          views=views, mc_method=a.mc, offline=a.offline)
    res = run_pipeline(cfg, progress=lambda m: print(f"  - {m}"))
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    save_outputs(res, out)
    print(f"\nSaved figures, tables and report.md to {out.resolve()}")


def md_table(df: pd.DataFrame, fmt: str = "{:.4f}") -> str:
    """Markdown table without the optional ``tabulate`` dependency."""
    if df.empty:
        return "_(none)_"
    cell = lambda v: fmt.format(v) if isinstance(v, (float, np.floating)) else str(v)
    head = "| " + " | ".join([str(df.index.name or "")] + [str(c) for c in df.columns]) + " |"
    sep = "|" + "---|" * (len(df.columns) + 1)
    rows = ["| " + " | ".join([str(i)] + [cell(v) for v in r]) + " |" for i, r in zip(df.index, df.values)]
    return "\n".join([head, sep] + rows)


def save_outputs(res, out: Path):
    cfg, w = res.config, res.allocation.weights

    # tables
    tbl = res.asset_stats.join(w.rename("weight")).join(res.risk_contrib["pct_risk"].rename("pct_risk"))
    tbl.to_csv(out / "allocation.csv")
    pd.Series(res.ex_ante).to_csv(out / "ex_ante_risk.csv", header=["value"])
    if not res.backtest_table.empty:
        res.backtest_table.to_csv(out / "backtest_metrics.csv")
    res.stress_hist.to_csv(out / "stress_historical.csv")
    res.stress_shock.to_csv(out / "stress_market_shock.csv")
    res.trades.to_csv(out / "trades.csv")
    pd.Series(res.mc_summary).to_csv(out / "monte_carlo.csv", header=["value"])

    # 1. allocation vs risk contribution
    nz = w[w > 1e-4].sort_values(ascending=False).index
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(nz))
    ax.bar(x - 0.2, w[nz], 0.4, label="capital weight")
    ax.bar(x + 0.2, res.risk_contrib.loc[nz, "pct_risk"], 0.4, label="risk contribution")
    ax.set_xticks(x, nz)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title(f"{METHODS[cfg.method]}: capital vs risk")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "fig1_allocation.png")
    plt.close(fig)

    # 2. efficient frontier
    fig, ax = plt.subplots(figsize=(8, 5))
    fr, mu, cov = res.frontier, res.allocation.mu, res.allocation.cov
    if not fr.empty:
        ax.plot(fr["volatility"], fr["return"], lw=2, label="long-only efficient frontier")
        sr = (fr["return"] - res.rf) / fr["volatility"]
        t = sr.idxmax()
        xs = np.linspace(0, fr["volatility"].max() * 1.1, 10)
        ax.plot(xs, res.rf + sr[t] * xs, ls=":", label=f"CML (SR={sr[t]:.2f})")
    vols = np.sqrt(np.diag(cov.values))
    ax.scatter(vols, mu, s=25)
    for tk, xv, yv in zip(mu.index, vols, mu.values):
        ax.annotate(tk, (xv, yv), textcoords="offset points", xytext=(4, 3), fontsize=8)
    ax.scatter(res.ex_ante["Volatility (ann.)"], res.ex_ante["Expected return (ann.)"], marker="*", s=250,
               c="crimson", zorder=5, label="chosen portfolio")
    ax.set_xlabel("volatility (ann.)")
    ax.set_ylabel("expected return (ann.)")
    ax.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "fig2_frontier.png")
    plt.close(fig)

    # 3/4. backtest equity and drawdowns
    if res.backtests:
        fig, ax = plt.subplots(figsize=(10, 5))
        for m, bt in res.backtests.items():
            ax.plot((1 + bt.returns).cumprod(), lw=2.2 if m == cfg.method else 1.1, label=m)
        if res.benchmark_returns is not None:
            b = res.benchmark_returns.loc[next(iter(res.backtests.values())).returns.index[0]:]
            ax.plot((1 + b).cumprod(), "k--", lw=1, label=f"{cfg.benchmark} buy & hold")
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(plt.matplotlib.ticker.FormatStrFormatter("$%.1f"))
        ax.yaxis.set_minor_formatter(plt.matplotlib.ticker.NullFormatter())
        ax.set_title(f"Walk-forward out-of-sample growth of $1 (lookback {cfg.lookback}d, "
                     f"rebalance {cfg.rebalance_every}d, {cfg.cost_bps:.0f} bps)")
        ax.legend(fontsize=8, ncol=2)
        fig.tight_layout()
        fig.savefig(out / "fig3_backtest.png")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4))
        for m in dict.fromkeys([cfg.method, "equal_weight", "min_variance", "hrp"]):
            if m in res.backtests:
                wealth = (1 + res.backtests[m].returns).cumprod()
                ax.plot(wealth / wealth.cummax() - 1, lw=1, label=m)
        ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
        ax.set_title("Drawdowns")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / "fig4_drawdowns.png")
        plt.close(fig)

        bt = res.backtests[cfg.method]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.stackplot(bt.weights.index, bt.weights.T.values, labels=bt.weights.columns)
        ax.set_ylim(0, 1)
        ax.set_title(f"{cfg.method}: weights through time")
        ax.legend(fontsize=7, ncol=6, loc="upper center", bbox_to_anchor=(0.5, -0.08))
        fig.tight_layout()
        fig.savefig(out / "fig5_weights.png")
        plt.close(fig)

    # 6. Monte Carlo fan
    paths = res.mc_paths * cfg.capital
    q = np.quantile(paths, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    xs = np.arange(paths.shape[1])
    ax.fill_between(xs, q[0], q[4], alpha=0.2, label="5-95%")
    ax.fill_between(xs, q[1], q[3], alpha=0.35, label="25-75%")
    ax.plot(xs, q[2], lw=2, label="median")
    ax.set_title(f"Monte Carlo ({cfg.mc_method}, {paths.shape[0]:,} paths)")
    ax.set_xlabel("trading days")
    ax.set_ylabel("value ($)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "fig6_monte_carlo.png")
    plt.close(fig)

    # 7. correlation heatmap
    corr = res.returns.iloc[-cfg.lookback:].corr()
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=90)
    ax.set_yticks(range(len(corr)), corr.index)
    fig.colorbar(im)
    ax.set_title("Correlation (estimation window)")
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(out / "fig7_correlation.png")
    plt.close(fig)

    # markdown report
    md = [f"# Portfolio analysis - {cfg.method}", "",
          f"Universe: {', '.join(res.prices.columns)}  |  data {res.prices.index[0].date()} to "
          f"{res.prices.index[-1].date()}  |  mu: {cfg.mu_method}, Sigma: {cfg.cov_method}  |  "
          f"risk appetite: {cfg.risk_appetite}", ""]
    md += [f"> {n}" for n in res.notes]
    md += ["", strategist_brief(res), "", "## Allocation", "", md_table(tbl, "{:.4f}"), ""]
    if not res.backtest_table.empty:
        md += ["## Walk-forward backtest", "", md_table(res.backtest_table, "{:.3f}"), ""]
    md += ["## Stress tests", "", md_table(res.stress_hist, "{:.3f}"), "",
           md_table(res.stress_shock, "{:.3f}"), "", "## Trades", "", md_table(res.trades, "{:.3f}")]
    md += ["", "![](fig1_allocation.png)", "![](fig2_frontier.png)", "![](fig3_backtest.png)",
           "![](fig4_drawdowns.png)", "![](fig5_weights.png)", "![](fig6_monte_carlo.png)",
           "![](fig7_correlation.png)"]
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
