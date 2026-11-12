# GoldTrader AI

**English** · [Tiếng Việt](README.vi.md)

A multi-agent automated trading desk for **gold (XAUUSD)** on **MetaTrader 5**. Sixteen
rule-based "agents" (each one a trading method with its own magic number, timeframe and
position) trade under a **head of desk** that arbitrates signals and enforces account-wide risk.
Once a day the head of desk calls the **Claude CLI** to review every agent, decide who trades real
money and who goes back to paper trading, and optionally improve an agent's source code.

> ⚠️ **Not financial advice. Trading leveraged products can lose more than you deposit.**
> This project is research software. Run it on a **demo account** first. Backtests do not
> guarantee future results; most agents in this repo have thin or negative tested edge (see
> [docs/en/03-agents-and-strategies.md](docs/en/03-agents-and-strategies.md)). You are
> responsible for anything it does with your money.

## Features

- **16 agents**, each with a distinct method (trend, pullback, breakout, reversal, range,
  re-entry, multi-timeframe, momentum, volatility expansion, false breakout, bull flag, …) and its
  own MT5 magic number, so every trade is attributable.
- **Real money / research switch per agent.** Research agents paper-trade only (shadow trades) so
  you can measure them without risk.
- **Head of desk (coordinator):** when several agents signal on the same bar, only the best-ranked
  one trades; no simultaneous buy and sell; shared risk limits (per-trade, daily loss, drawdown
  lock, total open risk, loss streak).
- **Daily meeting (22:10 UTC, Mon–Fri):** Claude CLI reviews every agent and decides real vs paper;
  can edit an agent's source code; code is backed up, smoke-tested and rolled back on failure.
  Every step is stored in a per-meeting diary.
- **Honest walk-forward backtester** (select 2022–2024, test 2025–2026) with spread, swap and
  broker-style volume rules; research scripts for new ideas.
- **Dashboard** (served locally): live office view with every desk, stars by profit, journal,
  charts, risk, backtest, models, settings.
- **Telegram notifications** (short messages for orders and closes) and an optional **Claude
  second opinion** on each signal.
- Secrets (MT5 password, Telegram token) are encrypted with Windows DPAPI and never leave the
  machine; the data folder is git-ignored.

## Requirements

- Windows 10/11 (the `MetaTrader5` Python package and DPAPI are Windows-only)
- Python 3.13 (3.11+ should work)
- MetaTrader 5 terminal installed and logged in to a broker account (developed on Exness
  Standard, symbol `XAUUSDm`)
- Optional: Claude CLI (for the daily meeting and second opinions), a Telegram bot

## Quick start

```powershell
git clone https://github.com/withlovei/gold-trader-ai.git
cd gold-trader-ai
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
scripts\start.bat          # starts the server and opens http://127.0.0.1:8787/
```

Then, in the dashboard: **Settings → MT5** (terminal path, server, login, password, symbol) →
**Risk** (use a small demo balance) → set the mode. Full guide:
[docs/en/01-getting-started.md](docs/en/01-getting-started.md).

## Documentation

| Topic | English | Tiếng Việt |
|---|---|---|
| Getting started | [01](docs/en/01-getting-started.md) | [01](docs/vi/01-getting-started.md) |
| Architecture | [02](docs/en/02-architecture.md) | [02](docs/vi/02-architecture.md) |
| Agents & strategies | [03](docs/en/03-agents-and-strategies.md) | [03](docs/vi/03-agents-and-strategies.md) |
| Risk & safety | [04](docs/en/04-risk-and-safety.md) | [04](docs/vi/04-risk-and-safety.md) |
| Daily meeting (self-improving desk) | [05](docs/en/05-daily-meeting.md) | [05](docs/vi/05-daily-meeting.md) |
| HTTP API | [06](docs/en/06-api.md) | [06](docs/vi/06-api.md) |
| Backtest & research | [07](docs/en/07-backtest-and-research.md) | [07](docs/vi/07-backtest-and-research.md) |
| Configuration & data | [08](docs/en/08-configuration.md) | [08](docs/vi/08-configuration.md) |
| Troubleshooting | [09](docs/en/09-troubleshooting.md) | [09](docs/vi/09-troubleshooting.md) |
| System requirements & status | [req](docs/en/req.md) | [req](docs/vi/req.md) |

Contributor / AI-assistant guide: [CLAUDE.md](CLAUDE.md).

## Project layout

```
services/api/        FastAPI app, live trading loop, agents, backtester, journal, meeting
services/api/methods/ research methods (one module per agent) + base framework
mockup/                index.html + css/ + js/ (dashboard; Vietnamese and English UI)
scripts/             start.bat / start.ps1, history download
tests/               regression tests (fake MetaTrader fed with real history)
docs/                documentation (en / vi)
data/                runtime data (git-ignored): app.db, candles, models, backups, meetings
```

## Disclaimer

Agent names (Raschke, Seykota, Connors, Darvas, …) are only labels borrowed from well-known
traders to describe each method's style. This project is **not affiliated with, endorsed by, or
derived from the work of** any of those people.

## License

[MIT](LICENSE). Research code, no warranty; see the disclaimer above.
