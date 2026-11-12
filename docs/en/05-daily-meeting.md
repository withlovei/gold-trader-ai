# 5. Daily meeting (the self-improving desk)

[Tiếng Việt](../vi/05-daily-meeting.md) · [Docs index](../README.md)

Once per trading day the head of desk calls the **Claude CLI** to review the desk, decide which
agents trade real money, and optionally have an agent's code improved. Implemented in
`services/api/meeting.py` (+ `restart.py`, `journal.manager_log`).

> This feature gives an AI **full authority** over which agents trade real money and permission to
> **edit your source code without a backtest gate**. Review the diary after each meeting. Turn it
> off if you do not want that (see §5.6).

## 5.1 Schedule

- **22:10 UTC, Monday–Friday** (5:10 am Vietnam time), right after gold's daily close.
- Started by the autopilot loop (`meeting.maybe_start`), once per UTC date (flag `meetingDate`).
- Manual: **Họp ngay** button (dashboard, office toolbar, or the head-of-desk desk) or
  `POST /api/meeting/run`.

## 5.2 What happens

1. **Gather**: for every agent — tested walk-forward numbers, manager score, real trade stats,
   paper (shadow) stats, trades of the last 26 hours, the account snapshot, last meeting summary.
2. **Decide** (Claude CLI, no tools, read-only prompt): returns JSON
   `{"summary", "decisions": [{id, real, reason}], "improve": [{id, goal}]}`. Every agent gets a
   decision; `real` flips are applied immediately (`set_agent_real`). No thresholds are enforced:
   the CLI decides.
3. **Improve** (up to 2 agents, `MAX_IMPROVE`): a second Claude CLI run with tools
   `Read, Edit, Write, Grep, Glob` and `--permission-mode acceptEdits` in the repository root edits
   the agent's source directly.
4. **Safety net** (kept even though there is no backtest gate):
   - the whole `services/` folder is copied to `data/backups/<timestamp>/` first;
   - after the edit a **smoke test** imports the app and evaluates the strategy catalogue on
     synthetic bars for M15/M30/H1/H4; if it fails the backup is restored;
   - the unified diff of every edited file is stored in the diary.
5. **Restart**: if code was applied, a detached helper (`python -m services.api.restart`) stops
   the server, starts it with the new code and waits for `/api/health`; if the new server does not
   answer within 60 s the code is restored from the backup and the server started again.
6. **Minutes**: saved to `data/meetings/<date>.json`, summarised to Telegram, appended to the diary.

An edit that runs but is a worse strategy is **not** detected automatically. Edited agents
should sit in research until their paper results prove them.

## 5.3 Diary

Every step is a row in `manager_log` tagged with the meeting id: meeting start/summary,
per-agent decision, desk change, improvement assignment, code change (with diff), rollback,
restart, and the head of desk's per-bar arbitration. The dashboard shows meetings as cards with
chips (⬆ real, ⬇ paper, 🛠 code, ↩ rollback) and a timeline per meeting; code rows expand into a
coloured diff. `GET /api/meetings` returns the grouped data, `GET /api/manager-log` the flat log.

While a meeting runs, **Họp ngay** opens a dialog with live progress (`GET /api/meeting` →
`status.events`), the decisions and the result.

## 5.4 Cost

Each meeting is one decision call (~$0.05–0.5, a few minutes) plus up to two edit runs (several
minutes and a few dollars of API-equivalent usage each). It counts against your Claude plan.

## 5.5 Restart warning

Never restart the server while a meeting is running: the meeting thread dies mid-edit. Check
`GET /api/meeting` → `status.running` first. If a meeting was cut off, the next autopilot pass
writes an "interrupted" line to the diary; inspect `git diff` and `data/backups/`.

## 5.6 Turning it off or limiting it

- Run the server with `GOLDTRADER_AUTOPILOT=0`: the background loop, and therefore the scheduled
  meeting, does not start (a manual *Họp ngay* still works; an open dashboard tab still runs the
  decision step, so use *Chỉ xem* mode to guarantee no orders), or
- remove the call to `meeting.maybe_start` in `live.run_autopilot`, or
- set `MAX_IMPROVE = 0` in `meeting.py` to keep the decisions but forbid code edits.

## 5.7 Reviewing and reverting a code change

```powershell
git diff                       # what changed in the working tree
git checkout -- services\api\methods\trend_reentry.py      # revert one file
```

or copy files back from `data\backups\<timestamp>\services\`.
