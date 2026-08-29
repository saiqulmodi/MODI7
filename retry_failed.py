"""
Retries just the rate-limited symbols from the last full universe scan,
sequentially with a delay between requests instead of 8-way concurrency --
the full scan showed Yahoo starts throttling ("Too Many Requests") after a
few hundred sustained concurrent requests, clustered near the end of the run.
"""

import time
import pandas as pd
from fundamentals import get_fundamentals

DELAY_SECONDS = 2.0

RATE_LIMITED_SYMBOLS = [
    "PRICOLLTD", "ESCORTS", "SIRCA", "GOODLUCK", "STYLAMIND", "EPACKPEB",
    "MASTEK", "CYIENT", "FINCABLES", "SGMART", "MPSLTD", "VIMTALABS",
    "PAYTM", "ROSSARI", "TATVA", "ADANIPOWER", "GROWW", "SAPPHIRE",
    "GREENPLY", "SAKAR", "GESHIP", "CESC", "PNBGILTS", "BHARATRAS",
    "VENUSPIPES", "EMSLIMITED", "GLAXO", "KKCL", "HDBFS", "BAJAJHFL",
    "BAJAJCON", "GRANULES", "HESTERBIO", "OFSS", "MPHASIS", "PARKHOSPS",
    "SHARDAMOTR", "ERIS", "POLICYBZR", "INDIASHLTR", "SHAILY", "BECTORFOOD",
    "REDTAPE", "TCPLPACK", "SURYAROSNI", "TBZ", "KSOLVES",
]

if __name__ == "__main__":
    print(f"Retrying {len(RATE_LIMITED_SYMBOLS)} rate-limited symbols, {DELAY_SECONDS}s apart...")
    retried = []
    for i, symbol in enumerate(RATE_LIMITED_SYMBOLS, 1):
        result = get_fundamentals(symbol)
        status = "OK" if not result.get("error") else f"FAILED ({result['error']})"
        print(f"  [{i}/{len(RATE_LIMITED_SYMBOLS)}] {symbol}: {status}")
        retried.append(result)
        if i < len(RATE_LIMITED_SYMBOLS):
            time.sleep(DELAY_SECONDS)

    retried_df = pd.DataFrame(retried)
    still_failed = retried_df[retried_df["error"].notna()]
    now_ok = retried_df[retried_df["error"].isna()]
    print(f"\nRetry done: {len(now_ok)} recovered, {len(still_failed)} still failing.")

    full_df = pd.read_csv("universe_scan_full.csv")
    full_df = full_df.set_index("symbol")
    retried_df = retried_df.set_index("symbol")
    full_df.update(retried_df)
    full_df = full_df.reset_index()
    full_df.to_csv("universe_scan_full.csv", index=False)
    print("Merged into universe_scan_full.csv")

    if not still_failed.empty:
        print("\nStill failing:")
        for _, row in still_failed.iterrows():
            print(f"  {row['symbol']}: {row['error']}")
