# System requirements & implementation status

[Tiếng Việt](../vi/req.md) · [Docs index](../README.md)

This document replaces the original blueprint (which described a Tauri/React desktop app,
OpenRouter LLMs and an event bus). It states what the system **is today** and what it needs, and
lists the original ideas that were **not** built. Last reviewed: 2026-11-12.

## 1. Product

An automated gold (XAUUSD) trading desk on MetaTrader 5: 16 rule-based agents, a head of desk
that arbitrates and enforces risk, a daily Claude-CLI meeting that reallocates real vs paper
trading and can edit agent code, a backtester that replays the live code path, and a local
single-page dashboard. Demo-first research software, not a product with performance claims.

## 2. Runtime requirements

| Requirement | Value |
|---|---|
| OS | Windows 10/11 (MetaTrader5 package, Windows DPAPI) |
| Python | 3.13 (3.11+ expected to work) |
| Packages | `requirements.txt`: fastapi, uvicorn, pydantic, MetaTrader5, numpy, scipy, scikit-learn, lightgbm, xgboost, hmmlearn |
| Broker / terminal | MetaTrader 5, **hedging** account; developed on Exness Standard, `XAUUSDm` |
| Network | Local only (127.0.0.1:8787). Internet for MT5, CDNs used by the page, Telegram, Claude |
| Optional | Claude CLI (`claude.exe`) for the meeting and second opinions; Telegram bot |
| Hardware | Any modern PC; the loop is light (history of ~600 bars per timeframe per 5 s pass). Backtests of 4 years of M15 use a few hundred MB RAM |

## 3. Architecture (as built)

| Layer | Technology | Where |
|---|---|---|
| UI | Single HTML page, Tailwind (CDN), Lightweight Charts 4.1.3, a canvas "office" | `mockup/index.html` |
| Backend | Python, FastAPI, Pydantic, one background autopilot thread | `services/api/` |
| Broker | `MetaTrader5` Python package, one session at a time | `mt5_session.py`, `mt5_client.py` |
| Storage | SQLite (`data/app.db`) + JSON state (`data/runtime.json`) | `settings_store.py`, `journal.py`, `shadow.py` |
| Secrets | Windows DPAPI | `secrets.py` |
| AI | Claude CLI (`claude -p`, JSON output) for the gate and meeting; optional LightGBM/XGBoost/GARCH/HMM and a logistic signal model | `llm_judge.py`, `meeting.py`, `trainer.py`, `meta_model.py` |
| Notifications | Telegram Bot API | `notify.py` |

A modular monolith; no message bus, no microservices, no WebSocket (the UI polls `/api/live`).

## 4. Functional requirements and status

Legend: ✅ implemented · 🟡 partial · ❌ not built

### MT5 connector
| Requirement | Status |
|---|---|
| Connect, account balance/equity/margin, bid/ask, OHLC, symbol specs (tick size/value, volume min/max/step), spread | ✅ |
| Open positions, deal history, market BUY/SELL with SL/TP, modify SL (trailing), close | ✅ |
| Order duplicate prevention, broker-confirmed result, fill/slippage in journal | ✅ |
| Pending orders, partial close | ❌ |
| Automatic reconnect | 🟡 (each pass reopens the session; errors are retried next pass) |

### Market data & analysis
| Requirement | Status |
|---|---|
| Timeframes M1…D1 for chart; M5–H4 for decisions | ✅ |
| EMA 9/20/50/200, RSI, ATR, ADX, Bollinger, support/resistance, swings, ATR zig-zag | ✅ |
| MACD, Stochastic, VWAP, pivots, FVG, order blocks, candlestick library | ❌ (candlestick patterns were evaluated offline and rejected) |
| Market regime (HMM) | 🟡 optional, trained on demand, not used to gate trades |

### Strategies / agents
| Requirement | Status |
|---|---|
| Trend, pullback | ✅ live-validated core |
| Breakout, reversal, range, re-entry, multi-timeframe, confirmed breakout, retest, momentum, volatility expansion, false breakout, bull flag | ✅ implemented; most unproven (see [03](03-agents-and-strategies.md)) |
| Strategy selector by regime | ❌ replaced by one agent per strategy + head of desk |
| Per-agent magic number, one position per agent, real/research switch, paper (shadow) trading | ✅ |

