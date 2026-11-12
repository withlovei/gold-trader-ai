# 4. Risk & safety

[Tiếng Việt](../vi/04-risk-and-safety.md) · [Docs index](../README.md)

Risk rules live in code (`live._risk_blocks`, `_coordinator_blocks`, `_drawdown_gate`) and are
**independent of any AI**: Claude or ML can only reduce a trade or skip it; nothing can override a
gate or make a trade bigger than the rules allow.

## 4.1 Settings (Rủi ro screen / `POST /api/settings/risk`)

| Setting | Key | Default | Meaning |
|---|---|---|---|
| Risk per trade | `perTradePercent` | 0.5 % | % of equity lost if the stop is hit; sizes the lot from the actual stop distance, tick size and tick value |
| Daily loss limit | `dailyLossPercent` | 2 % | no new entries after the day's loss reaches it |
| Drawdown limit | `drawdownPercent` | 10 % | new entries locked when equity falls this far below the peak |
| Max positions | `maxPositions` | 2 (1–20) | open positions across all agents |
| Max loss streak | `maxLossStreak` | 3 | per agent: after this many consecutive losses the agent rests the rest of the day |
| Min reward ratio | `minRewardRatio` | 1.5 | minimum take-profit / stop distance for fixed-target plans |
| Min lot cap | `minLotPercent` | 0 | if the computed lot is below the broker minimum, send the minimum lot **only if** its risk ≤ this % (lets small accounts trade) |
| Max open risk | `maxOpenRiskPercent` | 6 % | summed risk of all open agent positions |

The defaults are for a single agent. A desk of many agents needs larger `maxPositions` and
`maxOpenRiskPercent` (the author runs 0.75 % per trade, 2.5 % daily loss, 30 % drawdown lock,
14 positions, 30 % open risk on a small demo account). Choose your own numbers; larger exposure
means larger drawdowns.

## 4.2 Gates applied before every entry

1. Mode is *Tự động* and the emergency stop is off.
2. Agent is real; it has no open position; its loss streak is below the limit.
3. Daily loss, drawdown lock, max positions, max open risk, spread (≤ 0.8 price units), and no
   position without a stop.
4. Signal is fresh: bar closed ≤ 120 s ago (no late entries).
5. Coordinator: not against another agent's winning position; one trade per bar among competing
   agents.
6. Lot size: from risk, stop distance and the symbol's real tick value/volume step; the minimum-lot
   rule above.
7. Optional Claude gate: `vào` (full), `giảm` (half), `bỏ` (skip). No answer ⇒ follow the rules.

## 4.3 Drawdown lock

When equity falls `drawdownPercent` below the peak, new entries lock. The lock opens by itself
**once** after a cooldown with the peak reset to current equity; a second lock needs a manual
unlock (`POST /api/risk/unlock` or the dashboard button). Open positions keep their stops.

## 4.4 Safety behaviour

- **Broker-side SL/TP** on every entry; the time stop and trailing stop are extras.
- **Duplicate prevention:** per-bar `lastSentBar`, persisted *before* anything else can resend.
- **One position per agent**, identified by its magic number.
- **Hedging account required**; agents may hold opposite positions at the same time (a losing
  one is never closed because another agent flipped).
- **Restart safe:** state is on disk; the autopilot resumes at the next bar; corrupt state is
  quarantined.
- **MT5 down:** the loop logs the error and retries; it never assumes an order succeeded without
  the broker's confirmation.
- **Claude / Telegram down:** trading continues by the fixed rules.
- **Emergency stop:** blocks all new entries instantly (existing positions keep their stops).

## 4.5 What the system does NOT protect you from

- A broker that widens spreads or re-quotes; gaps over stops (slippage is recorded in the journal).
- Strategy decay: edges are thin and regime dependent.
- Your own settings: oversized risk will blow an account.
- The daily meeting can change code (see [05](05-daily-meeting.md)); review its diary.

## 4.6 Practical advice

- Demo first, for weeks. Keep risk per trade small (≤ 1 %).
- Prefer agents that passed both walk-forward periods; keep failing agents in research.
- Do not edit `data/runtime.json` by hand while the server runs.
- Treat any backtest number as an upper bound.
