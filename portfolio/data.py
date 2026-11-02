"""Price data: Yahoo Finance download with an on-disk cache, a bundled snapshot and a synthetic fallback.

Source order for each ticker:
  1. today's cache (.cache/)            - avoids re-downloading within a day
  2. Yahoo Finance via yfinance         - fresh data
  3. bundled snapshot (data/)           - real prices saved by build_snapshot.py, used
                                          when Yahoo fails or ``offline=True``
  4. synthetic GBM (prepare_prices)     - last resort, flagged as demo only

All prices are dividend/split adjusted closes (``auto_adjust=True``), so simple
returns computed from them are total returns. Exception: continuous futures
(tickers ending in ``=F``) are front-month prices without roll adjustment.
"""
from __future__ import annotations

import hashlib
import zlib
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "prices_snapshot.csv.gz"


def _cache_path(tickers: list[str], start: str, end: str) -> Path:
    key = f"{','.join(sorted(tickers))}|{start}|{end}"
    return CACHE_DIR / f"prices_{hashlib.md5(key.encode()).hexdigest()[:12]}.csv"


def _empty(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(index=pd.DatetimeIndex([]), columns=tickers, dtype=float)


def fetch_yahoo(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Raw yfinance download of adjusted closes; empty frame on any failure."""
    try:
        import yfinance as yf
        raw = yf.download(tickers, start=start, end=end, auto_adjust=True,
                          progress=False, threads=True)
    except Exception:  # network down, rate limit, yfinance API change, ...
        return _empty(tickers)
    if raw is None or raw.empty:
        return _empty(tickers)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
    close = close.reindex(columns=tickers).astype(float)
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close


def load_snapshot(tickers: list[str] | None = None, start: str | None = None,
                  end: str | None = None) -> pd.DataFrame:
    """Prices from the bundled snapshot (empty frame if the file does not exist)."""
    if not SNAPSHOT_PATH.exists():
        return _empty(tickers or [])
    snap = pd.read_csv(SNAPSHOT_PATH, index_col=0, parse_dates=True)
    if tickers is not None:
        snap = snap.reindex(columns=tickers)
    return snap.loc[start:end]


def download_prices(tickers: list[str], start: str, end: str | None = None,
                    use_cache: bool = True, offline: bool = False) -> pd.DataFrame:
    """Adjusted close prices, one column per ticker (NaN where an asset has no data).

    Tickers that Yahoo does not return are filled from the bundled snapshot. The
    returned frame's ``attrs["from_snapshot"]`` lists those tickers, and
    ``attrs["snapshot_end"]`` gives the last date of the snapshot.
    """
    tickers = [t.strip().upper() for t in tickers if t.strip()]
    end = end or date.today().isoformat()
    if offline:
        close = load_snapshot(tickers, start, end)
        close.attrs["from_snapshot"] = [t for t in tickers if close[t].notna().any()]
        close.attrs["snapshot_end"] = str(close.index[-1].date()) if len(close) else None
        return close

    path = _cache_path(tickers, start, end)
    if use_cache and path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)

    close = fetch_yahoo(tickers, start, end)
    missing = [t for t in tickers if close[t].isna().all()]
    used: list[str] = []
    if missing:
        snap = load_snapshot(missing, start, end)
        used = [t for t in missing if snap[t].notna().any()]
        if used:
            close = close.reindex(close.index.union(snap.index))
            close[used] = snap[used]
            close.attrs["snapshot_end"] = str(snap.index[-1].date())
    close.attrs["from_snapshot"] = used

    if use_cache and not missing and not close.empty:   # only cache complete, fresh downloads
        CACHE_DIR.mkdir(exist_ok=True)
        close.to_csv(path)
    return close


def download_risk_free(start: str, end: str | None = None, offline: bool = False) -> pd.Series | None:
    """Daily annualised risk-free rate from the 13-week T-bill yield (^IRX), as a decimal."""
    irx = download_prices(["^IRX"], start, end, offline=offline)
    if irx.empty or irx["^IRX"].dropna().empty:
        return None
    return (irx["^IRX"].dropna() / 100.0).rename("rf")


def synthetic_prices(tickers: list[str], index: pd.DatetimeIndex | int = 2520,
                     seed: int | None = None, mu: float = 0.07, sigma: float = 0.20,
                     rho: float = 0.3) -> pd.DataFrame:
    """Correlated geometric Brownian motion prices (for demos/tests only).

    dS/S = mu dt + sigma dW, with constant pairwise correlation ``rho``.
    Per-asset drift and volatility are jittered deterministically from the ticker name.
    """
    if isinstance(index, int):
        index = pd.bdate_range("2010-01-01", periods=index)
    n, T = len(tickers), len(index)
    if seed is None:
        seed = zlib.crc32(",".join(tickers).encode())
    rng = np.random.default_rng(seed)
    mus = mu + rng.uniform(-0.04, 0.04, n)
    sigmas = sigma * rng.uniform(0.5, 1.5, n)
    corr = np.full((n, n), rho) + (1 - rho) * np.eye(n)
    L = np.linalg.cholesky(corr)
    dt = 1.0 / TRADING_DAYS
    z = rng.standard_normal((T - 1, n)) @ L.T
    log_ret = (mus - 0.5 * sigmas**2) * dt + sigmas * np.sqrt(dt) * z
    log_px = np.vstack([np.zeros(n), np.cumsum(log_ret, axis=0)])
    return pd.DataFrame(100.0 * np.exp(log_px), index=index, columns=tickers)


def prepare_prices(raw: pd.DataFrame, tickers: list[str], start: str, end: str | None = None,
                   allow_synthetic: bool = True, min_coverage: float = 0.5
                   ) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Slice to [start, end], replace unusable tickers, and align to a common calendar.

    Returns (prices, synthetic_tickers, notes). A ticker is unusable when it has
    data for less than ``min_coverage`` of the window. Short gaps (<=5 days) are
    forward filled; the window then starts at the first date all assets trade.
    """
    notes: list[str] = []
    snap = [t for t in raw.attrs.get("from_snapshot", []) if t in tickers]
    if snap:
        notes.append(f"Yahoo unavailable/offline for {', '.join(snap)}: using bundled snapshot "
                     f"(data ends {raw.attrs.get('snapshot_end')}).")
    px = raw.reindex(columns=tickers).loc[start:end] if not raw.empty else raw
    synthetic: list[str] = []
    nonpos = [t for t in px.columns if (px[t] <= 0).any()]
    if nonpos:   # e.g. WTI front-month futures settled at -$37 on 2020-04-20
        px = px.where(px > 0)
        notes.append(f"Non-positive prices in {', '.join(nonpos)} set to missing (returns undefined).")

    if px.empty:
        if not allow_synthetic:
            raise ValueError("No price data downloaded and synthetic fallback disabled.")
        index = pd.bdate_range(start, end or date.today().isoformat())
        notes.append("No market data available: ALL prices are synthetic GBM (demo only).")
        return synthetic_prices(tickers, index), list(tickers), notes

    coverage = px.notna().mean()
    bad = [t for t in tickers if coverage.get(t, 0.0) < min_coverage]
    if bad:
        if allow_synthetic:
            fake = synthetic_prices(bad, px.index)
            for t in bad:
                px[t] = fake[t]
            synthetic = bad
            notes.append(f"No/insufficient data for {', '.join(bad)}: replaced by synthetic GBM (demo only).")
        else:
            px = px.drop(columns=bad)
            notes.append(f"Dropped tickers without enough data: {', '.join(bad)}.")

    px = px.ffill(limit=5).dropna(how="any")
    if len(px) < 60:
        raise ValueError("Fewer than 60 common trading days; widen the date range or change tickers.")
    first_dates = raw.reindex(columns=[t for t in px.columns if t not in synthetic]).apply(
        lambda s: s.first_valid_index())
    if len(first_dates) and px.index[0] > pd.Timestamp(start) + pd.Timedelta(days=10):
        youngest = first_dates.idxmax()
        notes.append(f"Common history starts {px.index[0].date()} (limited by {youngest}).")
    return px, synthetic, notes


def to_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple (arithmetic) daily returns. Portfolio return = w' r holds exactly for these."""
    return prices.pct_change().iloc[1:]
