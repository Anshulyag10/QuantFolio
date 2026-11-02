"""Offline tests: synthetic data only, checking each component against known mathematical properties."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio import optimizers as opt
from portfolio.backtest import walk_forward
from portfolio.data import synthetic_prices, to_returns
from portfolio.estimators import covariance, expected_returns, mu_james_stein
from portfolio.rebalance import rebalance_plan
from portfolio.risk import (drawdown, probabilistic_sharpe_ratio, risk_contributions, sharpe_difference_test,
                            var_cvar)
from portfolio.simulation import simulate_paths
from portfolio.pipeline import PortfolioConfig, run_pipeline

TICKERS = ["A", "B", "C", "D", "E", "F"]


@pytest.fixture(scope="module")
def returns():
    return to_returns(synthetic_prices(TICKERS, 1500, seed=7))


@pytest.fixture(scope="module")
def cov(returns):
    return covariance(returns, "ledoit_wolf")


@pytest.mark.parametrize("method", list(opt.METHODS))
def test_weights_valid(method, returns):
    res = opt.optimize(method, returns, max_weight=0.35, views=[opt.View({"A": 1}, 0.15, 0.7)])
    w = res.weights
    assert abs(w.sum() - 1) < 1e-6
    assert (w >= -1e-8).all()
    if method != "equal_weight":
        assert w.max() <= 0.35 + 1e-4, method
    assert not res.notes, res.notes  # no solver fallback


def test_min_variance_is_minimal(returns, cov):
    w_mv = opt.min_variance(cov)
    var = lambda w: w.values @ cov.values @ w.values
    for m in ("equal_weight", "inverse_vol", "hrp", "risk_parity", "max_diversification"):
        assert var(w_mv) <= var(opt.optimize(m, returns).weights) + 1e-10


def test_max_sharpe_beats_frontier(returns, cov):
    mu = expected_returns(returns, "historical")
    w = opt.max_sharpe(mu, cov, rf=0.01)
    sr = lambda w: (mu @ w - 0.01) / np.sqrt(w @ cov.values @ w)
    rng = np.random.default_rng(0)
    for _ in range(2000):
        x = rng.dirichlet(np.ones(len(mu)))
        assert sr(w.values) >= sr(x) - 1e-6


def test_min_variance_unconstrained_closed_form(cov):
    """With loose bounds and no shorting binding, compare with Sigma^-1 1 / 1'Sigma^-1 1 when it is long-only."""
    inv = np.linalg.inv(cov.values) @ np.ones(len(cov))
    w_cf = inv / inv.sum()
    if (w_cf > 0).all():
        np.testing.assert_allclose(opt.min_variance(cov).values, w_cf, atol=1e-4)


def test_risk_parity_equal_contributions(cov):
    w = opt.risk_parity(cov)
    pct = risk_contributions(w, cov)["pct_risk"]
    np.testing.assert_allclose(pct.values, 1 / len(w), atol=1e-4)
    assert abs(pct.sum() - 1) < 1e-10


def test_hrp_diagonal_equals_inverse_variance():
    """With zero correlation HRP reduces to inverse-variance weights."""
    vols = np.array([0.1, 0.2, 0.3, 0.4])
    cov = pd.DataFrame(np.diag(vols**2), index=list("WXYZ"), columns=list("WXYZ"))
    w = opt.hrp(cov)
    iv = 1 / vols**2
    np.testing.assert_allclose(w.values, iv / iv.sum(), atol=1e-10)


def test_black_litterman_no_views_returns_prior(cov):
    w_mkt = pd.Series(1 / len(cov), index=cov.index)
    mu, post, pi = opt.black_litterman(cov, [], w_mkt, delta=2.5, tau=0.05, rf=0.02)
    np.testing.assert_allclose(mu.values, pi.values)
    np.testing.assert_allclose(pi.values - 0.02, 2.5 * cov.values @ w_mkt.values)


def test_black_litterman_full_confidence_hits_view(cov):
    w_mkt = pd.Series(1 / len(cov), index=cov.index)
    mu, _, _ = opt.black_litterman(cov, [opt.View({"A": 1, "B": -1}, 0.05, 1.0)], w_mkt, rf=0.0)
    assert abs((mu["A"] - mu["B"]) - 0.05) < 1e-8


