"""Download saved candle history from your MetaTrader 5 terminal for tests and backtests.

usage: python scripts/fetch_history.py <output dir> [symbol]

Writes <output dir>/hist/<TF>.json for M5, M15, M30, H1, H4 as rows
[time, open, high, low, close, spread]. MetaTrader returns at most ~99,000 bars per request, so M15
covers roughly 4 years and M5 about 1.5 years. The terminal must be running and logged in, and the
MT5 settings saved in the dashboard (Settings -> MT5) are used to connect.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MetaTrader5 as mt5  # noqa: E402

from services.api.mt5_session import open_terminal  # noqa: E402

FRAMES = ("M5", "M15", "M30", "H1", "H4")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1]) / "hist"
    out.mkdir(parents=True, exist_ok=True)
    symbol = sys.argv[2] if len(sys.argv) > 2 else "XAUUSDm"
    with open_terminal() as terminal:
        info = terminal.symbol_info(symbol)
        if info is None:
            print("Symbol not found:", symbol)
            return 1
        print("server:", terminal.account_info().server, "| spread points:", info.spread)
        for name in FRAMES:
            rates = terminal.copy_rates_from_pos(symbol, getattr(mt5, "TIMEFRAME_" + name), 1, 99000)
            if rates is None:
                print(name, "no data:", terminal.last_error())
                continue
            rows = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), int(r["spread"])] for r in rates]
            (out / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
            first = datetime.fromtimestamp(rows[0][0], timezone.utc).date()
            last = datetime.fromtimestamp(rows[-1][0], timezone.utc).date()
            print(f"{name}: {len(rows)} bars {first} .. {last}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
