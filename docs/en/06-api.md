# 6. HTTP API

[Tiếng Việt](../vi/06-api.md) · [Docs index](../README.md)

FastAPI on `http://127.0.0.1:8787`. Local only; there is no authentication, so **do not expose the
port to a network**. Interactive docs: `/docs` (Swagger) while the server runs. All bodies are
JSON. Error responses use `{"detail": ...}` or `{"ok": false, "message": ...}`.

## Live

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/live` | Full snapshot: prices, account, decision, pipeline, agents (`agents.agents`, `agents.lab`), risk usage. Polled every 2 s by the UI. Also drives the autopilot when called. |
| POST | `/api/mode` | `{"mode": "analysis"\|"signal"\|"semi"\|"full", "emergency": bool?}` — only `full` sends orders |
| POST | `/api/agents/mode` | `{"id": "reversal-M15", "real": false}` — move an agent between real money and research |
| POST | `/api/risk/unlock` | Manually reopen the drawdown lock |
| GET | `/api/health` | Liveness check |
| GET | `/api/chart?timeframe=M15` | Candles, EMAs, Bollinger, levels, strategy card for the chart |
| GET | `/api/journal` | Trade journal + stats + Claude comparison table |

## Settings

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/settings/risk` | Read / save risk limits (see [04](04-risk-and-safety.md)) |
| POST | `/api/settings/risk/default` | Suggest and save risk from equity and ATR (falls back to test values if MT5 is unreachable) |
| GET | `/api/settings/mt5` | Saved MT5 settings (password never returned) |
| POST | `/api/mt5/connect` | `{"terminalPath","server","login","password","symbol"}` — connect and save |
| GET/POST | `/api/settings/telegram` | `{"enabled","chatId","token"}` |
| POST | `/api/settings/telegram/test` | Send a test message |
| GET/POST | `/api/settings/llm` | Claude second opinion on/off; reports the detected CLI path |

## Daily meeting & head of desk

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/meeting` | `{status: {running, step, startedAt, events[], result}, history[], schedule}` |
| POST | `/api/meeting/run` | Start a meeting now (`{"ok": false}` if one is running) |
| GET | `/api/meetings?limit=20` | Diary grouped by meeting with summaries and chips |
| GET | `/api/manager-log?limit=200&kind=` | Flat diary; `kind` ∈ meeting, decision, change, improve, code, rollback, restart, arbitration |

## Backtest & models

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/backtest` | `{"strategy":"auto"\|<id>, "timeframe","start","end","capital"}` |
| POST | `/api/backtest/compare` | Compare modes over a period |
| GET | `/api/backtest/latest` | Last saved report (`data/backtest-latest.json`) |
| GET | `/api/models/latest` | Last ML training report |
| POST | `/api/models/train` | `{"timeframe","bars"}` train the LightGBM/XGBoost/HMM ensemble (needs MT5) |
| GET | `/api/models/signal` | Signal (meta) model report and mode |
| POST | `/api/models/signal/train` | Train the signal model |
| POST | `/api/settings/model` | `{"mode": "off"\|"shadow"\|"size"}` |

## Static

`GET /` serves `mockup/index.html`.

## Example

```powershell
curl http://127.0.0.1:8787/api/health
curl -X POST http://127.0.0.1:8787/api/agents/mode -H "Content-Type: application/json" -d "{\"id\":\"flag-M30\",\"real\":true}"
curl -X POST http://127.0.0.1:8787/api/mode -H "Content-Type: application/json" -d "{\"mode\":\"analysis\"}"
```

> CORS only allows `http://127.0.0.1:8765` / `localhost:8765` as extra origins; the dashboard is
> served from the same origin on 8787.
