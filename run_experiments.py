"""Research experiments: estimator ablation, multiple-testing-aware inference, untouched holdout,
and parameter sensitivity. Writes CSVs, heatmaps and experiments.md to results/experiments/.

Research question: can risk-aware optimisation produce more stable portfolios than 1/N and
mean-variance on a commodity-heavy multi-asset universe, after costs and out of sample?

    python run_experiments.py                 # bundled snapshot (reproducible), commodity-heavy universe
    python run_experiments.py --online        # fresh Yahoo data
    python run_experiments.py --quick         # smaller sensitivity grid
"""
from __future__ import annotations

import argparse
import time
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from portfolio import optimizers as opt
from portfolio.backtest import memoize, walk_forward
from portfolio.data import download_prices, download_risk_free, prepare_prices, to_returns
from portfolio.pipeline import evaluate_backtests
from portfolio.risk import daily_rf, performance_metrics

warnings.filterwarnings("ignore")
UNIVERSE = ["DBC", "GLD", "SLV", "CPER", "USO", "UNG", "DBA", "CORN", "WEAT", "SPY", "TLT"]
HOLDOUT_START = "2022-01-01"
MAX_W = 0.35

# id: (description, method, mu estimator, covariance estimator)
ABLATION = {
    "E0": ("1/N baseline", "equal_weight", "historical", "sample"),
    "E1": ("MV  hist mu + sample cov", "mean_variance", "historical", "sample"),
    "E2": ("MV  hist mu + Ledoit-Wolf", "mean_variance", "historical", "ledoit_wolf"),
    "E3": ("MV  Bayes-Stein + sample cov", "mean_variance", "james_stein", "sample"),
    "E4": ("MV  Bayes-Stein + Ledoit-Wolf", "mean_variance", "james_stein", "ledoit_wolf"),
    "E5": ("MaxSR  hist mu + sample cov", "max_sharpe", "historical", "sample"),
    "E6": ("MaxSR  Bayes-Stein + Ledoit-Wolf", "max_sharpe", "james_stein", "ledoit_wolf"),
    "E7": ("MinVar  sample cov", "min_variance", "historical", "sample"),
    "E8": ("MinVar  Ledoit-Wolf", "min_variance", "historical", "ledoit_wolf"),
    "E9": ("MinCVaR 95% (scenarios, no mu/Sigma)", "min_cvar", "historical", "sample"),
    "E10": ("HRP  sample cov", "hrp", "historical", "sample"),
    "E11": ("HRP  Ledoit-Wolf", "hrp", "historical", "ledoit_wolf"),
}


def make_strategy(method, mu_m, cov_m, rf_lookup, max_w=MAX_W, gamma=4.0, beta=0.95):
    def run(window):
        return opt.optimize(method, window, mu_method=mu_m, cov_method=cov_m, rf=rf_lookup(window.index[-1]),
                            risk_aversion=gamma, max_weight=max_w, cvar_beta=beta).weights
    return memoize(run)


