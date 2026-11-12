# 7. Backtest & research

[Tiếng Việt](../vi/07-backtest-and-research.md) · [Docs index](../README.md)

## 7.1 Backtest from the dashboard

**Kiểm thử** screen: choose strategy (`auto` = live replica of the main selector, a single
strategy/agent, or multi-agent mode), timeframe, dates and starting capital, and run. The server
pulls history from your MT5 terminal (or the local candle archive) and replays it through the same
code path as live trading:

- decisions only on closed bars, fills at the next open, **spread** on entry, **swap** at rollover
  (21:00), commission, volume min/step, `minLotPercent`;
- all the live gates: hour gate (18–24 UTC), daily loss, drawdown lock, per-agent loss streak,
  risk limits, exits (stop, target, time stop, trailing);
- a candlestick chart with trade markers and a replay; metrics (net, PF, win rate, max drawdown,
  Sharpe, expectancy, R, streaks); per-agent breakdown.

The report is saved to `data/backtest-latest.json`. The trade list in the report is truncated; the
full list is `chartTrades`.

## 7.2 The honest test (walk-forward)

- **Select** parameters / pick the method on 2022-09 … 2024-12, **test** on 2025-01 … 2026-11.
- Spread 0.2 price units, $10,000, a 2× spread stress, and per-year results.
- A method qualifies for real money only if **both** periods are ≥ +0.05R per trade with PF ≥
  1.10 (`methods.verdict`), and then only with your approval.
- Beware: M15 history from MT5 is capped at ~99,000 bars (≈ 4 years); M5 ≈ 1.5 years.
- Past results never guarantee future results. Edges here are thin (+0.1R per trade) and regime
  dependent.

## 7.3 Saved history for scripts and tests

```powershell
.venv\Scripts\python.exe scripts\fetch_history.py data\research XAUUSDm
```

writes `data/research/hist/{M5,M15,M30,H1,H4}.json` (rows `[time, o, h, l, c, spread]`). Then:

```powershell
.venv\Scripts\python.exe tests\run_all.py data\research
```

## 7.4 Evaluating a new method (recipe)

```python
import json, sys
from datetime import timezone
sys.path.insert(0, ".")
from services.api import backtest as b
from services.api.settings_store import read_risk

rows = json.load(open("data/research/hist/M30.json"))
market = {"spread": 0.2, "tickSize": 0.001, "tickValue": 0.1, "volumeMin": 0.01, "volumeMax": 200.0,
          "volumeStep": 0.01, "swapLong": -493.4, "swapShort": 0.0, "swapMode": 1, "point": 0.001}
limits = dict(read_risk()); limits.update({"drawdownPercent": 100.0, "dailyLossPercent": 100.0, "maxLossStreak": 1000})
sd, ed = b._parse_day("2025-01-01"), b._parse_day("2026-11-06")
lo = int(b._warmup(sd, "M30").replace(tzinfo=timezone.utc).timestamp())
hi = int(ed.replace(tzinfo=timezone.utc).timestamp()) + 86400
sel = [r for r in rows if lo <= r[0] < hi]
report = b._simulate([tuple(map(float, r[1:5])) for r in sel], [int(r[0]) for r in sel],
                     market, "flag", "M30", sd, ed, 10000.0, limits)
trades = report["chartTrades"]          # full list; each has "r", "openedTs", "agent", ...
```

Run it for both periods, compare average R and profit factor, check per-year results and a 2×
spread run, and keep the numbers in `methods.TESTED` (`"flag-H1"` style keys when the same method
is measured on another timeframe).

## 7.5 What research found (summary)

- Fading / range strategies lose on gold across 2022–2026; trend pullback with a volatility
  filter (ATR14 ≥ ATR100) and no fills 18–24 UTC is the one robust edge.
- A chandelier trailing stop (3 ATR after 1R) roughly doubled M15 trend's R per trade.
- Meta-model sizing, news blackout, ADX / efficiency filters, limit entries, breakeven moves,
  "follow recent performance" allocation: none improved walk-forward results.
- Candlestick patterns (all 61 TA-Lib) have no stable edge; chart patterns: only bull flags on
  M30/H1 held up (buy-only, drift caveat).
- Running many correlated agents mostly adds leverage on the same move; raising per-trade risk on
  one selector beat several multi-agent variants at equal drawdown. The multi-agent desk is a
  research and monitoring platform, not a proven improvement.
- Replaying every agent's backtest trades on M5 and cancelling early on 5-minute checks did **not**
  beat the current exits.

## 7.6 Optional ML

`POST /api/models/train` (or the **Mô hình** screen) fits LightGBM, XGBoost, GARCH and an HMM
regime filter on recent bars. The signal (meta) model scores trend signals; modes `off`,
`shadow` (record only, recommended) and `size` (halve size on low scores; never skip or enlarge).
Models are written to `data/models/` and are not part of the repository.
