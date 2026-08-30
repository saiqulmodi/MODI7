"""One-off CLI runner for a full MODI1 universe scan -- saves results to CSV."""

import sys
import time
import pandas as pd
from fundamentals import get_bulk_fundamentals
from universe import MODI1_INTRADAY_SYMBOLS


def _progress(completed, total):
    if completed % 25 == 0 or completed == total:
        print(f"  {completed}/{total} fetched...", flush=True)


if __name__ == "__main__":
    start = time.time()
    print(f"Scanning {len(MODI1_INTRADAY_SYMBOLS)} symbols...")
    results = get_bulk_fundamentals(MODI1_INTRADAY_SYMBOLS, progress_callback=_progress)
    elapsed = time.time() - start

    df = pd.DataFrame(results)
    ok = df[df["error"].isna()]
    failed = df[df["error"].notna()]

    df.to_csv("universe_scan_full.csv", index=False)
    print(f"\nDone in {elapsed:.0f}s. {len(ok)} ok, {len(failed)} failed.")
    print(f"Saved to universe_scan_full.csv")
    print("\nFailed symbols:")
    for _, row in failed.iterrows():
        print(f"  {row['symbol']}: {row['error']}")
