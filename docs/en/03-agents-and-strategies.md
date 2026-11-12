# 3. Agents & strategies

[Tiếng Việt](../vi/03-agents-and-strategies.md) · [Docs index](../README.md)

> Agent names are labels borrowed from well-known traders to describe a method's style. No
> affiliation or endorsement is implied.

## 3.1 The agents

Each agent is one strategy on one timeframe with its **own MT5 magic number** and at most **one
open position**. The coordinator is the head of desk (alias "Paul Tudor Jones").

| Agent id | Alias | TF | Magic | Method (short) | Default |
|---|---|---|---|---|---|
| `trend-M15` | Linda Raschke | M15 | 260611 | Trend pullback to EMA 20, volatility-expanding, trailing stop | real |
| `trend-M30` | Ed Seykota | M30 | 260612 | Same trend method on M30, TP 2R, 48 bars | real |
| `pullback-M15` | Larry Connors | M15 | 260613 | RSI(2) dip in a long trend, TP 1.5R, 24 bars | real |
| `breakout-M15` | Nicolas Darvas | M15 | 260614 | Range breakout | real |
| `reversal-M15` | Richard Wyckoff | M15 | 260615 | Liquidity-sweep reversal | real |
| `range-M15` | John Bollinger | M15 | 260616 | Range / Bollinger mean reversion | real |
| `reentry-M15` | Jesse Livermore | M15 | 260617 | Second entry on the same trend leg | real |
| `mtf-M15` | Alexander Elder | M15 | 260618 | Multi-timeframe trend alignment | real |
| `brkconfirm-M15` | William O'Neil | M15 | 260619 | Confirmed breakout | real |
| `retest-M15` | Al Brooks | M15 | 260620 | Breakout then retest | real |
| `momentum-M15` | Richard Dennis | M15 | 260621 | Momentum breakout, trailing | real |
| `volexp-M15` | Toby Crabel | M15 | 260622 | Volatility expansion | real |
| `fakeout-M15` | Larry Williams | M15 | 260623 | False-breakout fade | real |
| `trend-H4` | John W. Henry | H4 | 260624 | Trend on H4, TP 2R, 48 bars | real |
| `flag-M30` | Dan Zanger | M30 | 260625 | Bull flag (buy only) | **research** |
| `flag-H1` | Thomas Bulkowski | H1 | 260626 | Bull flag (buy only) | **research** |

"Default" is what a fresh install uses. The daily meeting and you can change it at any time.

## 3.2 Real money vs research

- **Real**: the agent sends orders with its magic number.
- **Research (paper)**: no new orders; the signal is recorded as a shadow trade and followed to
  its stop/target/time stop. Open real positions of an agent moved to research are still
  managed until they close.
- Switch in the dashboard (*Quản lý agent*, or click a desk in the office view) or with
  `POST /api/agents/mode {"id": "...", "real": true|false}`.

## 3.3 Honest tested edge

Walk-forward on saved M15 history, $10k, spread 0.2 (select 2022–2024 / test 2025–2026), average R
per trade. A method clears the bar only if **both** periods are ≥ +0.05R and PF ≥ 1.10.

| Agent | 2022–24 | 2025–26 | Verdict |
|---|---|---|---|
| trend-M15 / pullback-M15 / trend-M30 | full-history 2022–26: +0.152R / +0.188R / +0.122R per trade; positive most years (2022 weak, trend-M30 −4R) | | the core |
| trend-H4 | +0.131R | +0.262R | passes on few trades (36 / 32) |
| flag-M30 | +0.335R PF 1.75 | +0.288R PF 1.60 | passes |
| flag-H1 | +0.099R PF 1.19 | +0.081R PF 1.16 | passes (thin) |
| reentry | +0.006R | +0.094R | fails 2022–24 |
| brkconfirm | −0.029R | +0.091R | fails 2022–24 |
| momentum / retest | −0.09R / −0.04R | +0.02R / +0.01R | fail |
| mtf, volexp, fakeout | negative | negative | fail |
| breakout / reversal / range | little or no edge (reversal ≈ 0.006R; range has too few trades) | | unproven |

Findings behind the numbers: fading and range strategies lose on gold; only trend pullback with a
volatility filter has a robust edge; candlestick patterns (all 61 TA-Lib patterns) have none;
bull flags on M30/H1 are robust but buy-only in a bull market (drift caveat). **Do not enable
failing agents on real money** unless you accept paying for the experiment.

## 3.4 The core strategy (trend)

Gates, in order (shown as green/red chips in the dashboard): EMA 20/50/200 aligned in one
direction · ADX ≥ 15 · higher timeframe agrees · volatility expanding (ATR14 ≥ ATR100) · one of
the last three bars touched EMA 20 · the last three closes held EMA 50 · a confirmation bar closes
in the trend direction beyond the previous bar's high/low · signal-bar body ≤ 1 ATR (M15) · stop
≤ 3 ATR · fill hour outside 18–24 UTC. Stop beyond the pullback. M15: no fixed take profit, a
trailing stop (3 ATR) once profit reaches 1R; M30/H4: TP 2R and a 48-bar time stop. The exact
gate list for every strategy is in `services/api/strategies.py` and `methods/*.py`.

## 3.5 Stars

Every desk shows stars from the **net profit of closed real trades**: profitable agents 3–5 (best
= 5), losing/flat 1–2, no closed trade 0. Stars rank evidence, not quality: a few trades prove
little.

## 3.6 Head-of-desk arbitration

When several real agents signal on the **same bar**, the coordinator ranks them by score =
(40 × tested edge + sum of real R) / (40 + closed real trades) and lets only the best open. It
never opens a buy and a sell on the same bar and never opens against another agent's winning
position. Signals at different moments are all allowed, so each agent's record shows whether its
own signals are right. Decisions are written to the diary (`arbitration`).

## 3.7 Adding an agent

1. Copy `services/api/methods/_template.py`, implement gates, `scan`, stop/target (see
   `methods/base.py`, `bull_flag.py` for a full example).
2. Register it in `methods/__init__.py`.
3. Add a book to `EXTRA_BOOKS` in `live.py` with a **new magic** and a name; add identity text in
   `agents.py`.
4. Run the walk-forward ([07](07-backtest-and-research.md)), store results in `methods.TESTED`.
5. Leave it in research (`"defaultReal": False`) until it earns real money.
6. Add a test under `tests/`.