def test_black_litterman_confidence_monotone(cov):
    w_mkt = pd.Series(1 / len(cov), index=cov.index)
    gaps = []
    for c in (0.1, 0.5, 0.9):
        mu, _, pi = opt.black_litterman(cov, [opt.View({"A": 1}, 0.30, c)], w_mkt)
        gaps.append(abs(mu["A"] - 0.30))
    assert gaps[0] > gaps[1] > gaps[2]


def test_cap_weights():
    w = opt.cap_weights(pd.Series([0.7, 0.2, 0.1], index=list("abc")), 0.4)
    assert abs(w.sum() - 1) < 1e-12 and w.max() <= 0.4 + 1e-12


def test_james_stein_shrinks(returns):
    js, hist = mu_james_stein(returns), expected_returns(returns, "historical")
    assert js.std() <= hist.std() + 1e-12


def test_var_cvar_gaussian_matches_theory():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 400_000)
    v_h, c_h = var_cvar(r, 0.95, "historical")
    v_g, c_g = var_cvar(r, 0.95, "gaussian")
    v_cf, c_cf = var_cvar(r, 0.95, "cornish_fisher")
    assert abs(v_g - 0.01645) < 2e-4 and abs(c_g - 0.02063) < 2e-4   # 1.645 sigma, phi(1.645)/0.05 sigma
    assert abs(v_h - v_g) < 2e-4 and abs(c_h - c_g) < 2e-4
    assert abs(v_cf - v_g) < 2e-4 and abs(c_cf - c_g) < 3e-4
    assert c_h >= v_h


def test_drawdown():
    r = pd.Series([0.10, -0.50, 0.20])
    dd = drawdown(r)
    np.testing.assert_allclose(dd.values, [0.0, -0.5, -0.4])
    assert drawdown(pd.Series([-0.1]))[0] == pytest.approx(-0.1)


def test_psr_and_sharpe_test():
    rng = np.random.default_rng(2)
    good = pd.Series(rng.normal(0.002, 0.01, 2000))     # daily SR 0.2 -> z ~ 9, PSR ~ 1
    noise = pd.Series(rng.normal(0.0, 0.01, 2000))
    assert probabilistic_sharpe_ratio(good) > 0.99
    assert 0.0 < probabilistic_sharpe_ratio(noise) < 1.0
    z, p = sharpe_difference_test(good, noise)
    assert z > 0 and p < 0.05


def test_backtest_no_lookahead_and_costs(returns):
    seen = []

    def spy(window):
        seen.append(window.index[-1])
        return pd.Series(1 / window.shape[1], index=window.columns)

    bt = walk_forward(returns, spy, lookback=252, rebalance_every=21, cost_bps=0)
    for last_seen, reb in zip(seen, bt.weights.index):
        assert last_seen < reb
    # zero-cost daily-rebalanced 1/N differs from drifting 1/N, but both start equal-weighted
    assert abs(bt.returns.iloc[0] - returns.iloc[252].mean()) < 1e-12
    bt_cost = walk_forward(returns, spy, lookback=252, rebalance_every=21, cost_bps=50)
    assert (bt_cost.returns <= bt.returns + 1e-15).all()
    assert bt_cost.turnover.iloc[0] == pytest.approx(1.0)  # initial purchase from cash


def test_buy_and_hold_drift_matches_prices():
    """Never rebalancing must reproduce buy-and-hold wealth exactly."""
    px = synthetic_prices(["X", "Y"], 400, seed=3)
    r = to_returns(px)
    bt = walk_forward(r, lambda w: pd.Series([0.5, 0.5], index=w.columns), lookback=10,
                      rebalance_every=10_000, cost_bps=0)
    wealth = (1 + bt.returns).cumprod().iloc[-1]
    bh = 0.5 * px["X"].iloc[-1] / px["X"].iloc[10] + 0.5 * px["Y"].iloc[-1] / px["Y"].iloc[10]
    assert wealth == pytest.approx(bh, rel=1e-10)


