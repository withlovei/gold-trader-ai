# 9. Troubleshooting

[Tiếng Việt](../vi/09-troubleshooting.md) · [Docs index](../README.md)

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard shows no prices, "Mất kết nối" | Server not running | Run `scripts\start.bat`; check `http://127.0.0.1:8787/api/health` |
| `Chưa đọc được giá thời gian thực` / MT5 error | MT5 terminal closed, not logged in, wrong path, symbol not in Market Watch | Open MT5, log in, put `XAUUSDm` in Market Watch, re-check path/server/login in Cài đặt |
| `ModuleNotFoundError: MetaTrader5` | Wrong Python / not Windows / venv not used | Use `.venv\Scripts\python.exe -m pip install -r requirements.txt`; Windows only |
| Orders rejected (retcode 10027) | Algo trading disabled | MT5 toolbar **Algo Trading** on; Tools → Options → Expert Advisors |
| Orders rejected "invalid stops/volume" | Symbol limits differ from Exness defaults | Check min lot/step; raise balance or `minLotPercent` |
| Nothing is ever traded | Mode is *Chỉ xem* (default on first run), emergency stop, drawdown lock, or all agents in research | Check sidebar mode, the pipeline/blocks line on each agent, `Rủi ro` screen |
| Agents say `đủ N vị thế` | `maxPositions` reached | Raise `maxPositions` (and `maxOpenRiskPercent`) knowingly |
| Trades blocked "chênh lệch quá rộng" | Spread > 0.8 | Wait; typical at rollover/news |
| Many `Biến động mở rộng` (ATR14 ≥ ATR100) fails | Volatility filter by design | Normal: ~⅓ of days have no trend signal; do not loosen it (it is the edge) |
| `runtime.json unreadable` in log | File cut by power loss | Handled: moved to `runtime.corrupt-<ts>.json`, mode reset to Tự động; re-check mode and locks |
| Telegram test fails | Wrong token/chat id; bot not started | Message the bot first; verify chat id via `getUpdates`; check `Cài đặt → Telegram` status text |
| Claude opinion always "không có ý kiến" | CLI not found / not logged in / timeout | Set `CLAUDE_CLI`, run `claude` once to log in; **Cài đặt → Claude** shows the path |
| Meeting did not run | Weekend, before 22:10 UTC, server off, `GOLDTRADER_AUTOPILOT=0`, already ran today | Press **Họp ngay** or check `GET /api/meeting` |
| Meeting "bị gián đoạn" | Server restarted during the meeting | Check `git diff` and `data/backups/`, re-run the meeting |
| Code edited by the meeting broke something | CLI edit ran but is wrong | `git diff`, revert the file (see [05](05-daily-meeting.md) §5.7), keep the agent in research |
| Dashboard looks unstyled | CDNs blocked (Tailwind, charts, fonts) | Allow `cdn.tailwindcss.com`, `unpkg.com`, `fonts.googleapis.com` |
| Tests fail with missing `hist/M15.json` | No history downloaded | `scripts\fetch_history.py <dir>`, then `tests\run_all.py <dir>` |
| `test_meeting` leaves a changed file | Test crashed mid-run | `git checkout -- services/api/methods/false_breakout.py` |

## Logs

The server prints to its console. When started by the restart helper, output goes to
`data/uvicorn.log` and `data/uvicorn.err`. The head-of-desk diary (`/api/manager-log`) shows
meeting and arbitration events. The trade journal (`/api/journal`) shows every real order with
slippage, spread, exit reason and, if enabled, Claude's verdict.

## Getting help

Open an issue at <https://github.com/withlovei/gold-trader-ai/issues> with: Windows and Python
versions, what you did, the error text, and **no** passwords, tokens, account numbers or
screenshots that show them.