def heatmap(df: pd.DataFrame, title: str, path: Path, fmt: str = "{:.2f}", cmap="RdYlGn"):
    fig, ax = plt.subplots(figsize=(1.1 * df.shape[1] + 3, 0.5 * df.shape[0] + 1.8))
    im = ax.imshow(df.values.astype(float), cmap=cmap, aspect="auto")
    ax.set_xticks(range(df.shape[1]), df.columns, rotation=30, ha="right")
    ax.set_yticks(range(df.shape[0]), df.index)
    for i in range(df.shape[0]):
        for j in range(df.shape[1]):
            v = df.values[i, j]
            if pd.notna(v):
                ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def md(df: pd.DataFrame, fmt="{:.3f}") -> str:
    cell = lambda v: fmt.format(v) if isinstance(v, (float, np.floating)) and pd.notna(v) else ("" if pd.isna(v) else str(v))
    head = "| " + " | ".join([str(df.index.name or "")] + [str(c) for c in df.columns]) + " |"
    rows = ["| " + " | ".join([str(i)] + [cell(v) for v in r]) + " |" for i, r in zip(df.index, df.values)]
    return "\n".join([head, "|" + "---|" * (df.shape[1] + 1)] + rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tickers", nargs="+", default=UNIVERSE)
    p.add_argument("--start", default="2005-01-01")
    p.add_argument("--online", action="store_true")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--out", default="results/experiments")
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)

    raw = download_prices(a.tickers, a.start, offline=not a.online)
    rf_s = download_risk_free(a.start, offline=not a.online)
    prices, synth, notes = prepare_prices(raw, a.tickers, a.start, allow_synthetic=False)
    R = to_returns(prices)
    rf = rf_s if rf_s is not None else 0.04
    rf_lookup = (lambda ts: float(rf_s.loc[:ts].iloc[-1])) if rf_s is not None else (lambda ts: 0.04)
    log(f"{R.shape[1]} assets, {R.index[0].date()} -> {R.index[-1].date()}; " + " ".join(notes))
    lines = ["# Experiments", "",
             f"Universe: {', '.join(R.columns)}. Daily data {R.index[0].date()} to {R.index[-1].date()}. "
             f"Walk-forward: 504-day window, rebalance every 21 days, 10 bps costs, max weight {MAX_W:.0%}, "
             f"gamma = 4. Data source: {'Yahoo' if a.online else 'bundled snapshot'}.", ""]

    # ---------------------------------------------------------------- 1. ablation
    log("Ablation")
    strategies = {k: make_strategy(m, mu, cv, rf_lookup) for k, (_, m, mu, cv) in ABLATION.items()}
    bts = {k: walk_forward(R, s, k, 504, 21, 10.0) for k, s in strategies.items()}
    table = evaluate_backtests(bts, rf, baseline="E0")
    table.insert(0, "experiment", [ABLATION[k][0] for k in table.index])
    table.index.name = "id"
    table.to_csv(out / "ablation.csv")
    cols = ["experiment", "CAGR", "Volatility", "Sharpe", "Sharpe CI low", "Sharpe CI high", "Max Drawdown",
            "Turnover (ann.)", "Avg effective N", "p-value vs 1/N", "p Holm vs 1/N", "DSR"]
    lines += ["## 1. Estimator ablation (full out-of-sample period)", "",
              "Each row changes ONE ingredient. Pairs to compare: E1->E2 and E3->E4 (covariance shrinkage), "
              "E1->E3 and E2->E4 (mean shrinkage), E5->E6 (both, max Sharpe), E7->E8 and E10->E11 (covariance "
              "only, no mu needed).", "", md(table[cols]), ""]

    # ------------------------------------------------- 2. selection vs holdout
    log("Holdout")
    sel, hold = {}, {}
    for k, bt in bts.items():
        sel[k] = performance_metrics(bt.returns.loc[:HOLDOUT_START], rf)
        hold[k] = performance_metrics(bt.returns.loc[HOLDOUT_START:], rf)
    sel, hold = pd.DataFrame(sel).T, pd.DataFrame(hold).T
    ho = pd.DataFrame({"experiment": table["experiment"],
                       "Sharpe (selection)": sel["Sharpe"], "rank (selection)": sel["Sharpe"].rank(ascending=False),
                       "Sharpe (holdout)": hold["Sharpe"], "rank (holdout)": hold["Sharpe"].rank(ascending=False),
                       "MaxDD (holdout)": hold["Max Drawdown"]})
    ho.index.name = "id"
    ho.to_csv(out / "holdout.csv")
    best = ho["Sharpe (selection)"].idxmax()
    rho = ho["Sharpe (selection)"].corr(ho["Sharpe (holdout)"], method="spearman")
    lines += [f"## 2. Untouched holdout ({HOLDOUT_START} onward)", "",
              f"Strategies are ranked on the selection period only (start to {HOLDOUT_START}); the holdout is never "
              f"used for any choice. Best in selection: **{best}** ({ho.loc[best, 'experiment']}), holdout rank "
              f"**{int(ho.loc[best, 'rank (holdout)'])} of {len(ho)}**. Spearman rank correlation selection vs "
              f"holdout: **{rho:.2f}**.", "", md(ho), ""]

    # --------------------------------------------- 3. sensitivity: window x rebalance
    log("Sensitivity: lookback x rebalance")
    sens_methods = {"1/N": ("equal_weight", "historical", "sample"),
                    "MinVar LW": ("min_variance", "historical", "ledoit_wolf"),
                    "MinCVaR": ("min_cvar", "historical", "sample"),
                    "HRP LW": ("hrp", "historical", "ledoit_wolf"),
                    "MV BS+LW": ("mean_variance", "james_stein", "ledoit_wolf")}
    lookbacks = [252, 504] if a.quick else [252, 504, 756]
    rebals = [21, 63]
    first = max(lookbacks)          # common evaluation start so configurations are comparable
    eval_start = R.index[first]
    sh, dd = {}, {}
    for name, (m, mu, cv) in sens_methods.items():
        for L in lookbacks:
            for k in rebals:
                s = make_strategy(m, mu, cv, rf_lookup)
                r = walk_forward(R, s, name, L, k, 10.0).returns.loc[eval_start:]
                met = performance_metrics(r, rf)
                sh[(name, f"L={L}, k={k}")] = met["Sharpe"]
                dd[(name, f"L={L}, k={k}")] = met["Max Drawdown"]
        log(f"  {name}")
    sh_df, dd_df = pd.Series(sh).unstack(), pd.Series(dd).unstack()
    heatmap(sh_df, "Out-of-sample Sharpe: lookback L x rebalance k", out / "heat_sharpe_window.png")
    heatmap(dd_df, "Max drawdown: lookback L x rebalance k", out / "heat_mdd_window.png", "{:.0%}")
    sh_df.to_csv(out / "sens_window_sharpe.csv")
    dd_df.to_csv(out / "sens_window_mdd.csv")

    # ---------------------------------------------------- 4. sensitivity: costs
    log("Sensitivity: transaction costs")
    costs = [0, 5, 10, 25, 50]
    cs = {}
    for name, (m, mu, cv) in sens_methods.items():
        s = make_strategy(m, mu, cv, rf_lookup)              # memoised: one optimisation pass per method
        for c in costs:
            cs[(name, f"{c} bps")] = performance_metrics(walk_forward(R, s, name, 504, 21, c).returns, rf)["Sharpe"]
    cs_df = pd.Series(cs).unstack()[[f"{c} bps" for c in costs]]
    heatmap(cs_df, "Out-of-sample Sharpe vs transaction cost", out / "heat_sharpe_costs.png")
    cs_df.to_csv(out / "sens_costs_sharpe.csv")

    # ------------------------------------------------- 5. sensitivity: weight cap
    log("Sensitivity: max weight")
    caps = [0.2, 0.3, 0.35, 0.5, 1.0]
    cap_methods = {"MV BS+LW": ("mean_variance", "james_stein", "ledoit_wolf"),
                   "MaxSR BS+LW": ("max_sharpe", "james_stein", "ledoit_wolf"),
                   "MinCVaR": ("min_cvar", "historical", "sample")}
    cp_sh, cp_dd = {}, {}
    for name, (m, mu, cv) in cap_methods.items():
        for u in caps:
            r = walk_forward(R, make_strategy(m, mu, cv, rf_lookup, max_w=u), name, 504, 21, 10.0).returns
            met = performance_metrics(r, rf)
            cp_sh[(name, f"cap {u:.0%}")], cp_dd[(name, f"cap {u:.0%}")] = met["Sharpe"], met["Max Drawdown"]
        log(f"  {name}")
    cap_sh, cap_dd = pd.Series(cp_sh).unstack(), pd.Series(cp_dd).unstack()
    order = [f"cap {u:.0%}" for u in caps]
    cap_sh, cap_dd = cap_sh[order], cap_dd[order]
    heatmap(cap_sh, "Out-of-sample Sharpe vs max weight", out / "heat_sharpe_cap.png")
    heatmap(cap_dd, "Max drawdown vs max weight", out / "heat_mdd_cap.png", "{:.0%}")
    cap_sh.to_csv(out / "sens_cap_sharpe.csv")

    # ------------------------------------------------ 6. sensitivity: CVaR level
    log("Sensitivity: CVaR confidence")
    cv_rows = {}
    for b in (0.90, 0.95, 0.99):
        r = walk_forward(R, make_strategy("min_cvar", "historical", "sample", rf_lookup, beta=b),
                         "cvar", 504, 21, 10.0).returns
        met = performance_metrics(r, rf)
        cv_rows[f"beta = {b:.2f}"] = {k: met[k] for k in ("CAGR", "Volatility", "Sharpe", "Max Drawdown",
                                                          "CVaR 95% (1d)")}
    cv_df = pd.DataFrame(cv_rows).T
    cv_df.to_csv(out / "sens_cvar_beta.csv")

    lines += ["## 3. Sensitivity", "",
              f"Window x rebalance (all evaluated from {eval_start.date()} so the periods match):", "",
              "![](heat_sharpe_window.png)", "![](heat_mdd_window.png)", "", md(sh_df, "{:.2f}"), "",
              "Transaction costs (bps per unit traded):", "", "![](heat_sharpe_costs.png)", "", md(cs_df, "{:.2f}"), "",
              "Maximum weight per asset:", "", "![](heat_sharpe_cap.png)", "![](heat_mdd_cap.png)", "",
              md(cap_sh, "{:.2f}"), "", "Min-CVaR confidence level:", "", md(cv_df), ""]

    # ----------------------------------------------------------- 7. equity plot
    fig, ax = plt.subplots(figsize=(10, 5))
    for k in ("E0", "E1", "E4", "E8", "E9", "E11"):
        ax.plot((1 + bts[k].returns).cumprod(), lw=1.3, label=f"{k}: {ABLATION[k][0]}")
    ax.axvline(pd.Timestamp(HOLDOUT_START), color="k", ls="--", lw=1)
    ax.text(pd.Timestamp(HOLDOUT_START), ax.get_ylim()[1] * 0.97, " holdout", va="top")
    ax.set_yscale("log")
    ax.set_title("Ablation: out-of-sample growth of $1")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "ablation_equity.png", dpi=130)
    plt.close(fig)
    lines += ["![](ablation_equity.png)"]

    (out / "experiments.md").write_text("\n".join(lines), encoding="utf-8")
    log(f"Done -> {out.resolve()}")


if __name__ == "__main__":
    main()
