import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services.api.backtest import latest_backtest, run_backtest, run_compare
from services.api.chart_analysis import build_chart
from services.api.live import apply_default_risk, run_autopilot, set_mode, snapshot, unlock_drawdown
from services.api import meta_model
from services.api.journal import summary as journal_summary
from services.api.mt5_client import connect_account
from services.api.notify import read_telegram, save_telegram, send_test
from services.api.settings_store import read_risk, read_settings, save_risk
from services.api.trainer import latest_report, train_now

MOCKUP = Path(__file__).resolve().parents[2] / "mockup" / "index.html"

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # The autopilot makes trading decisions on its own thread, so trading no longer depends on a
    # dashboard tab being open. Set GOLDTRADER_AUTOPILOT=0 to run the server without it.
    stop = threading.Event()
    if os.environ.get("GOLDTRADER_AUTOPILOT", "1") != "0":
        threading.Thread(target=run_autopilot, args=(stop,), name="autopilot", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="AI Gold Trader", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Mt5ConnectRequest(BaseModel):
    terminalPath: str = Field(min_length=1)
    server: str = Field(min_length=1)
    login: str = Field(min_length=1)
    password: str = ""
    symbol: str = Field(min_length=1)


@app.get("/api/meeting")
def meeting_info() -> dict[str, object]:
    from services.api import meeting

    return {"ok": True, "status": meeting.status(), "history": meeting.history(10),
            "schedule": f"{meeting.MEETING_HOUR_UTC:02d}:{meeting.MEETING_MINUTE_UTC:02d} UTC (5:10 sáng giờ Việt Nam), thứ Hai – thứ Sáu"}


@app.post("/api/meeting/run")
def meeting_run() -> dict[str, object]:
    from services.api import meeting, live

    started = meeting.start(live._LAST_SNAPSHOT or None)
    return {"ok": started, "message": "Trưởng phòng bắt đầu họp." if started else "Đang họp rồi."}


@app.get("/api/meetings")
def meetings_grouped(limit: int = 20) -> dict[str, object]:
    from services.api import journal

    return {"ok": True, "meetings": journal.meetings_log(max(1, min(limit, 100)))}


@app.get("/api/manager-log")
def manager_diary(limit: int = 200, kind: str = "") -> dict[str, object]:
    from services.api import journal

    return {"ok": True, "items": journal.manager_log(max(1, min(limit, 1000)), kind)}


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(MOCKUP, headers={"Cache-Control": "no-store"})


class RiskRequest(BaseModel):
    perTradePercent: float
    dailyLossPercent: float
    drawdownPercent: float
    maxPositions: int
    maxLossStreak: int
    minRewardRatio: float
    minLotPercent: float | None = None
    maxOpenRiskPercent: float | None = None


class ModeRequest(BaseModel):
    mode: str = "full"
    emergency: bool | None = None


@app.get("/api/live")
def get_live() -> dict[str, object]:
    try:
        return snapshot()
    except (ValueError, RuntimeError, OSError) as error:
        return {"ok": False, "message": str(error)}


class AgentModeRequest(BaseModel):
    id: str
    real: bool


@app.post("/api/agents/mode")
def post_agent_mode(body: AgentModeRequest) -> dict[str, object]:
    from services.api.live import set_agent_real

    return set_agent_real(body.id, body.real)


@app.post("/api/mode")
def post_mode(body: ModeRequest) -> dict[str, object]:
    return set_mode(body.mode, body.emergency)


class TelegramRequest(BaseModel):
    enabled: bool = False
    chatId: str = ""
    token: str = ""


class LlmRequest(BaseModel):
    enabled: bool


@app.get("/api/settings/llm")
def get_llm_settings() -> dict[str, object]:
    from services.api import llm_judge

    return {"ok": True, "enabled": llm_judge.enabled(), "cli": llm_judge.find_cli() or ""}


@app.post("/api/settings/llm")
def post_llm_settings(body: LlmRequest) -> dict[str, object]:
    from services.api.settings_store import write_flag

    write_flag("llmJudge", "on" if body.enabled else "off")
    return get_llm_settings()


@app.get("/api/journal")
def get_journal() -> dict[str, object]:
    from services.api.shadow import summary as shadow_summary

    from services.api.journal import vetoes

    return {**journal_summary(), "shadow": shadow_summary(), "vetoes": vetoes()}


@app.get("/api/settings/telegram")
def get_telegram() -> dict[str, object]:
    return read_telegram()


@app.post("/api/settings/telegram")
def post_telegram(body: TelegramRequest) -> dict[str, object]:
    try:
        return save_telegram(body.enabled, body.chatId, body.token)
    except (ValueError, OSError) as error:
        return {"ok": False, "message": str(error)}


@app.post("/api/settings/telegram/test")
def post_telegram_test() -> dict[str, object]:
    return send_test()


class ModelModeRequest(BaseModel):
    mode: str


@app.get("/api/models/signal")
def get_signal_model() -> dict[str, object]:
    report = meta_model.latest()
    report.pop("params", None)
    mode = meta_model.read_mode()
    return {**report, "mode": mode, "modeLabel": meta_model.MODES[mode], "modes": meta_model.MODES}


@app.post("/api/models/signal/train")
def post_signal_train() -> dict[str, object]:
    try:
        report = meta_model.train()
    except (ValueError, RuntimeError, OSError) as error:
        return {"ok": False, "message": str(error)}
    report.pop("params", None)
    return report


@app.post("/api/settings/model")
def post_model_mode(body: ModelModeRequest) -> dict[str, object]:
    try:
        return meta_model.save_mode(body.mode)
    except ValueError as error:
        return {"ok": False, "message": str(error)}


@app.post("/api/risk/unlock")
def post_risk_unlock() -> dict[str, object]:
    return unlock_drawdown()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/chart")
def get_chart(timeframe: str = "M15") -> dict[str, object]:
    return build_chart(timeframe)


@app.get("/api/settings/risk")
def get_risk_settings() -> dict[str, float | int]:
    return read_risk()


@app.post("/api/settings/risk")
def post_risk_settings(body: RiskRequest) -> dict[str, float | int | bool]:
    saved = save_risk(body.model_dump())
    return {"ok": True, **saved}


@app.post("/api/settings/risk/default")
def post_risk_default() -> dict[str, object]:
    return apply_default_risk()


@app.get("/api/settings/mt5")
def get_mt5_settings() -> dict[str, str | bool]:
    return read_settings()


class BacktestRequest(BaseModel):
    strategy: str = "auto"
    timeframe: str = "M15"
    start: str
    end: str
    capital: float = 10000


@app.get("/api/backtest/latest")
def get_backtest() -> dict[str, object]:
    return latest_backtest()


@app.post("/api/backtest")
def post_backtest(body: BacktestRequest) -> dict[str, object]:
    try:
        return run_backtest(body.strategy, body.timeframe, body.start, body.end, body.capital)
    except (ValueError, RuntimeError, OSError) as error:
        return {"ok": False, "message": str(error)}


@app.post("/api/backtest/compare")
def post_backtest_compare(body: BacktestRequest) -> dict[str, object]:
    try:
        return run_compare(body.timeframe, body.start, body.end, body.capital)
    except (ValueError, RuntimeError, OSError) as error:
        return {"ok": False, "message": str(error)}


class TrainRequest(BaseModel):
    timeframe: str = "M15"
    bars: int = 5000


@app.get("/api/models/latest")
def get_latest_model() -> dict[str, object]:
    return latest_report()


@app.post("/api/models/train")
def post_train(body: TrainRequest) -> dict[str, object]:
    try:
        return train_now(body.timeframe, body.bars)
    except (ValueError, RuntimeError, OSError) as error:
        return {"ok": False, "message": str(error)}


@app.post("/api/mt5/connect")
def post_mt5_connect(body: Mt5ConnectRequest) -> dict[str, str | float | bool]:
    try:
        return connect_account(body.terminalPath, body.server, body.login, body.symbol, body.password)
    except (ValueError, RuntimeError, OSError) as error:
        return {"ok": False, "message": str(error)}
