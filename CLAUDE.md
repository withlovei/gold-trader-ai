# CLAUDE.md

Guidance for Claude Code (and other AI assistants / contributors) working in this repository.

## What this project is

GoldTrader AI: a multi-agent automated trading desk for XAUUSD on MetaTrader 5 (Windows only).
16 rule-based agents trade under a head of desk (coordinator). A daily meeting calls the Claude CLI
to decide who trades real money and to improve agent code. The single-page dashboard lives in
`mockup/` (index.html + `css/` + `js/`; UI in Vietnamese and English). Full docs: `docs/en/` and `docs/vi/`. Start with
`docs/en/02-architecture.md`.

## Commands

```powershell
# environment (Python 3.13, Windows)
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# run the server + dashboard (http://127.0.0.1:8787/)
scripts\start.bat
# or: .venv\Scripts\python.exe -m uvicorn services.api.main:app --host 127.0.0.1 --port 8787

# server without the background loop / daily meeting (an open dashboard tab still polls
# /api/live, which can trade in "Tự động" mode; use "Chỉ xem" to be sure nothing is sent)
$env:GOLDTRADER_AUTOPILOT = "0"

# download history for tests/backtests (MetaTrader terminal must be running and logged in)
.venv\Scripts\python.exe scripts\fetch_history.py data\research XAUUSDm

# tests (each prints a final "... PASSED"/"OK" line; the folder holds hist/<TF>.json)
.venv\Scripts\python.exe tests\run_all.py data\research
.venv\Scripts\python.exe tests\test_switch.py data\research     # a single test
```

There is no linter config; follow the style of the surrounding code (type hints, small
functions, Vietnamese user-facing strings, English identifiers and comments).

## Architecture in one screen

- `services/api/main.py` — FastAPI routes; starts `live.run_autopilot` on a daemon thread.
- `services/api/live.py` — the trading loop. `snapshot()` (every 5 s, under `_STATE_LOCK`) reads
  MT5, runs the main book (`trend-M15`) and every book in `EXTRA_BOOKS` via `_book_step`, the
  coordinator (`_manager_review`, `_coordinator_blocks`), risk gates, stars, and builds the payload
  of `GET /api/live`. State in `data/runtime.json` (atomic write + fsync).
- `services/api/agents.py` — agent identities (alias, persona, rules text, `TESTED` numbers).
- `services/api/strategies.py` — the two core strategies (trend, pullback) + gate lists
  (`TREND_GATES`, `PULLBACK_GATES`) + `evaluate_strategies` (catalog of cards).
- `services/api/methods/` — one module per research method (`Method` base in `base.py`;
  `_template.py` shows how to add one; register in `__init__.py`, add `TESTED` numbers).
- `services/api/backtest.py` — live-replica simulator (`_simulate`), modes `auto`, one strategy,
  and `agents`.
- `services/api/shadow.py` — paper ("shadow") trades for research agents; rows carry
  `frame_seconds` so each only advances on its own bar size.
- `services/api/journal.py` — SQLite journal (`trade_journal`, `llm_calls`, `llm_vetoes`,
  `manager_log`), agent stats, head-of-desk diary grouped by meeting.
- `services/api/meeting.py` + `restart.py` — daily meeting, Claude-CLI code edits, backup /
  smoke test / rollback, detached restart helper.
- `services/api/llm_judge.py` — Claude CLI wrapper (second opinion; `decide()` = vào/giảm/bỏ).
- `services/api/notify.py` — Telegram (short order/close messages).
- `services/api/settings_store.py`, `secrets.py` — SQLite settings; MT5 password and Telegram
  token encrypted with Windows DPAPI.
- `mockup/index.html` — page markup only; `mockup/css/app.css`; `mockup/js/NN-*.js` are plain scripts loaded in order
  (shared global scope; `11-office.js` holds the `OfficeGame` IIFE). `js/i18n.js` + `js/i18n-en.js`: UI source text is
  Vietnamese, English comes from a phrase dictionary applied to the DOM (`?lang=en`, header selector); canvas text uses `t()`.

## Rules that matter

1. **Never commit anything under `data/`, `.env*`, `*.db`, logs, or credentials.** The repo is
   public. Do not print or read secret values (MT5 password, Telegram token, `app.db` blobs).
2. **Commit small and often.** The daily meeting may edit agent source files in place (it backs
   them up to `data/backups/`, which is git-ignored), so review `git diff` after a meeting and
   commit or revert deliberately.
3. **Do not restart the server while a meeting is running.** Check `GET /api/meeting` →
   `status.running` first; a restart kills the meeting thread mid-edit.
4. **Risk is independent of AI.** Anything from Claude CLI / ML may only reduce or skip; it can
   never override risk gates, enlarge size, or bypass the coordinator.
5. **No look-ahead.** Strategies use closed bars only. Backtests must stay walk-forward (select on
   2022–2024, test on 2025–2026) and include spread and swap. A method passes only when both
   periods are ≥ +0.05R per trade and profit factor ≥ 1.10 (`methods.verdict`).
6. **Magic numbers are identities** (260611–260626). Do not reuse or renumber; journal, stats
   and the broker's history depend on them.
7. **One position per agent**; the book stores `maxBars` / `manage` from the card it sent on.
8. Research agents (`agentReal:<id>` flag off) must never call `order_send` for new entries;
   already-open real positions are still managed to the end.
9. User-facing text is Vietnamese; keep it that way unless adding i18n deliberately.
10. When you change live behaviour, add or update a test in `tests/` and run the whole suite.

## Testing notes

Tests drive `live._book_step`, `_manager_review`, the meeting, etc. with a fake MetaTrader object
fed with real saved candles (`<dir>/hist/M15.json`, `M30.json`, `H1.json`, `H4.json`, `M5.json`),
temporary SQLite files, and stubbed Claude / Telegram (`_llm.decide`, `notify.send`). They never
touch your real `data/`. `tests/test_meeting.py` temporarily edits and restores
`services/api/methods/false_breakout.py`; run it on a clean checkout.

## Typical tasks

- **Add an agent:** copy `methods/_template.py`, register in `methods/__init__.py`, add a book to
  `EXTRA_BOOKS` in `live.py` with a new magic, add identity/persona in `agents.py`, run the
  walk-forward (`docs/en/07-backtest-and-research.md`), store results in `methods.TESTED`.
- **Change a risk rule:** `live._risk_blocks` / `_coordinator_blocks`, mirror it in
  `backtest._simulate` when it affects results, extend tests.
- **UI change:** edit `mockup/index.html` / `mockup/js/*.js`; add English phrases for new Vietnamese text to `js/i18n-en.js`; keep confirmations in the `<dialog>` helpers
  (`confirmDialog` / `noticeDialog`) — no `alert()` / `confirm()`.
