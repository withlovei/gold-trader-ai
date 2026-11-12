# 2. Architecture

[Tiếng Việt](../vi/02-architecture.md) · [Docs index](../README.md)

A modular monolith: one Python process (FastAPI + a background autopilot thread), one SQLite
database, one single-page dashboard. No message bus, no microservices.

```
                 ┌──────────────────────── browser ───────────────────────┐
                 │  mockup/index.html  (dashboard, office canvas, dialogs) │
                 └───────────────▲──────────────────────────┬──────────────┘
                                 │ GET /api/live (2 s)       │ POST …
                      ┌──────────┴──────────────────────────▼──────────┐
                      │ services/api/main.py  (FastAPI, 127.0.0.1:8787) │
                      └──────────┬──────────────────────────────────────┘
          starts daemon thread   │
┌────────────────────────────────▼─────────────────────────────────────────┐
│ live.py  run_autopilot  → snapshot() every 5 s  (under _STATE_LOCK)       │
│   MT5 read ─► main book trend-M15 ─► _book_step for every EXTRA_BOOK      │
│   ─► head of desk: _manager_review / _coordinator_blocks / _risk_blocks   │
│   ─► _claude_gate (optional) ─► _send_order ─► journal ─► Telegram        │
│   meeting.maybe_start()  (22:10 UTC Mon–Fri)                               │
└───────┬─────────────┬──────────────┬─────────────┬──────────────┬────────┘
        │             │              │             │              │
  mt5_session    strategies +     shadow.py     journal.py    llm_judge.py
  (MetaTrader5)  methods/*       (paper trades) (SQLite)     (Claude CLI)
```

## 2.1 Decision timing

- The autopilot wakes **every 5 seconds** (`AUTOPILOT_SECONDS`) and runs `snapshot()`; it does not
  need a browser tab.
- Each agent ("book") decides **once per closed bar of its own timeframe** (M15, M30, H1, H4).
  Orders are only sent within `SEND_WINDOW_SECONDS` (120 s) after the bar closed, never late.
- Between bars, open positions are managed: time stop (`maxBars`), trailing stop for trail agents.
  Stop loss and take profit are always set on the broker side at entry.
- Weekend: the loop idles when the market is closed.

## 2.2 Books and agents

`live.all_books()` returns the main book (`trend-M15`) plus `EXTRA_BOOKS`. Each book has a
timeframe, bar seconds, a **magic number**, a strategy id and a display name. Real/research is a
flag `agentReal:<id>` (stored in `app_flags`, default real unless the book says
`"defaultReal": False`). See [03-agents-and-strategies.md](03-agents-and-strategies.md).

## 2.3 Head of desk (coordinator)

Implemented in `live.py`:

- `_manager_review` — once per newly closed bar, gathers every real agent signalling now and lets
  only the best ranked trade (score = tested edge shrunk toward real results). No simultaneous
  buy and sell. Different moments are not arbitrated.
- `_coordinator_blocks` — never open against another agent's *winning* position; total open risk
  cap (`maxOpenRiskPercent`).
- `_risk_blocks` — account gates: daily loss, drawdown lock, max positions, loss streak per
  agent, spread, unprotected positions.

## 2.4 Research (paper) agents

Agents with the real flag off never send entries. They still evaluate and record **shadow trades**
(`shadow.py`) closed with the same stop / target / time rules, so their results can be compared
to real ones. Shadow rows carry `frame_seconds`.

## 2.5 Backtester

`backtest.py::_simulate` replays history through the **same decision code path** as live
(strategy cards, gates, exits, risk limits, spread, swap, volume steps). Modes: `auto` (live
replica of the main selector), a single strategy id, and `agents` (multi-agent). Reports contain
metrics, per-agent stats and the trade list (`chartTrades`).

## 2.6 Data and state

| Where | What |
|---|---|
| `data/app.db` | settings, flags, risk, journal (`trade_journal`), shadow trades, LLM calls/vetoes, `manager_log` diary |
| `data/runtime.json` | live state: mode, emergency, drawdown lock, per-book last bar/decision, manager state |
| `data/candles/` | candle cache for the chart |
| `data/models/` | optional ML artefacts (signal model, LightGBM/XGBoost/HMM report) |
| `data/meetings/` | one JSON minutes file per meeting day |
| `data/backups/` | code backups taken before a meeting edit |

`data/` is git-ignored. `runtime.json` is written atomically (temp file + `fsync` + replace); an
unreadable file is quarantined as `runtime.corrupt-<ts>.json`.

## 2.7 Secrets

`secrets.py` wraps Windows DPAPI (`CryptProtectData`): the MT5 password and the Telegram token are
encrypted for the current Windows user and stored as blobs in `app.db`. They are never logged or
returned by the API.

## 2.8 Optional ML

`trainer.py` (LightGBM + XGBoost + GARCH + HMM) and `meta_model.py` (logistic signal scorer) are
optional. Research found no reliable edge from the direction models; the signal model is used in
`shadow` or `size` mode only to record or halve size, never to skip or enlarge trades.

## 2.9 Where to look

| I want to… | File |
|---|---|
| change when/how orders are sent | `services/api/live.py` (`_book_step`, `_send_order`) |
| add / tune an agent | `services/api/methods/`, `agents.py`, `EXTRA_BOOKS` in `live.py` |
| change risk rules | `live._risk_blocks`, `settings_store.py` |
| understand the backtest | `services/api/backtest.py` |
| change the UI | `mockup/index.html` |
