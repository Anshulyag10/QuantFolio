"""Download a fixed price dataset into data/ so the project runs without Yahoo Finance.

    python build_snapshot.py                 # default ~100 tickers, 2005 -> today
    python build_snapshot.py --add XOM CVX   # add tickers to the existing snapshot

Writes
    data/prices_snapshot.csv.gz   adjusted closes, one column per ticker
    data/snapshot_manifest.csv    ticker, category, first/last date, observations

Tickers that fail now but exist in an older snapshot are kept, so rebuilding never loses data.

Note on futures (=F): Yahoo gives the front-month contract with no roll adjustment, so
returns jump at each roll and ignore roll yield; WTI (CL=F) even went negative in Apr-2020.
For portfolio construction prefer the commodity ETFs, which are investable total-return series.
"""
from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

from portfolio.data import SNAPSHOT_PATH, fetch_yahoo, load_snapshot

UNIVERSE = {
    # --- commodity futures (continuous front month) ---
    "energy futures": ["CL=F", "BZ=F", "NG=F", "HO=F", "RB=F"],
    "metal futures": ["GC=F", "SI=F", "HG=F", "PL=F", "PA=F"],
    "grain futures": ["ZC=F", "ZW=F", "KE=F", "ZS=F", "ZM=F", "ZL=F", "ZO=F", "ZR=F"],
    "soft futures": ["KC=F", "CC=F", "SB=F", "CT=F", "OJ=F"],
    "livestock futures": ["LE=F", "GF=F", "HE=F"],
    # --- commodity ETFs / ETNs (investable) ---
    "broad commodity ETF": ["DBC", "GSG", "PDBC", "USCI", "COMT", "BCI", "FTGC", "DJP"],
    "energy ETF": ["USO", "BNO", "UNG", "UGA", "DBO", "DBE", "XLE", "XOP", "OIH", "URA"],
    "precious metal ETF": ["GLD", "IAU", "SLV", "PPLT", "PALL", "DBP", "GDX", "GDXJ", "SIL"],
    "industrial metal ETF": ["CPER", "DBB", "XME", "COPX", "LIT", "REMX", "PICK"],
    "agriculture ETF": ["DBA", "CORN", "WEAT", "SOYB", "CANE", "MOO", "WOOD", "VEGI"],
    # --- multi-asset core (default universe + benchmarks) ---
    "equity ETF": ["SPY", "QQQ", "IWM", "VTI", "EFA", "VEA", "EEM", "VWO"],
    "sector ETF": ["XLK", "XLF", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"],
    "bond ETF": ["TLT", "IEF", "SHY", "AGG", "LQD", "HYG", "TIP", "EMB"],
    "real estate ETF": ["VNQ"],
    "rates": ["^IRX"],
}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2005-01-01")
    p.add_argument("--add", nargs="*", default=[], help="extra tickers to include")
    a = p.parse_args()

    category = {t: c for c, ts in UNIVERSE.items() for t in ts}
    category.update({t.upper(): "user added" for t in a.add if t.upper() not in category})
    tickers = list(category)
    print(f"Downloading {len(tickers)} tickers from {a.start} ...")

    new = fetch_yahoo(tickers, a.start, date.today().isoformat())
    old = load_snapshot()
    snap = new.combine_first(old) if not old.empty else new      # keep old data for tickers that fail now
    snap = snap.dropna(axis=1, how="all").dropna(axis=0, how="all").sort_index()

    failed = [t for t in tickers if t not in snap.columns]
    kept_old = [t for t in tickers if t in snap.columns and new[t].isna().all()]

    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    snap.round(6).to_csv(SNAPSHOT_PATH, compression="gzip")
    manifest = pd.DataFrame({
        "category": [category.get(t, "other") for t in snap.columns],
        "first date": [snap[t].first_valid_index().date() for t in snap.columns],
        "last date": [snap[t].last_valid_index().date() for t in snap.columns],
        "observations": snap.notna().sum().values,
    }, index=pd.Index(snap.columns, name="ticker"))
    manifest.sort_values(["category", "ticker"]).to_csv(SNAPSHOT_PATH.parent / "snapshot_manifest.csv")

    size_mb = SNAPSHOT_PATH.stat().st_size / 1e6
    print(f"Saved {snap.shape[1]} tickers x {snap.shape[0]} days "
          f"({snap.index[0].date()} -> {snap.index[-1].date()}), {size_mb:.1f} MB -> {SNAPSHOT_PATH}")
    if kept_old:
        print(f"Yahoo failed, kept previous snapshot data for: {', '.join(kept_old)}")
    if failed:
        print(f"No data at all for: {', '.join(failed)}")


if __name__ == "__main__":
    main()
