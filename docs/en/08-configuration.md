# 8. Configuration & data

[Tiếng Việt](../vi/08-configuration.md) · [Docs index](../README.md)

## 8.1 Where configuration lives

Almost everything is configured in the dashboard and stored in SQLite (`data/app.db`). The only
environment variables are optional (see `.env.example`; GoldTrader does not read a `.env` file
by itself — set variables in your shell or launcher).

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDE_CLI` | (auto) | Full path to `claude.exe`; otherwise `PATH`, then the newest VS Code extension copy |
| `GOLDTRADER_AUTOPILOT` | `1` | `0` = no background loop / no scheduled meeting |

## 8.2 Dashboard settings

| Screen | What | Stored |
|---|---|---|
| Cài đặt → MetaTrader 5 | terminal path, server, login, symbol, password | `mt5_settings` (password DPAPI-encrypted) |
| Cài đặt → Claude | on/off for per-signal Claude opinion | flag `llmJudge` |
| Cài đặt → Telegram | enabled, chat id, bot token | `telegram_settings` (token DPAPI-encrypted) |
| Rủi ro | per-trade, daily loss, drawdown, positions, streak, reward ratio, min-lot cap, open risk cap | `risk_settings` |
| Mô hình | signal-model mode and training | `model_settings`, `data/models/` |
| Sidebar mode | `analysis` / `signal` / `semi` / `full`, emergency stop | `data/runtime.json` |
| Quản lý agent | real vs research per agent | flags `agentReal:<id>` |

## 8.3 Flags (`app_flags` table)

| Flag | Meaning |
|---|---|
| `agentReal:<id>` | `on`/`off`; absent = the book's default (`defaultReal`, else real) |
| `llmJudge` | `on`/`off` Claude per-signal gate |
| `meetingDate` | last UTC date a scheduled meeting started |
| `meetingRunning` | set while a meeting runs (detects interrupted meetings) |

## 8.4 Constants in code you might tune

| Constant | File | Meaning |
|---|---|---|
| `LIVE_TIMEFRAME`, `DECISION_SECONDS` | `live.py` | main book timeframe (M15) |
| `AUTOPILOT_SECONDS` (5) | `live.py` | background loop period |
| `SEND_WINDOW_SECONDS` (120) | `live.py` | max age of a closed bar for sending an order |
| `EXTRA_BOOKS` | `live.py` | the agents (timeframe, magic, strategy, name, `defaultReal`) |
| `MANAGER_PRIOR_TRADES`, `MANAGER_EDGE` | `live.py` | head-of-desk ranking |
| `BLOCK_HOURS` (18–23 UTC) | `strategies.py` | no fills in these hours |
| `MEETING_HOUR_UTC/MINUTE_UTC`, `MAX_IMPROVE` | `meeting.py` | meeting schedule and edit budget |
| `TESTED` | `methods/__init__.py`, `agents.py` | stored walk-forward numbers |

## 8.5 The `data/` folder (git-ignored)

```
data/app.db              settings, flags, risk, journal, shadow trades, diary
data/runtime.json        live state (mode, locks, per-book last decision)
data/candles/<SYMBOL>/   chart candle cache
data/models/             optional ML models
data/meetings/           meeting minutes (JSON per day)
data/backups/<ts>/       code backups taken before meeting edits
data/backtest-latest.json
data/uvicorn.log|err     server logs if started by the restart helper
```

**Backing up:** copy the `data/` folder while the server is stopped. **Moving to another PC:**
the stored MT5 password and Telegram token cannot be moved — DPAPI blobs are tied to the Windows
user and machine — so re-enter them in the dashboard on the new machine.

**Starting fresh:** stop the server and delete `data/` (you lose the journal and settings).

## 8.6 Never commit

`data/`, `.env*`, any `*.db`, logs, screenshots with account numbers. `.gitignore` already covers
them; run `git status` before every push.