def test_monte_carlo_shapes(returns):
    w = pd.Series(1 / len(TICKERS), index=TICKERS)
    for m in ("bootstrap", "gaussian", "student_t"):
        p = simulate_paths(returns, w, horizon=50, n_paths=200, method=m)
        assert p.shape == (200, 51) and (p[:, 0] == 1).all() and (p > 0).all()


def test_rebalance_plan():
    tgt = pd.Series({"A": 0.5, "B": 0.5})
    px = pd.Series({"A": 100.0, "B": 50.0, "C": 10.0})
    plan, s = rebalance_plan(tgt, px, {"A": 10, "C": 100}, cash=0.0, threshold=0.0, cost_bps=0)
    assert s["portfolio value"] == 2000
    assert plan.loc["C", "trade shares"] == -100        # sell asset outside target
    assert plan.loc["B", "trade shares"] == 20           # buy to 50%
    assert plan.loc["A", "action"] == "HOLD"


def test_pipeline_offline():
    raw = synthetic_prices(["A", "B", "C", "SPY"], pd.bdate_range("2012-01-02", "2019-12-31"), seed=11)
    cfg = PortfolioConfig(tickers=["A", "B", "C"], start="2012-01-01", end="2019-12-31", rf=0.02,
                          method="black_litterman", views=opt.parse_views("A - B = 0.02 @ 0.5"),
                          backtest_methods=["hrp", "min_variance"], mc_paths=200, lookback=252)
    res = run_pipeline(cfg, raw_prices=raw)
    assert abs(res.allocation.weights.sum() - 1) < 1e-6
    assert {"black_litterman", "equal_weight", "hrp", "min_variance"} <= set(res.backtest_table.index)
    from portfolio.report import strategist_brief
    assert "Strategist brief" in strategist_brief(res)


def test_pipeline_oos_split_has_no_look_ahead():
    """With oos_start, the allocation ignores later data and the backtest is scored only from the split."""
    raw = synthetic_prices(["A", "B", "C", "SPY"], pd.bdate_range("2012-01-02", "2019-12-31"), seed=5)
    cfg = PortfolioConfig(tickers=["A", "B", "C"], start="2012-01-01", end="2019-12-31", rf=0.02,
                          method="min_variance", backtest_methods=["hrp"], mc_paths=100, lookback=252,
                          oos_start="2017-01-01")
    res = run_pipeline(cfg, raw_prices=raw)
    shocked = raw.copy()
    shocked.loc["2017-01-01":] *= np.linspace(1, 3, len(shocked.loc["2017-01-01":]))[:, None]
    res2 = run_pipeline(cfg, raw_prices=shocked)
    assert np.allclose(res.allocation.weights, res2.allocation.weights)
    assert res.backtests["hrp"].returns.index[0] >= pd.Timestamp("2017-01-01")


def test_parse_views():
    v = opt.parse_views("QQQ = 0.12 @ 0.6\nSPY - TLT = 0.03\nBRK-B = 0.08 @ 0.3")
    assert v[0].assets == {"QQQ": 1.0} and v[0].confidence == 0.6
    assert v[1].assets == {"SPY": 1.0, "TLT": -1.0} and v[1].confidence == 0.5
    assert v[2].assets == {"BRK-B": 1.0}


def test_snapshot_fallback_when_yahoo_fails(monkeypatch, tmp_path):
    """If Yahoo returns nothing for some tickers, they are filled from the bundled snapshot."""
    from portfolio import data
    snap = synthetic_prices(["AAA", "BBB", "^IRX"], pd.bdate_range("2015-01-01", "2016-12-30"), seed=5)
    path = tmp_path / "snap.csv.gz"
    snap.to_csv(path, compression="gzip")
    monkeypatch.setattr(data, "SNAPSHOT_PATH", path)
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path / "cache")

    def half_down(tickers, start, end):     # Yahoo works for AAA only
        out = data._empty(tickers).reindex(snap.index)
        out["AAA"] = snap["AAA"] * 1.01
        return out
    monkeypatch.setattr(data, "fetch_yahoo", half_down)
    px = data.download_prices(["AAA", "BBB"], "2015-01-01", "2016-12-31")
    assert px.attrs["from_snapshot"] == ["BBB"]
    np.testing.assert_allclose(px["BBB"].values, snap["BBB"].values, rtol=1e-12)
    np.testing.assert_allclose(px["AAA"].values, snap["AAA"].values * 1.01, rtol=1e-12)
    assert not (tmp_path / "cache").exists()          # partial downloads are not cached
    _, synth, notes = data.prepare_prices(px, ["AAA", "BBB"], "2015-01-01", "2016-12-31")
    assert synth == [] and any("snapshot" in n for n in notes)

    monkeypatch.setattr(data, "fetch_yahoo", lambda *a: pytest.fail("offline must not call Yahoo"))
    off = data.download_prices(["AAA", "BBB"], "2015-06-01", None, offline=True)
    assert off.index[0] >= pd.Timestamp("2015-06-01") and off.attrs["from_snapshot"] == ["AAA", "BBB"]


