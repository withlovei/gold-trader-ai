# 1. Getting started

[Tiếng Việt](../vi/01-getting-started.md) · [Docs index](../README.md)

This guide takes you from a clean Windows machine to a running desk on a **demo account**.

> Do everything below on a **demo** account first. Only consider a live account after weeks of
> demo results you understand.

## 1.1 Prerequisites

| Item | Notes |
|---|---|
| Windows 10/11 | Required: the `MetaTrader5` package and the DPAPI secret store are Windows-only. |
| Python 3.13 | 3.11+ should work. Get it from python.org or `winget install Python.Python.3.13`. |
| MetaTrader 5 | Install your broker's terminal. Developed on **Exness** (Standard account, symbol `XAUUSDm`). |
| Hedging account | **Required.** Agents hold opposite positions at the same time; a netting account would merge them. Exness accounts are hedging. |
| Internet | The dashboard loads Tailwind, Lightweight Charts and Google Fonts from CDNs. |
| Claude CLI (optional) | For the daily meeting and Claude's second opinion. See §1.6. |
| Telegram bot (optional) | For order / close notifications. See §1.7. |

Algo trading must be allowed in MT5: **Tools → Options → Expert Advisors → Allow algorithmic
trading**, and the green "Algo Trading" button on the toolbar must be on.

## 1.2 Install

```powershell
git clone https://github.com/withlovei/gold-trader-ai.git
cd gold-trader-ai
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 1.3 Start

```powershell
scripts\start.bat
```

This starts `uvicorn services.api.main:app` on `127.0.0.1:8787` and opens the dashboard at
<http://127.0.0.1:8787/>. The server is local-only (it does not listen on your network).

Manual start, if you prefer:

```powershell
.venv\Scripts\python.exe -m uvicorn services.api.main:app --host 127.0.0.1 --port 8787
```

The first run creates the `data/` folder (SQLite database, runtime state). On a **fresh install the
mode is "Chỉ xem" (view-only): nothing is traded** until you change it in §1.5.

## 1.4 Connect MetaTrader 5

1. Open the MT5 terminal and log in to your **demo** account at least once.
2. In the dashboard open **Cài đặt** (Settings) → MetaTrader 5:
   - *Đường dẫn phần mềm* — path to `terminal64.exe` (default `C:\Program Files\MetaTrader 5\terminal64.exe`)
   - *Máy chủ* — broker server name exactly as MT5 shows it (e.g. `Exness-MT5Trial…`)
   - *Số tài khoản* — your account number
   - *Mật khẩu* — account password (encrypted with Windows DPAPI in `data/app.db`; it never
     appears in the repo or in logs)
   - *Mã giao dịch* — `XAUUSDm` (Exness Standard) or `XAUUSD`
3. Press connect. The top bar should show **MT5** green and live prices.

## 1.5 Set risk, review agents, choose the mode

1. **Rủi ro** (Risk) screen. Defaults are conservative (0.5% per trade, 2% daily loss, 10%
   drawdown, 2 positions). With 16 agents you will want a higher *max positions* and *max open
   risk*; with a small balance set *minimum lot cap* (`minLotPercent`) so 0.01 lot trades are
   not all blocked. See [04-risk-and-safety.md](04-risk-and-safety.md). **Start small.**
2. **Phòng giao dịch** → *Quản lý agent*. **By default every agent except the two flag agents is
   set to real money.** Most agents have little or negative tested edge. Move the ones you do not
   trust to *Nghiên cứu* (research = paper trades only). A cautious starting set is the agents
   with positive walk-forward: `trend-M15`, `pullback-M15`, `trend-M30`, `trend-H4`, `flag-M30`.
   See [03-agents-and-strategies.md](03-agents-and-strategies.md).
3. Sidebar **Chế độ** (mode):
   - *Chỉ xem* — analyse only, no orders (default on first run)
   - *Tín hiệu* — show signals
   - *Duyệt tay* — manual approval
   - *Tự động* — **the only mode that sends orders**; runs on the server even if the browser is
     closed.
4. Watch a few sessions in *Chỉ xem* first, then switch to *Tự động* on the demo account.

The **Dừng khẩn cấp** (emergency stop) button blocks all new entries immediately.

## 1.6 Claude CLI (optional)

Needed for the [daily meeting](05-daily-meeting.md) and the per-signal second opinion.

1. Install Claude Code (<https://claude.com/claude-code>) and log in once (`claude`).
2. GoldTrader finds the executable via: the `CLAUDE_CLI` environment variable → `PATH` → the newest
   `~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe`.
3. **Cài đặt → Claude** shows the detected path and has an on/off switch.

Usage counts against your Claude plan. If the CLI is missing or times out, trading simply
follows the fixed rules (no opinion is not a veto).

## 1.7 Telegram (optional)

1. In Telegram talk to **@BotFather**, `/newbot`, copy the bot token.
2. Send any message to your new bot (or add it to a group), then get your chat id
   (e.g. via `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. **Cài đặt → Telegram**: paste token and chat id, enable, press *Gửi tin thử*.

The token is stored encrypted. Messages are short: order opened (side, size, price, SL/TP, risk,
agent), order closed (result, R, reason), plus the daily meeting summary.

## 1.8 Optional: history and tests

```powershell
.venv\Scripts\python.exe scripts\fetch_history.py data\research XAUUSDm   # MT5 must be running
.venv\Scripts\python.exe tests\run_all.py data\research
```

See [07-backtest-and-research.md](07-backtest-and-research.md). The **Kiểm thử** screen runs
the backtester directly from the dashboard (it pulls history from MT5 itself).

## 1.9 Checklist before trusting it with real money

- [ ] At least several weeks on demo in *Tự động*, journal reviewed.
- [ ] You understand each real-money agent's tested edge and its worst drawdown.
- [ ] Risk per trade, daily loss and drawdown lock set to numbers you can live with.
- [ ] Hedging account, algo trading allowed, `XAUUSDm` volume rules understood (min 0.01 lot).
- [ ] Telegram on so you see every order.
- [ ] You know where the emergency stop is.

Problems? See [09-troubleshooting.md](09-troubleshooting.md).