### Decision, risk, execution
| Requirement | Status |
|---|---|
| Head of desk: one trade per bar among competing agents, no simultaneous buy/sell, open-risk cap | ✅ |
| Risk per trade, daily loss, drawdown lock, max positions, loss streak per agent, spread filter, minimum-lot rule, emergency stop | ✅ |
| Weekly loss limit, session restrictions other than the 18–24 UTC fill gate | ❌ |
| Trailing stop (chandelier), time stop, broker-side SL/TP | ✅ |
| Weighted scoring engine (trend/AI/LLM weights) | ❌ (removed: it was cosmetic) |
| Explicit order state machine | ❌ (positions are reconciled with MT5 each pass) |
| News / economic calendar blackout | ❌ (tested offline: no benefit) |

### AI
| Requirement | Status |
|---|---|
| Local ML models (LightGBM, XGBoost, GARCH, HMM) | 🟡 optional; no reliable edge found; not used to open trades |
| Signal meta-model | 🟡 `shadow` (record) or `size` (halve) only |
| LLM validation | ✅ via **Claude CLI** (not OpenRouter): `vào` / `giảm` / `bỏ`, journalled, never enlarges |
| OpenRouter, provider-independent LLM layer, prompt versioning, token cost tracking | ❌ (cost reported by the CLI is stored per call) |
| Daily meeting: Claude CLI decides real vs paper and edits agent code | ✅ |

### Backtesting
| Requirement | Status |
|---|---|
| Live-replica OHLC backtest with spread, swap, commission, volume rules, per-agent stats | ✅ |
| Walk-forward (select 2022–24, test 2025–26), per-year, spread stress | ✅ (scripts / recipe in [07](07-backtest-and-research.md)) |
| Tick-level backtest, Monte Carlo UI, parameter optimizer | ❌ |

### Dashboard
| Requirement | Status |
|---|---|
| Trading overview, live office view, agent cards, journal, charts, risk, backtest, models, settings | ✅ |
| Real/research switch, meeting dialog, per-meeting diary, stars | ✅ |
| Tauri desktop shell, React/TypeScript | ❌ (plain HTML page) |
| i18n | ✅ UI in Vietnamese and English (header selector, `?lang=en`); docs in both. Text generated by the backend or Claude is translated only where a known phrase matches |

### Operations
| Requirement | Status |
|---|---|
| Atomic, fsynced state file; corrupt-state quarantine | ✅ |
| Structured logging, error monitoring, health endpoint | 🟡 (`/api/health`, Python logging) |
| Database migrations framework | ❌ (columns added with `ALTER TABLE … IF missing`) |
| Tests | ✅ 11 regression scripts in `tests/` (fake MT5 + real history) |

## 5. Non-functional requirements

- **Safety first:** risk gates independent of AI; broker-side SL on every entry.
- **Auditability:** every real order is journalled with plan, fill, slippage, spread, agent, exit
  reason and Claude verdict; head-of-desk diary per meeting.
- **Security:** secrets DPAPI-encrypted; server bound to localhost; no auth (do not expose).
- **Performance:** decisions are per closed bar; the 5-second loop only reads and checks.
- **Maintainability:** type hints, one module per method, tests, CLAUDE.md for AI assistants.

## 6. Data (SQLite tables, as built)

`mt5_settings`, `telegram_settings`, `risk_settings`, `model_settings`, `app_flags`,
`trade_journal`, `shadow_trades`, `llm_calls`, `llm_vetoes`, `manager_log` (+ candle/chart caches
as JSON). The original 20-table design was not adopted.

## 7. Known limitations

- Windows only; one MT5 terminal; XAUUSD-focused (symbol is configurable, strategies are tuned on gold).
- Thin edge, regime dependent; 2022–2026 was a gold bull market (buy-only bull-flag drift caveat).
- The daily meeting can change code without a backtest gate; a worse edit is not detected
  automatically.
- No authentication on the local API.

## 8. Original blueprint ideas not built

Tauri/React desktop app · OpenRouter and prompt management · event-driven bus with event payload
schemas · weighted decision scoring · economic-calendar module · order state machine · pending
orders / partial close · tick-level backtests · model-deployment approval workflow · 20-table
schema. They are kept out on purpose to stay a small, testable monolith; contributions welcome.