def test_non_positive_prices_removed():
    from portfolio.data import prepare_prices
    px = synthetic_prices(["X", "Y"], pd.bdate_range("2020-01-01", "2020-12-31"), seed=1)
    px.iloc[70, 0] = -37.6                                  # WTI, 20 Apr 2020
    clean, _, notes = prepare_prices(px, ["X", "Y"], "2020-01-01", "2020-12-31")
    assert (clean > 0).all().all() and any("Non-positive" in n for n in notes)


def test_holm_bonferroni():
    from portfolio.risk import holm_bonferroni
    p = pd.Series({"a": 0.01, "b": 0.04, "c": 0.03, "d": None})
    adj = holm_bonferroni(p)
    # sorted 0.01, 0.03, 0.04 -> 3*0.01, max(0.03, 2*0.03), max(0.06, 1*0.04)
    assert adj["a"] == pytest.approx(0.03) and adj["c"] == pytest.approx(0.06) and adj["b"] == pytest.approx(0.06)
    assert pd.isna(adj["d"])


def test_sharpe_ci_and_dsr():
    from portfolio.risk import deflated_sharpe_ratio, probabilistic_sharpe_ratio, sharpe_bootstrap_ci
    rng = np.random.default_rng(4)
    x = pd.Series(rng.normal(0.0004, 0.01, 3000))
    sr = x.mean() / x.std() * np.sqrt(252)
    lo, hi = sharpe_bootstrap_ci(x, 500)
    assert lo < sr < hi
    # more (and more dispersed) trials -> higher hurdle -> lower DSR
    assert deflated_sharpe_ratio(x, np.array([sr, 0.0, -0.3, 0.5, 0.2])) < probabilistic_sharpe_ratio(x)


def test_monte_carlo_matches_backtester():
    """Bootstrap MC with rebalance_every=1 and no costs is the constant-mix model w'r_t; with
    monthly rebalancing + costs it must equal a walk-forward replay of the same return draws."""
    r = to_returns(synthetic_prices(["X", "Y", "Z"], 300, seed=9))
    w = pd.Series([0.5, 0.3, 0.2], index=r.columns)
    daily = simulate_paths(r, w, horizon=40, n_paths=3, block=40, rebalance_every=1, cost_bps=0, seed=1)
    monthly = simulate_paths(r, w, horizon=40, n_paths=3, block=40, rebalance_every=10, cost_bps=25, seed=1)
    start = np.random.default_rng(1).integers(0, len(r), size=(3, 1))[0, 0]
    seq = r.iloc[(start + np.arange(40)) % len(r)].reset_index(drop=True)
    np.testing.assert_allclose(daily[0, 1:], np.cumprod(1 + seq.values @ w.values), rtol=1e-12)
    seq.index = pd.bdate_range("2020-01-01", periods=40)
    padded = pd.concat([seq.iloc[:1] * 0, seq])      # walk_forward needs >= 1 lookback row
    padded.index = pd.bdate_range("2019-12-31", periods=41)
    bt = walk_forward(padded, lambda win: w, lookback=1, rebalance_every=10, cost_bps=25)
    replay = (1 + bt.returns).cumprod().values / (1 - 25e-4)   # MC starts invested: no initial cost
    np.testing.assert_allclose(monthly[0, 1:], replay, rtol=1e-12)
