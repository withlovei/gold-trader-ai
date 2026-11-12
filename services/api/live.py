import json
import logging
import math
import os
import copy
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.api import journal, meta_model, notify, shadow
from services.api.mt5_session import open_terminal
from services.api.settings_store import read_risk, read_settings, save_risk
from services.api.strategies import DRAWDOWN_COOLDOWN_SECONDS

RUNTIME_PATH = Path(__file__).resolve().parents[2] / "data" / "runtime.json"
# The user trades M15 (decision every 15 minutes, ~0.8 trades a day; chosen 2026-11-07).
# Walk-forward 2022-2026 on M15: +0.054R a trade, PF 1.09, max drawdown ~30R; M30 earns about
# twice as much per trade with half the drawdown but trades only ~0.45 times a day.
LIVE_TIMEFRAME = "M15"
DECISION_SECONDS = 15 * 60
# Breakout is paper-tracked on M30, where its backtest yardstick was measured.
SHADOW_TIMEFRAME = "M30"
SHADOW_SECONDS = 30 * 60
LIVE_BARS = 600
MAGIC = 260611
# Extra books {timeframe: {"seconds", "magic", "factor", "strategies"}}: same trend rules on another
# timeframe with its own position. M30 trend (TP 2R / 48 bars, the configuration selected on data
# before 2025) at half risk next to the M15 book (enabled 2026-11-08, user approved): 2022-24
# +61.6R -> +75.7R with drawdown 16.4R -> 17.3R, 2025-26 +98.3R -> +113.3R (19.7R); monthly R
# correlation with M15 0.34. Only the trend strategy was validated on M30.
#
# 2026-11-09 multi-agent (user's choice, variant E of the agent study): every validated strategy
# is its own agent with its own magic and position; the main book above is the trend-M15 agent.
# The coordinator lets agents stack in the same direction, opens against another agent only while
# that agent's position is losing, and caps the total open risk (maxOpenRiskPercent).
AGENT_MODE = True
EXTRA_BOOKS: dict[str, dict[str, object]] = {
    "pullback-M15": {"timeframe": "M15", "seconds": 15 * 60, "magic": 260613, "factor": 1.0, "strategies": ("pullback",), "name": "Larry Connors (Hồi giá M15)"},
    "trend-M30": {"timeframe": "M30", "seconds": 30 * 60, "magic": 260612, "factor": 1.0, "strategies": ("trend",), "name": "Ed Seykota (Theo xu hướng M30)"},
}
# 2026-11-10: every agent has its own book and a switch on the dashboard: real money ("thật") or
# research (paper trades only). The switch is stored as flag "agentReal:<id>" (settings_store).
# The user put ALL agents on real money, against my advice: in the 2022-24 walk-forward 8 of them
# lose steadily (together about -360R). Same risk per trade as the core agents.
_MORE_BOOKS = (
    ("breakout-M15", "breakout", 260614, "Nicolas Darvas (Phá vùng M15)"),
    ("reversal-M15", "reversal", 260615, "Richard Wyckoff (Đảo chiều M15)"),
    ("range-M15", "range", 260616, "John Bollinger (Đi ngang M15)"),
    ("reentry-M15", "reentry", 260617, "Jesse Livermore (Vào lại theo xu hướng M15)"),
    ("mtf-M15", "mtf", 260618, "Alexander Elder (Xu hướng đa khung M15)"),
    ("brkconfirm-M15", "brkconfirm", 260619, "William O'Neil (Phá vùng có xác nhận M15)"),
    ("retest-M15", "retest", 260620, "Al Brooks (Phá vùng rồi kiểm tra lại M15)"),
    ("momentum-M15", "momentum", 260621, "Richard Dennis (Phá vùng động lượng M15)"),
    ("volexp-M15", "volexp", 260622, "Toby Crabel (Bùng nổ biến động M15)"),
    ("fakeout-M15", "fakeout", 260623, "Larry Williams (Phá vỡ thất bại M15)"),
)
for _key, _strategy, _magic, _name in _MORE_BOOKS:
    EXTRA_BOOKS[_key] = {"timeframe": "M15", "seconds": 15 * 60, "magic": _magic, "factor": 1.0, "strategies": (_strategy,), "name": _name}
# Trend on H4: the only new candidate that passed both periods (2022-24 +0.131R PF 1.21, 2025-26
# +0.262R PF 1.45), but on 36 + 32 trades only. TP 2R / 48 H4 bars.
EXTRA_BOOKS["trend-H4"] = {"timeframe": "H4", "seconds": 4 * 3600, "magic": 260624, "factor": 1.0, "strategies": ("trend",), "name": "John W. Henry (Theo xu hướng H4)"}
# Bull flag (chart pattern, 2026-11-10): passed the split test on M30 and H1, buy side only. New
# agents start in research (paper) until the user moves them to real money on the dashboard.
EXTRA_BOOKS["flag-M30"] = {"timeframe": "M30", "seconds": 30 * 60, "magic": 260625, "factor": 1.0, "strategies": ("flag",), "name": "Dan Zanger (Cờ tăng M30)", "defaultReal": False}
EXTRA_BOOKS["flag-H1"] = {"timeframe": "H1", "seconds": 3600, "magic": 260626, "factor": 1.0, "strategies": ("flag",), "name": "Thomas Bulkowski (Cờ tăng H1)", "defaultReal": False}
MAIN_BOOK = {"timeframe": LIVE_TIMEFRAME, "seconds": DECISION_SECONDS, "magic": MAGIC, "factor": 1.0, "strategies": ("trend",), "name": "Linda Raschke (Theo xu hướng M15)"}


def all_books() -> dict[str, dict[str, object]]:
    """Every agent the bot runs, the main trend-M15 book first."""
    return {"trend-M15": MAIN_BOOK, **EXTRA_BOOKS}


def agent_real(key: str) -> bool:
    """Real money (True) or research / paper only (False). Default: the book's "defaultReal" (real
    when not given)."""
    from services.api.settings_store import read_flag

    default = "on" if all_books().get(key, {}).get("defaultReal", True) else "off"
    try:
        return read_flag("agentReal:" + key, default) != "off"
    except OSError:
        return True


def set_agent_real(key: str, real: bool) -> dict[str, object]:
    from services.api.settings_store import write_flag

    if key not in all_books():
        return {"ok": False, "message": f"Không có agent {key}."}
    with _STATE_LOCK:
        write_flag("agentReal:" + key, "on" if real else "off")
    return {"ok": True, "id": key, "real": real}


RESEARCH_NOTE = "đang ở phòng nghiên cứu, chỉ ghi lệnh giấy"
AGENT_MAGICS = {MAGIC, *(int(config["magic"]) for config in EXTRA_BOOKS.values())}  # noqa: E305
LIVE_MARK = "Lệnh thật theo chiến lược đã kiểm thử"
VN_TZ = timezone(timedelta(hours=7))
# An order is only sent this many seconds after the signal bar closed. The backtest fills at
# the open of the next bar; a signal picked up later would trade a different price.
SEND_WINDOW_SECONDS = 120
AUTOPILOT_SECONDS = 5
# Every read-modify-write of runtime.json and every trading decision runs under this lock, so
# two callers (the autopilot thread, the dashboard, a mode change) can never send the same
# order twice or overwrite each other's state (for example an emergency stop).
_STATE_LOCK = threading.RLock()
_LOG = logging.getLogger("goldtrader.autopilot")
_AUTOPILOT = {"lastRun": 0.0, "lastError": ""}


def _frame(mt5: object) -> int:
    return int(getattr(mt5, "TIMEFRAME_" + LIVE_TIMEFRAME))


_LAST_SNAPSHOT: dict[str, object] = {}


def snapshot() -> dict[str, object]:
    with _STATE_LOCK:
        result = _snapshot()
    _LAST_SNAPSHOT.clear()
    _LAST_SNAPSHOT.update({name: result.get(name) for name in ("balance", "equity", "dailyProfit", "drawdown", "positions")})
    return result


def run_autopilot(stop: threading.Event) -> None:
    """Background loop started with the server: decisions no longer depend on a browser tab
    being open and polling /api/live."""
    last_reminder_check = 0.0
    while not stop.is_set():
        delay = AUTOPILOT_SECONDS
        if time.time() - last_reminder_check >= 3600:
            last_reminder_check = time.time()
            _remind_retraining()
        try:
            result = snapshot()
            _AUTOPILOT["lastError"] = ""
            try:
                from services.api import meeting

                meeting.maybe_start(result)  # daily head of desk meeting, on its own thread
            except Exception as error:  # noqa: BLE001
                _LOG.warning("meeting: %s", error)
        except Exception as error:  # keep the loop alive whatever MetaTrader does
            _AUTOPILOT["lastError"] = str(error)
            _LOG.warning("autopilot: %s", error)
            delay = 30
        _AUTOPILOT["lastRun"] = time.time()
        stop.wait(delay)


def unlock_drawdown() -> dict[str, object]:
    """Manual confirmation after a drawdown stop: restart the peak from current equity."""
    with _STATE_LOCK:
        state = _read_state()
        state["drawdownLock"] = None
        state["peakEquity"] = None
        state["autoUnlocks"] = 0
        _write_state(state)
    return {"ok": True, "message": "Đã mở khóa sụt giảm. Đỉnh vốn tính lại từ vốn hiện tại."}


def _drawdown_gate(state: dict[str, object], equity: float, limits: dict[str, float | int]) -> str:
    """Keep the peak in state. Reaching the drawdown limit locks new entries. The lock opens
    by itself once, after DRAWDOWN_COOLDOWN_SECONDS, with the peak reset to equity; a second
    lock waits for a manual unlock. Returns a note when the lock was opened automatically."""
    peak = max(float(state.get("peakEquity") or equity), equity)
    limit = float(limits["drawdownPercent"]) / 100
    lock = state.get("drawdownLock") if isinstance(state.get("drawdownLock"), dict) else None
    now = int(time.time())
    note = ""
    if lock is None and peak > 0 and (peak - equity) / peak >= limit:
        lock = {"since": now, "peak": round(peak, 2), "equity": round(equity, 2)}
        state["drawdownLock"] = lock
    if lock is not None and int(state.get("autoUnlocks") or 0) == 0 and now - int(lock["since"]) >= DRAWDOWN_COOLDOWN_SECONDS:
        state["drawdownLock"] = None
        state["autoUnlocks"] = 1
        peak = equity
        note = "Khóa sụt giảm đã hết thời gian nghỉ và tự mở một lần; đỉnh vốn tính lại từ vốn hiện tại."
    state["peakEquity"] = peak
    return note


def _lock_text(lock: dict[str, object], auto_left: bool) -> str:
    since = int(lock.get("since") or 0)
    if auto_left:
        until = datetime.fromtimestamp(since + DRAWDOWN_COOLDOWN_SECONDS, VN_TZ).strftime("%d/%m %H:%M")
        return f"khóa sụt giảm đến {until} giờ Việt Nam"
    return "khóa sụt giảm lần hai, cần bấm mở khóa"


def _snapshot() -> dict[str, object]:
    state = _read_state()
    settings = read_settings()
    symbol = str(settings["symbol"] or "XAUUSDm")
    with open_terminal() as mt5:
        account = mt5.account_info()
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        rates = mt5.copy_rates_from_pos(symbol, _frame(mt5), 0, LIVE_BARS)
        hmm_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 250)
        positions = mt5.positions_get(symbol=symbol) or []
        if account is None or tick is None or rates is None or len(rates) == 0:
            code, message = mt5.last_error()
            raise RuntimeError(f"Chưa đọc được giá thời gian thực ({code}): {message}")
        now = int(tick.time)
        closed, reopen = _weekend_close()
        if closed:
            return _closed_snapshot(state, symbol, tick, account, positions, reopen)
        closed_bar, next_close = _schedule(rates, now)
        daily = _daily_profit(mt5, now)
        equity = float(account.equity)
        limits = read_risk()
        unlock_note = _drawdown_gate(state, equity, limits)
        peak = float(state["peakEquity"])
        streak = _loss_streak(mt5, now, MAGIC)
        strategy = _strategy_for(rates, closed_bar, float(limits["minRewardRatio"]))
        if state.get("methodBar") != closed_bar:
            _method_paper_step(strategy, rates, closed_bar, tick, info)
            state["methodBar"] = closed_bar
        if AGENT_MODE:
            strategy = _agent_card(strategy, "trend")
        shadow_rates = mt5.copy_rates_from_pos(symbol, int(getattr(mt5, "TIMEFRAME_" + SHADOW_TIMEFRAME)), 0, LIVE_BARS)
        if shadow_rates is not None and len(shadow_rates) > 30:
            shadow_bar, _ = _schedule(shadow_rates, now, SHADOW_SECONDS)
            if state.get("shadowBar") != shadow_bar:
                shadow_strategy = _strategy_for(shadow_rates, shadow_bar, float(limits["minRewardRatio"]), SHADOW_TIMEFRAME, SHADOW_SECONDS)
                _shadow_step(shadow_strategy, shadow_rates, shadow_bar, tick, info)
                state["shadowBar"] = shadow_bar
        model_mode = meta_model.read_mode()
        scored = _score_signal(rates, closed_bar, strategy) if model_mode != "off" else None
        factor = meta_model.size_factor(scored, model_mode)
        expired = _expire_positions(mt5, info, tick, symbol, rates, closed_bar, positions) if state.get("mode") == "full" else []
        if state.get("mode") == "full" and state.get("trailBar") != closed_bar:
            # once per closed bar, like the backtest: ratchet trailing stops of open positions
            expired += _trail_positions(mt5, info, tick, symbol, rates, closed_bar, list(mt5.positions_get(symbol=symbol) or []))
            state["trailBar"] = closed_bar
        if expired:
            positions = mt5.positions_get(symbol=symbol) or []
        _journal_sync(mt5, symbol)
        if state.get("mode") == "full" and AGENT_MODE:
            try:
                _manager_review(mt5, state, symbol, tick, limits, list(positions))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                _LOG.warning("manager: %s", error)
        open_risk, unprotected = _open_risk(info, positions, equity)
        plan_risk = _plan_risk(info, strategy, equity) if strategy.get("live") else None  # analysis-only plans never trade
        risk_blocks = _risk_blocks(
            len(positions), daily, equity, peak, streak, open_risk, unprotected, plan_risk, limits
        )
        if any(int(getattr(position, "magic", 0) or 0) == MAGIC for position in positions):
            # each agent holds one position at a time
            risk_blocks.append("agent Linda Raschke (Theo xu hướng M15) đang có lệnh mở, mỗi agent chỉ giữ một lệnh")
        if not agent_real("trend-M15"):
            risk_blocks.append("agent Linda Raschke " + RESEARCH_NOTE)
        coord_blocks = _coordinator_blocks(strategy, positions, info, equity, limits, plan_risk) if AGENT_MODE else []
        coord_blocks += _manager_block(state, "trend-M15", closed_bar)
        risk_blocks += coord_blocks
        lock = state.get("drawdownLock") if isinstance(state.get("drawdownLock"), dict) else None
        if lock is not None:
            risk_blocks.append(_lock_text(lock, int(state.get("autoUnlocks") or 0) == 0))
        stored = state.get("decision") if isinstance(state.get("decision"), dict) else {}
        stored_reason = str(stored.get("reason") or "")
        stored_scores = stored.get("scores") if isinstance(stored.get("scores"), list) else []
        stale = "ba tháng" in stored_reason
        needs_scores = "scores" not in stored
        needs_hmm = not any(str(line).startswith(GATE_LINE_MARK) for line in stored_scores)
        needs_live = LIVE_MARK not in stored_reason
        needs_points = "points" not in stored
        fresh = state.get("lastBar") != closed_bar or "candle" not in stored
        if state.get("mode") == "full" and (fresh or stale or needs_scores or needs_hmm or needs_live or needs_points):
            same_candle = not fresh and "candle" in stored
            state["lastBar"] = closed_bar
            # The HMM regime filter was trained on M15 returns, so it keeps reading closed M15 bars.
            closes = [float(row["close"]) for row in (hmm_rates if hmm_rates is not None else []) if int(row["time"]) + 900 <= now]
            decision = _decide(symbol, tick, closed_bar, risk_blocks, strategy, closes)
            if _manager_note(state, "trend-M15", closed_bar):
                decision["reason"] = _manager_note(state, "trend-M15", closed_bar) + str(decision["reason"])
            decision["signal"] = _has_signal(strategy)
            decision["side"] = strategy.get("side")
            decision["blocks"] = {"coordinator": list(coord_blocks), "risk": [item for item in risk_blocks if item not in coord_blocks]}
            if scored is not None:
                decision["model"] = {**scored, "factor": factor, "mode": model_mode}
                decision["reason"] = str(decision["reason"]) + " " + _model_sentence(scored, factor, model_mode)
            if expired:
                decision["reason"] = str(decision["reason"]) + " " + " ".join(expired)
            if unlock_note:
                decision["reason"] = str(decision["reason"]) + " " + unlock_note
            age = now - (closed_bar + DECISION_SECONDS)
            if fresh and decision.get("ready"):
                held_back = age > SEND_WINDOW_SECONDS or state.get("lastSentBar") == closed_bar or state.get("llmSkipBar") == closed_bar
                if held_back:
                    decision["reason"] = str(decision["reason"]).replace(" Gửi lệnh thật.", "")
                if age > SEND_WINDOW_SECONDS:
                    decision["ready"] = False
                    decision["action"] = "CHỜ"
                    decision["blocks"]["risk"].append("nến đã đóng quá lâu, không vào lệnh trễ")
                    decision["reason"] = (
                        str(decision["reason"])
                        + f" Không gửi: nến đã đóng {age // 60} phút {age % 60} giây trước, quá {SEND_WINDOW_SECONDS} giây cho phép. Không vào lệnh trễ."
                    )
                elif state.get("lastSentBar") == closed_bar:
                    decision["ready"] = False
                    decision["action"] = "CHỜ"
                    decision["reason"] = str(decision["reason"]) + " Đã gửi lệnh cho nến này rồi, không gửi lại."
                elif state.get("llmSkipBar") == closed_bar:
                    decision["ready"] = False
                    decision["action"] = "CHỜ"
                    decision["reason"] = str(decision["reason"]) + " Claude đã quyết định bỏ tín hiệu của nến này."
                else:
                    gate = _claude_gate("trend-M15", strategy, rates, closed_bar, LIVE_TIMEFRAME, symbol, list(positions), state, equity, info, limits)
                    decision["claude"] = _gate_brief(gate)
                    if gate is not None and gate["decision"] == "bỏ":
                        state["llmSkipBar"] = closed_bar
                        _write_state(state)
                        decision["ready"] = False
                        decision["action"] = "CHỜ"
                        decision["reason"] = str(decision["reason"]).replace(" Gửi lệnh thật.", "") + " " + _gate_text(gate)
                        _record_veto("trend-M15", strategy, closed_bar, LIVE_TIMEFRAME, gate)
                    else:
                        tick = _fresh_tick(mt5, symbol, tick, gate)
                        use = factor * (gate["factor"] if gate is not None else 1.0)
                        sent, note, detail = _send_order(mt5, info, tick, symbol, strategy, equity, limits, use)
                        decision["sent"] = sent
                        decision["reason"] = str(decision["reason"]) + " " + _gate_text(gate) + (" Đã gửi " + note + "." if sent else " Không gửi được lệnh: " + note + ".")
                        if sent:
                            # Persist at once: if anything below fails, the next pass must not resend.
                            state["lastSentBar"] = closed_bar
                            _write_state(state)
                            _journal_open(symbol, strategy, {**detail, "score": None if scored is None else scored["score"], "size_factor": use, "agent": "trend-M15"}, closed_bar, equity, str(decision["reason"]))
                            _gate_journal(detail, gate, "trend-M15")
                        else:
                            decision["action"] = "CHỜ"
            if same_candle and stored.get("sent"):
                decision = dict(stored, scores=decision["scores"])
            decision["points"] = _points(strategy)
            state["decision"] = decision
            history = state.get("history") if isinstance(state.get("history"), list) else []
            if same_candle and history and isinstance(history[0], dict) and history[0].get("candle") == state["decision"].get("candle"):
                history[0] = state["decision"]
                state["history"] = history[:12]
            else:
                state["history"] = [state["decision"], *history][:12]
        if state.get("mode") == "full":
            lock_text = "" if lock is None else _lock_text(lock, int(state.get("autoUnlocks") or 0) == 0)
            for book_key, book_config in EXTRA_BOOKS.items():
                try:
                    _book_step(mt5, state, book_key, book_config, symbol, tick, info, equity, limits, daily, peak, streak, lock_text)
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                    _LOG.warning("book %s: %s", book_key, error)
        _write_state(state)
        spread_points = int(info.spread) if info is not None else 0
        drawdown = 0.0 if peak <= 0 else (peak - equity) / peak
        daily_loss = 0.0 if equity <= 0 or daily >= 0 else abs(daily) / equity * 100
        decision = state.get("decision") or {
            "action": "CHỜ",
            "reason": f"Tự động đang chạy. Quyết định tiếp theo khi nến {LIVE_TIMEFRAME} đóng.",
            "sent": False,
        }
        return {
            "ok": True,
            "symbol": symbol,
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "spreadPoints": spread_points,
            "serverTime": datetime.fromtimestamp(now, timezone.utc).strftime("%H:%M:%S"),
            "secondsToDecision": max(0, next_close - now),
            "nextDecision": datetime.fromtimestamp(next_close, timezone.utc).strftime("%H:%M:%S"),
            "balance": float(account.balance),
            "equity": equity,
            "freeMargin": float(account.margin_free),
            "dailyProfit": daily,
            "drawdown": round(drawdown, 4),
            "positions": len(positions),
            "mode": state.get("mode") or "full",
            "emergency": bool(state.get("emergency")),
            "drawdownLock": lock is not None,
            "autopilot": {
                "lastRun": datetime.fromtimestamp(_AUTOPILOT["lastRun"], VN_TZ).strftime("%H:%M:%S") if _AUTOPILOT["lastRun"] else "",
                "error": _AUTOPILOT["lastError"],
            },
            "decision": decision,
            "history": state.get("history") if isinstance(state.get("history"), list) else [],
            "risk": "Đang chặn" if state.get("emergency") or risk_blocks else "An toàn",
            "limits": limits,
            "pipeline": _pipeline(strategy, tick, risk_blocks, bool(state.get("emergency")), decision, positions, state.get("books")),
            "agents": _agents_view(state, list(positions), info, equity, limits, strategy),
            "usage": {
                "perTradePercent": None if unprotected else round(open_risk, 2),
                "perTradeNote": "có vị thế chưa có cắt lỗ" if unprotected else "",
                "dailyLossPercent": round(daily_loss, 2),
                "drawdownPercent": round(drawdown * 100, 2),
                "positions": len(positions),
                "lossStreak": streak,
                "planRiskPercent": None if plan_risk is None else round(plan_risk, 2),
                "planRewardRatio": _plan_reward(strategy),
            },
        }


def apply_default_risk() -> dict[str, object]:
    settings = read_settings()
    symbol = str(settings["symbol"] or "XAUUSDm")
    try:
        with open_terminal() as mt5:
            account = mt5.account_info()
            info = mt5.symbol_info(symbol)
            rates = mt5.copy_rates_from_pos(symbol, _frame(mt5), 0, LIVE_BARS)
        if account is None or info is None or rates is None or len(rates) == 0:
            raise RuntimeError("Chưa đọc được tài khoản.")
        bars = [
            (float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))
            for row in rates
        ]
        from services.api.chart_analysis import _atr

        atr = next((value for value in reversed(_atr(bars, 14)) if value is not None), 1.0)
        suggested = _suggest_risk(float(account.equity), atr, info)
    except (OSError, RuntimeError, TypeError, ValueError):
        saved = save_risk(
            {
                "perTradePercent": 0.5,
                "dailyLossPercent": 2,
                "drawdownPercent": 10,
                "maxPositions": 2,
                "maxLossStreak": 3,
                "minRewardRatio": 1.5,
            }
        )
        return {
            "ok": True,
            **saved,
            "reason": "Chưa đọc được MetaTrader. Đã đặt mức thử nghiệm: 0,5% mỗi lệnh, lỗ ngày 2%, sụt giảm 10%, 2 vị thế, chuỗi thua 3, tỷ lệ 1:1,5.",
        }
    saved = save_risk(suggested)
    return {"ok": True, **saved, "reason": str(suggested["reason"])}


def _suggest_risk(equity: float, atr: float, info: object) -> dict[str, float | int | str]:
    tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    volume = float(getattr(info, "volume_min", 0) or 0)
    stop = max(float(atr) * 1.2, 0.5)
    if equity <= 0 or tick_size <= 0 or tick_value <= 0 or volume <= 0:
        floor = 0.5
    else:
        floor = (stop / tick_size * tick_value * volume) / equity * 100
    per_trade = _round_up(max(0.5, floor * 1.25), 0.1, 5)
    daily = _round_up(max(2.0, per_trade * 3), 0.1, 20)
    drawdown = 10.0 if daily <= 10 else _round_up(daily * 1.5, 0.1, 50)
    positions = 1 if per_trade * 2 > daily else 2
    reason = (
        f"Khối lượng nhỏ nhất {volume:g} với cắt lỗ khoảng {_comma(stop)} đang chiếm {_comma(floor)}% vốn. "
        f"Đặt rủi ro mỗi lệnh {_comma(per_trade)}% để lệnh nhỏ nhất không bị chặn, lỗ ngày {_comma(daily)}% cho đủ 3 lệnh thua, "
        f"sụt giảm {_comma(drawdown)}%, tối đa {positions} vị thế, tỷ lệ 1:1,5."
    )
    return {
        "perTradePercent": per_trade,
        "dailyLossPercent": daily,
        "drawdownPercent": drawdown,
        "maxPositions": positions,
        "maxLossStreak": 3,
        "minRewardRatio": 1.5,
        "reason": reason,
    }


def _comma(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _round_up(value: float, step: float, high: float) -> float:
    units = math.ceil((value / step) - 1e-9)
    return round(min(high, max(step, units * step)), 2)


def set_mode(mode: str, emergency: bool | None = None) -> dict[str, object]:
    with _STATE_LOCK:
        state = _read_state()
        if mode in {"analysis", "signal", "semi", "full"}:
            state["mode"] = mode
        if emergency is not None:
            state["emergency"] = emergency
        _write_state(state)
    return {"ok": True, "mode": state.get("mode"), "emergency": bool(state.get("emergency"))}


def _weekend_close() -> tuple[bool, datetime]:
    moment = datetime.now(VN_TZ)
    if moment.weekday() < 5:
        return False, moment
    monday = moment.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7 - moment.weekday())
    return True, monday


def _closed_snapshot(
    state: dict[str, object],
    symbol: str,
    tick: object,
    account: object,
    positions: list[object],
    reopen: datetime,
) -> dict[str, object]:
    stored = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    decision = {
        "action": "CHỜ",
        "reason": "Thứ Bảy và Chủ Nhật phiên đóng. Không chấm và không gửi lệnh.",
        "ready": False,
        "sent": False,
        "candle": stored.get("candle") or "",
        "strategy": stored.get("strategy") or "Chưa chọn",
        "points": "—",
        "scores": [],
    }
    seconds = max(0, int((reopen - datetime.now(VN_TZ)).total_seconds()))
    equity = float(account.equity)
    return {
        "ok": True,
        "marketClosed": True,
        "drawdownLock": isinstance(state.get("drawdownLock"), dict),
        "autopilot": {
            "lastRun": datetime.fromtimestamp(_AUTOPILOT["lastRun"], VN_TZ).strftime("%H:%M:%S") if _AUTOPILOT["lastRun"] else "",
            "error": _AUTOPILOT["lastError"],
        },
        "symbol": symbol,
        "bid": float(tick.bid),
        "ask": float(tick.ask),
        "spreadPoints": 0,
        "serverTime": datetime.fromtimestamp(int(tick.time), timezone.utc).strftime("%H:%M:%S"),
        "secondsToDecision": seconds,
        "nextDecision": "Thứ Hai 00:00",
        "balance": float(account.balance),
        "equity": equity,
        "freeMargin": float(account.margin_free),
        "dailyProfit": 0.0,
        "drawdown": 0.0,
        "positions": len(positions),
        "mode": state.get("mode") or "full",
        "emergency": bool(state.get("emergency")),
        "decision": decision,
        "history": state.get("history") if isinstance(state.get("history"), list) else [],
        "risk": "Phiên đóng",
        "limits": read_risk(),
        "pipeline": _closed_pipeline(),
        "agents": _agents_view(state, list(positions), None, equity, read_risk()),
        "usage": {
            "perTradePercent": 0,
            "perTradeNote": "",
            "dailyLossPercent": 0,
            "drawdownPercent": 0,
            "positions": len(positions),
            "lossStreak": 0,
            "planRiskPercent": None,
            "planRewardRatio": None,
        },
    }


def _closed_pipeline() -> dict[str, object]:
    return {
        "label": "—",
        "groups": [],
        "rule": "Thứ Bảy và Chủ Nhật phiên đóng. Bot không chấm điều kiện và không gửi lệnh.",
        "steps": [{"name": "Phiên", "value": "Đóng đến thứ Hai", "tone": "off"}],
    }


def _schedule(rates: object, now: int, seconds: int = DECISION_SECONDS) -> tuple[int, int]:
    opens = [int(row["time"]) for row in rates]
    current_open = opens[-1]
    if now >= current_open + seconds:
        return current_open, current_open + (2 * seconds)
    previous = opens[-2] if len(opens) > 1 else current_open
    return previous, current_open + seconds


def _decide(
    symbol: str,
    tick: object,
    closed_bar: int,
    risk_blocks: list[str],
    strategy: dict[str, object],
    closes: list[float],
) -> dict[str, object]:
    blocks = list(risk_blocks)
    if _spread_price(tick) > 0.8:
        blocks.append("chênh lệch quá rộng")
    # The HMM regime veto is no longer applied. Walk-forward 2025-2026 on M30: it blocked 87 of
    # 223 trend signals, and those earned +0.28R each against +0.04R for the ones it let through.
    live_rule = bool(strategy.get("live")) and bool(strategy.get("confirmed")) and strategy.get("side") in {"buy", "sell"}
    if not live_rule:
        if strategy.get("side") in {"buy", "sell"} and not strategy.get("live"):
            blocks.append(f"{strategy.get('name')} chỉ để phân tích, kiểm thử dài hạn chưa cho lợi thế")
        else:
            blocks.append(str(strategy.get("reason") or "chưa có tín hiệu đủ điều kiện"))
    state = _read_state()
    if state.get("emergency"):
        blocks.append("dừng khẩn cấp")
    passed = not blocks
    ready = passed and strategy["side"] in {"buy", "sell"}
    action = "MUA" if ready and strategy["side"] == "buy" else "BÁN" if ready else "CHỜ"
    candle = datetime.fromtimestamp(closed_bar, timezone.utc).strftime("%H:%M")
    reason = (
        f"{LIVE_MARK}. Nến {LIVE_TIMEFRAME} {candle} đã đóng. Chiến lược {strategy['name']}. {strategy['reason']} "
        + ("Không gửi lệnh: " + ", ".join(blocks) + "." if blocks else "Tín hiệu đủ điều kiện và cổng rủi ro đạt. Gửi lệnh thật.")
    )
    return {
        "action": action,
        "reason": reason,
        "ready": ready,
        "sent": False,
        "candle": candle,
        "strategy": strategy["name"],
        "riskPass": not risk_blocks and not state.get("emergency"),
        "symbol": symbol,
        "scores": _gate_lines(strategy),
    }


def _send_order(
    mt5: object,
    info: object,
    tick: object,
    symbol: str,
    strategy: dict[str, object],
    equity: float,
    limits: dict[str, float | int],
    factor: float = 1.0,
    magic: int = MAGIC,
    tag: str = "",
) -> tuple[bool, str, dict[str, object]]:
    side = str(strategy.get("side"))
    if info is None or side not in {"buy", "sell"}:
        return False, "chưa có mã hoặc chiều lệnh", {}
    price = float(tick.ask if side == "buy" else tick.bid)
    # Keep the planned stop and target distances from the real fill, as the backtest does.
    try:
        planned_entry = float(strategy["entry"])
        distance = abs(planned_entry - float(strategy["stop"]))
    except (TypeError, ValueError, KeyError):
        return False, "kế hoạch chưa có cắt lỗ", {}
    if distance <= 0:
        return False, "kế hoạch chưa có cắt lỗ", {}
    stop = price - distance if side == "buy" else price + distance
    # factor < 1 when the signal model scores the trade low; it never raises the user's risk limit
    volume = _sized_volume(
        info, equity, float(limits["perTradePercent"]) / 100 * min(1.0, factor), distance, float(limits.get("minLotPercent") or 0) / 100
    )
    if volume is None:
        return False, "khối lượng nhỏ nhất đã vượt rủi ro cho phép (kể cả mức cho vốn nhỏ)", {}
    digits = int(getattr(info, "digits", 2) or 2)
    take = strategy.get("takeProfit")
    try:
        reward = 0.0 if take is None else abs(float(take) - planned_entry)
    except (TypeError, ValueError):
        reward = 0.0
    target = 0.0 if reward <= 0 else (price + reward if side == "buy" else price - reward)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": round(stop, digits),
        "tp": round(target, digits) if target else 0.0,
        "deviation": 50,
        "magic": magic,
        "comment": ("GoldTrader " + str(strategy.get("id") or "") + (" " + tag if tag else ""))[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling(mt5, info),
    }
    result = mt5.order_send(request)
    if result is None:
        code, message = mt5.last_error()
        return False, f"{code} {message}", {}
    done = {int(mt5.TRADE_RETCODE_DONE), int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010))}
    if int(getattr(result, "retcode", 0)) in done:
        fill = float(getattr(result, "price", 0) or 0) or price
        tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
        tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
        filled_volume = float(getattr(result, "volume", 0) or 0) or volume
        detail = {
            "position": int(getattr(result, "order", 0) or 0),
            # broker time, the same clock as the closing deal in MetaTrader's history
            "opened_at": int(getattr(tick, "time", 0) or 0) or int(time.time()),
            "side": side,
            "planned_entry": planned_entry,
            "requested": price,
            "fill": fill,
            "sl": request["sl"],
            "tp": request["tp"],
            "volume": filled_volume,
            "risk_money": abs(fill - float(request["sl"])) / tick_size * tick_value * filled_volume if tick_size > 0 else 0.0,
            "spread": float(tick.ask) - float(tick.bid),
        }
        return True, f"{filled_volume:g} lot", detail
    return False, str(getattr(result, "comment", None) or getattr(result, "retcode", "từ chối")), {}


def _sized_volume(info: object, equity: float, per_trade: float, distance: float, min_lot_cap: float = 0.0) -> float | None:
    """Volume risking `per_trade` of equity. When that is below the minimum lot, the minimum lot
    is used if it risks at most `min_lot_cap` of equity (small accounts); otherwise None."""
    tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    if equity <= 0 or tick_size <= 0 or tick_value <= 0 or distance <= 0:
        return None
    step = float(getattr(info, "volume_step", 0) or 0.01)
    minimum = float(getattr(info, "volume_min", 0) or 0.01)
    maximum = float(getattr(info, "volume_max", 0) or 50)
    money_per_lot = distance / tick_size * tick_value
    if money_per_lot <= 0 or step <= 0:
        return None
    volume = math.floor((equity * per_trade / money_per_lot) / step) * step
    volume = round(min(maximum, volume), 2)
    if volume < minimum:
        if min_lot_cap > 0 and money_per_lot * minimum <= equity * min_lot_cap + 1e-9:
            return round(minimum, 2)
        return None
    return volume


def _filling(mt5: object, info: object) -> int:
    mask = int(getattr(info, "filling_mode", 0) or 0)
    if mask & 1:
        return int(mt5.ORDER_FILLING_FOK)
    if mask & 2:
        return int(mt5.ORDER_FILLING_IOC)
    return int(mt5.ORDER_FILLING_RETURN)


GATE_LINE_MARK = "Điều kiện"
GATE_SHORT = {"trend": "XH", "pullback": "HG"}


def _live_cards(strategy: dict[str, object], ids: tuple[str, ...] | None = None) -> list[dict[str, object]]:
    from services.api.strategies import LIVE_STRATEGIES

    catalog = strategy.get("catalog") if isinstance(strategy.get("catalog"), list) else []
    wanted = ids or tuple(LIVE_STRATEGIES)
    cards = {str(card.get("id")): card for card in catalog if isinstance(card, dict) and card.get("gates")}
    return [cards[name] for name in wanted if name in cards]


def _gate_count(card: dict[str, object]) -> tuple[int, int]:
    gates = [gate for gate in card["gates"] if gate["state"] != "skip"]
    return sum(1 for gate in gates if gate["state"] == "ok"), len(gates)


def _gate_stop(card: dict[str, object] | None) -> tuple[str, str]:
    """Where the card stopped: the first failed entry condition, or all passed."""
    if card is None:
        return "Chưa chấm", "off"
    failed = next((gate for gate in card["gates"] if gate["state"] == "fail"), None)
    passed, total = _gate_count(card)
    if failed is None:
        return f"Đủ {passed}/{total} điều kiện", "ok"
    return f"Dừng ở «{failed['name']}» ({passed}/{total})", "wait"


def _points(strategy: dict[str, object], ids: tuple[str, ...] | None = None) -> str:
    """Conditions met by each live strategy on the closed bar, e.g. "XH 6/10 · HG 2/7"."""
    parts = []
    for card in _live_cards(strategy, ids):
        passed, total = _gate_count(card)
        parts.append(f"{GATE_SHORT.get(str(card['id']), card['name'])} {passed}/{total}")
    return " · ".join(parts) or "—"


def _gate_lines(strategy: dict[str, object], ids: tuple[str, ...] | None = None) -> list[str]:
    lines = []
    for card in _live_cards(strategy, ids):
        text, _tone = _gate_stop(card)
        lines.append(f"{GATE_LINE_MARK} {card['name']}: {text[0].lower() + text[1:]}")
    return lines or [f"{GATE_LINE_MARK}: chưa đủ nến để chấm"]


def _pipeline(
    strategy: dict[str, object],
    tick: object,
    risk_blocks: list[str],
    emergency: bool,
    decision: dict[str, object],
    positions: list[object],
    books: object = None,
) -> dict[str, object]:
    """What the bot actually checked on the closed bar: the entry conditions of each live
    strategy in the order the code tests them, then the risk gates, then the order."""
    cards = {str(card["id"]): card for card in _live_cards(strategy)}
    groups = [
        {"name": f"{card['name']} {LIVE_TIMEFRAME}" + (" (ưu tiên 1)" if name == "trend" else " (ưu tiên 2)"), "gates": card["gates"]}
        for name, card in cards.items()
    ]
    spread = _spread_price(tick)
    risk_gates = [{"name": f"Chênh lệch ≤ 0,80 (đang {spread:.2f})", "state": "ok" if spread <= 0.8 else "fail"}]
    if emergency:
        risk_gates.append({"name": "Dừng khẩn cấp đang bật", "state": "fail"})
    risk_gates += [{"name": text[:1].upper() + text[1:], "state": "fail"} for text in risk_blocks]
    if not risk_blocks and not emergency:
        risk_gates.append({"name": "Lỗ ngày, chuỗi thua sổ M15, khóa sụt giảm: chưa chạm giới hạn; sổ M15 chưa có lệnh", "state": "ok"})
    groups.append({"name": "Cổng rủi ro", "gates": risk_gates})
    risk_ok = not risk_blocks and not emergency
    sent = bool(decision.get("sent"))
    chosen = str(strategy.get("name") or "") if strategy.get("live") and strategy.get("side") in {"buy", "sell"} else ""
    trend_text, trend_tone = _gate_stop(cards.get("trend"))
    pull_text, pull_tone = _gate_stop(cards.get("pullback"))
    own = [position for position in positions if int(getattr(position, "magic", 0) or 0) == MAGIC]
    steps = [
        {"name": "01 Nhận giá từ MT5", "value": "Xong", "tone": "ok"},
        {"name": f"02 Nến {LIVE_TIMEFRAME} đóng", "value": str(decision.get("candle") or "—"), "tone": "ok"},
        {"name": "03 Linda Raschke (Theo xu hướng M15)", "value": trend_text, "tone": trend_tone},
        {"name": "04 Larry Connors (Hồi giá M15)", "value": pull_text, "tone": pull_tone},
        {"name": "05 Agent tổng (Paul Tudor Jones)", "value": "Linda Raschke có tín hiệu" if chosen else "Linda Raschke chờ", "tone": "ok" if chosen else "off"},
        {"name": "06 Cổng rủi ro", "value": "Đạt" if risk_ok else "Chặn", "tone": "ok" if risk_ok else "bad"},
        {"name": f"07 Gửi lệnh {LIVE_TIMEFRAME} (kiểm khối lượng tối thiểu)", "value": "Đã gửi" if sent else "Không gửi", "tone": "ok" if sent else "off"},
        {"name": "08 Cắt lỗ bám 3 ATR sau khi lời 1R", "value": f"Theo dõi {len(own)} lệnh" if own else "Không có lệnh", "tone": "wait" if own else "off"},
    ]
    number = 9
    for key, config in EXTRA_BOOKS.items():
        book = books.get(key) if isinstance(books, dict) and isinstance(books.get(key), dict) else {}
        last = book.get("last") if isinstance(book.get("last"), dict) else {}
        value = f"{last.get('candle', '')}: {last.get('action', 'CHỜ')}" if last else "Chưa chấm"
        if last.get("points"):
            value += f" · {last['points']}"
        steps.append({"name": f"{number:02d} Agent {config.get('name') or key}", "value": value, "tone": "ok" if last.get("sent") else "wait" if last else "off"})
        number += 1
    steps.append({"name": f"{number:02d} Vị thế đang mở", "value": _position_label(positions), "tone": "wait" if positions else "off"})
    review = _review_step()
    review["name"] = f"{number + 1:02d} Đối chiếu với kiểm thử"
    steps.append(review)
    return {
        "label": str(decision.get("points") or _points(strategy)),
        "groups": groups,
        "rule": "Không cộng điểm. Lệnh chỉ gửi khi một chiến lược đạt mọi điều kiện theo đúng thứ tự dưới đây và cổng rủi ro đạt. "
        "Bot dừng ở điều kiện đầu tiên không đạt; các điều kiện sau ghi là chưa xét. Mô hình và LLM không tham gia.",
        "steps": steps,
    }


def _risk_blocks(
    positions: int,
    daily: float,
    equity: float,
    peak: float,
    streak: int,
    open_risk: float,
    unprotected: bool,
    plan_risk: float | None,
    limits: dict[str, float | int],
) -> list[str]:
    blocks: list[str] = []
    max_positions = int(limits["maxPositions"])
    if positions >= max_positions:
        blocks.append(f"đủ {max_positions} vị thế")
    daily_limit = float(limits["dailyLossPercent"])
    if equity > 0 and daily <= -(daily_limit / 100) * equity:
        blocks.append(f"lỗ trong ngày chạm {daily_limit:g}%")
    drawdown = 0.0 if peak <= 0 else (peak - equity) / peak
    drawdown_limit = float(limits["drawdownPercent"])
    if drawdown * 100 >= drawdown_limit:
        blocks.append(f"sụt giảm chạm {drawdown_limit:g}%")
    loss_limit = int(limits["maxLossStreak"])
    if streak >= loss_limit:
        blocks.append(f"chuỗi thua chạm {loss_limit}")
    # a minimum-lot trade of a small account may risk up to minLotPercent
    trade_limit = max(float(limits["perTradePercent"]), float(limits.get("minLotPercent") or 0))
    if unprotected:
        blocks.append("có vị thế chưa có cắt lỗ")
    elif open_risk > trade_limit + 0.01:
        blocks.append(f"rủi ro vị thế đang mở vượt {trade_limit:g}%")
    if plan_risk is not None and plan_risk > trade_limit:
        blocks.append(f"kế hoạch vượt {trade_limit:g}% ngay ở khối lượng nhỏ nhất")
    return blocks


def _open_risk(info: object, positions: object, equity: float) -> tuple[float, bool]:
    if equity <= 0 or info is None:
        return 0.0, False
    tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    worst = 0.0
    unprotected = False
    for position in positions:
        stop = float(getattr(position, "sl", 0) or 0)
        if stop <= 0:
            unprotected = True
            continue
        if tick_size <= 0 or tick_value <= 0:
            continue
        # a stop already past the entry (trailing) has no risk left
        worst = max(worst, _position_risk(info, position, equity))
    return worst, unprotected


def _plan_risk(info: object, strategy: dict[str, object], equity: float) -> float | None:
    if strategy.get("side") not in {"buy", "sell"} or equity <= 0 or info is None:
        return None
    try:
        distance = abs(float(strategy["entry"]) - float(strategy["stop"]))
    except (TypeError, ValueError, KeyError):
        return None
    if distance <= 0:
        return None
    tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    volume = float(getattr(info, "volume_min", 0) or 0)
    if tick_size <= 0 or tick_value <= 0 or volume <= 0:
        return None
    money = distance / tick_size * tick_value * volume
    return money / equity * 100


def _plan_reward(strategy: dict[str, object]) -> float | None:
    try:
        risk = abs(float(strategy["entry"]) - float(strategy["stop"]))
        reward = abs(float(strategy["takeProfit"]) - float(strategy["entry"]))
    except (TypeError, ValueError, KeyError):
        return None
    if risk <= 0 or strategy.get("side") not in {"buy", "sell"}:
        return None
    return round(reward / risk, 2)


def _loss_streak(mt5: object, server_time: int, magic: int | None = None) -> int:
    """Consecutive losing closes today. With `magic`, only that book's positions count: each
    book has its own streak (the backtest does the same); daily loss and drawdown stay shared."""
    try:
        moment = datetime.fromtimestamp(server_time, timezone.utc).replace(tzinfo=None)
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(start, moment) or []
    except (OSError, RuntimeError, TypeError, ValueError):
        return 0
    closed = []
    for deal in deals:
        if int(getattr(deal, "entry", -1)) not in {1, 2, 3}:
            continue
        if magic is not None and _deal_magic(mt5, deal) != magic:
            continue
        net = float(deal.profit) + float(deal.commission) + float(deal.swap)
        closed.append((int(deal.time), net))
    streak = 0
    for _, net in sorted(closed, reverse=True):
        if net < 0:
            streak += 1
            continue
        break
    return streak


def _deal_magic(mt5: object, deal: object) -> int:
    """Magic of the position a closing deal belongs to. A close by the broker's stop or target
    may carry magic 0, so fall back to the deal that opened the position."""
    magic = int(getattr(deal, "magic", 0) or 0)
    if magic:
        return magic
    try:
        history = mt5.history_deals_get(position=int(getattr(deal, "position_id", 0) or 0)) or []
    except (OSError, RuntimeError, TypeError, ValueError):
        return 0
    for item in history:
        if int(getattr(item, "entry", -1)) == 0:
            return int(getattr(item, "magic", 0) or 0)
    return 0


def _position_label(positions: list[object]) -> str:
    if not positions:
        return "Không có lệnh"
    buys = sum(1 for item in positions if int(getattr(item, "type", 1)) == 0)
    sells = len(positions) - buys
    bits = []
    if buys:
        bits.append(f"{buys} lệnh mua")
    if sells:
        bits.append(f"{sells} lệnh bán")
    return ", ".join(bits)


_CARD_CACHE: dict[tuple, dict[str, object]] = {}


def _strategy_for(
    rates: object, closed_bar: int, reward_ratio: float, timeframe: str = LIVE_TIMEFRAME, seconds: int = DECISION_SECONDS
) -> dict[str, object]:
    rows = [row for row in rates if int(row["time"]) <= closed_bar]
    bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rows]
    times = [int(row["time"]) for row in rows]
    if len(bars) < 30:
        return {"name": "Chưa chọn", "side": "wait", "confirmed": False, "reason": "Chưa đủ nến để chấm."}
    key = (timeframe, int(closed_bar), float(reward_ratio), int(seconds), len(bars), times[0], bars[-1])
    if key not in _CARD_CACHE:
        if len(_CARD_CACHE) > 24:
            _CARD_CACHE.clear()
        _CARD_CACHE[key] = _evaluate_bars(bars, times, closed_bar, reward_ratio, timeframe, seconds)
    return copy.deepcopy(_CARD_CACHE[key])


def _evaluate_bars(bars: list, times: list[int], closed_bar: int, reward_ratio: float, timeframe: str, seconds: int) -> dict[str, object]:
    from services.api.chart_analysis import _atr, _thresholds
    from services.api.strategies import evaluate_strategies

    atr = _atr(bars, 14)
    last_atr = next((value for value in reversed(atr) if value is not None), 1.0)
    support, resistance = _thresholds(bars, last_atr)
    fill_hour = datetime.fromtimestamp(closed_bar + seconds, timezone.utc).hour
    return evaluate_strategies(bars, timeframe, support, resistance, None, reward_ratio, times, fill_hour)["selected"]


def _spread_price(tick: object) -> float:
    bid = float(getattr(tick, "bid", 0) or 0)
    ask = float(getattr(tick, "ask", 0) or 0)
    return max(0.0, ask - bid)


def _daily_profit(mt5: object, server_time: int) -> float:
    try:
        moment = datetime.fromtimestamp(server_time, timezone.utc).replace(tzinfo=None)
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(start, moment) or []
        return round(sum(float(deal.profit) + float(deal.commission) + float(deal.swap) for deal in deals), 2)
    except (OSError, RuntimeError, TypeError, ValueError):
        return 0.0


def _read_state() -> dict[str, object]:
    if not RUNTIME_PATH.exists():
        # First run: view-only until the user has connected MetaTrader, reviewed the agents and the
        # risk limits and chosen "Tự động" (full) on the dashboard.
        return {"mode": "analysis", "emergency": False}
    try:
        state = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except (ValueError, OSError):
        pass
    # A file cut by a power loss or sleep (seen 2026-11-10: all NUL bytes) must not stop the bot:
    # keep it for inspection and start again in automatic mode. The emergency stop and drawdown
    # lock are rebuilt from the account by the next snapshot.
    broken = RUNTIME_PATH.with_name(f"runtime.corrupt-{int(time.time())}.json")
    try:
        RUNTIME_PATH.replace(broken)
    except OSError:
        pass
    _LOG.warning("runtime.json unreadable, moved to %s", broken.name)
    return {"mode": "full", "emergency": False}


def _write_state(state: dict[str, object]) -> None:
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = RUNTIME_PATH.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(state, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(RUNTIME_PATH)


def _expire_positions(
    mt5: object,
    info: object,
    tick: object,
    symbol: str,
    rates: object,
    closed_bar: int,
    positions: list[object],
    magic: int = MAGIC,
    seconds: int = DECISION_SECONDS,
    timeframe: str = LIVE_TIMEFRAME,
    max_bars: int | None = None,
) -> list[str]:
    """Close GoldTrader positions that reached the holding limit (48 closed bars for the
    trend strategy), the same time stop the backtest applies. max_bars: the limit of the card
    the book sent its order on (the other agents' strategies)."""
    from services.api.strategies import PULLBACK_MAX_BARS, TREND_MAX_BARS, TREND_TRAIL_BARS, TREND_TRAIL_FRAMES

    trend_limit = TREND_TRAIL_BARS if timeframe in TREND_TRAIL_FRAMES else TREND_MAX_BARS
    if info is None or tick is None or rates is None:
        return []
    opens = [int(row["time"]) for row in rates if int(row["time"]) <= closed_bar]
    notes: list[str] = []
    for position in positions:
        if int(getattr(position, "magic", 0) or 0) != magic:
            continue
        opened = int(getattr(position, "time", 0) or 0)
        held = sum(1 for moment in opens if moment + seconds > opened)
        # the order comment carries the strategy id ("GoldTrader pullback")
        limit = PULLBACK_MAX_BARS if "pullback" in str(getattr(position, "comment", "") or "") else trend_limit
        if max_bars:
            limit = int(max_bars)
        if held < limit:
            continue
        buy = int(position.type) == 0
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "position": int(position.ticket),
            "volume": float(position.volume),
            "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
            "price": float(tick.bid if buy else tick.ask),
            "deviation": 50,
            "magic": magic,
            "comment": "GoldTrader het gio",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling(mt5, info),
        }
        result = mt5.order_send(request)
        done = {int(mt5.TRADE_RETCODE_DONE), int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010))}
        if result is not None and int(getattr(result, "retcode", 0)) in done:
            notes.append(f"Đã đóng vị thế {int(position.ticket)} sau {held} nến {timeframe}.")
        else:
            comment = "không có phản hồi" if result is None else str(getattr(result, "comment", None) or getattr(result, "retcode", ""))
            notes.append(f"Chưa đóng được vị thế {int(position.ticket)} hết giờ: {comment}.")
    return notes


def _journal_open(
    symbol: str,
    strategy: dict[str, object],
    detail: dict[str, object],
    closed_bar: int,
    equity: float,
    reason: str,
    timeframe: str = LIVE_TIMEFRAME,
) -> None:
    if not detail.get("position"):
        return
    name = str(strategy.get("name") or "") + ("" if timeframe == LIVE_TIMEFRAME else f" {timeframe}")
    try:
        row = journal.record_open({**detail, "signal_bar": closed_bar, "strategy": name})
        notify.send(notify.order_text(symbol, timeframe, name, row, equity, reason))
    except (OSError, ValueError, KeyError) as error:
        _LOG.warning("journal open: %s", error)


def _journal_sync(mt5: object, symbol: str) -> None:
    try:
        closed = journal.sync_closed(mt5, DECISION_SECONDS)
    except (OSError, ValueError, TypeError) as error:
        _LOG.warning("journal sync: %s", error)
        return
    if not closed:
        return
    stats = journal.summary(1)["stats"]
    for row in closed:
        notify.send(notify.close_text(symbol, row, stats))


def _review_step() -> dict[str, str]:
    try:
        stats = journal.summary(1)["stats"]
    except OSError:
        return {"name": "17 Đánh giá sau lệnh", "value": "Chưa đọc được sổ", "tone": "off"}
    if not stats["closed"]:
        return {"name": "17 Đánh giá sau lệnh", "value": "Chưa có lệnh đóng", "tone": "off"}
    average = stats["averageR"]
    tone = "ok" if average is not None and average > 0 else "bad"
    return {"name": "17 Đánh giá sau lệnh", "value": f"{stats['closed']} lệnh, {float(stats['totalR']):+.2f}R", "tone": tone}


def _score_signal(rates: object, closed_bar: int, strategy: dict[str, object]) -> dict[str, object] | None:
    # the signal model was trained on trend signals only
    if strategy.get("id") != "trend" or not strategy.get("live") or not strategy.get("confirmed") or strategy.get("side") not in {"buy", "sell"}:
        return None
    rows = [row for row in rates if int(row["time"]) <= closed_bar]
    bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rows]
    times = [int(row["time"]) for row in rows]
    fill_hour = datetime.fromtimestamp(closed_bar + DECISION_SECONDS, timezone.utc).hour
    try:
        return meta_model.score_window(
            bars, times, LIVE_TIMEFRAME, str(strategy["side"]), float(strategy["entry"]), float(strategy["stop"]), fill_hour
        )
    except (ValueError, KeyError, TypeError, OSError) as error:
        _LOG.warning("signal model: %s", error)
        return None


def _model_sentence(scored: dict[str, object], factor: float, mode: str) -> str:
    text = f"Điểm mô hình {float(scored['score']) * 100:.0f}% (ngưỡng {float(scored['threshold']) * 100:.0f}%)"
    if mode == "shadow":
        return text + ", chỉ ghi điểm, không đổi khối lượng."
    if factor < 1:
        return text + ", dưới ngưỡng nên vào nửa khối lượng."
    return text + ", đủ ngưỡng, vào đủ khối lượng."


def _remind_retraining() -> None:
    """Send one Telegram reminder per model version once it is a month old."""
    try:
        plan = meta_model.schedule()
        trained = meta_model.trained_ts()
        if not plan["due"] or meta_model.read_mode() == "off":
            return
        with _STATE_LOCK:
            state = _read_state()
            if state.get("retrainRemindedFor") == trained:
                return
            state["retrainRemindedFor"] = trained
            _write_state(state)
        age = plan["ageDays"]
        notify.send(
            "🗓 <b>Nhắc huấn luyện mô hình</b>\n"
            + (f"Mô hình chấm tín hiệu đã {age:.0f} ngày tuổi." if age is not None else "Chưa có mô hình chấm tín hiệu.")
            + "\nVào GoldTrader → Mô hình → bấm <b>Huấn luyện lại</b> (mất vài giây, cần MetaTrader đang mở)."
        )
    except (OSError, ValueError, KeyError) as error:
        _LOG.warning("retrain reminder: %s", error)


def _method_tested(strategy_id: str, agent_id: str = "") -> dict[str, object] | None:
    """Walk-forward of a research method; an agent key ("flag-H1") wins over the method id when the
    same method was measured separately on that agent's frame."""
    from services.api import methods

    key = agent_id if agent_id in methods.TESTED else strategy_id
    found = methods.TESTED.get(key)
    return None if found is None else {"periods": found, "verdict": methods.verdict(key)}


def _method_paper_step(strategy: dict[str, object], rates: object, closed_bar: int, tick: object, info: object) -> None:
    """Research methods (services/api/methods) in "paper" status: record their M15 signals as paper
    trades with each method's own exits. Never sends an order."""
    from services.api import methods

    ids = tuple(dict.fromkeys(
        [str((config.get("strategies") or ("",))[0]) for key, config in all_books().items() if str(config.get("timeframe")) == "M15" and not agent_real(key)]
        + [item for item in methods.paper_ids() if f"{item}-M15" not in EXTRA_BOOKS and methods.BY_ID[item].timeframe == "M15"]
    ))
    if ids:
        _shadow_step(strategy, rates, closed_bar, tick, info, ids, DECISION_SECONDS)


def _shadow_step(
    strategy: dict[str, object], rates: object, closed_bar: int, tick: object, info: object,
    ids: tuple[str, ...] | None = None, seconds: int | None = None,
) -> None:
    """Paper-trade the candidate strategies on each closed bar; never sends an order."""
    from services.api.strategies import SHADOW_STRATEGIES

    try:
        rows = [row for row in rates if int(row["time"]) <= closed_bar]
        bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rows]
        times = [int(row["time"]) for row in rows]
        point = float(getattr(info, "point", 0) or 0.001)
        swap_points = int(getattr(info, "swap_mode", 0) or 0) == 1
        shadow.process(
            SHADOW_STRATEGIES if ids is None else ids,
            strategy.get("catalog"),
            bars,
            times,
            SHADOW_SECONDS if seconds is None else seconds,
            tick,
            max(_spread_price(tick), point),
            -float(getattr(info, "swap_long", 0) or 0) * point if swap_points else 0.0,
            -float(getattr(info, "swap_short", 0) or 0) * point if swap_points else 0.0,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        _LOG.warning("shadow: %s", error)


def _book_step(
    mt5: object,
    state: dict[str, object],
    key: str,
    config: dict[str, object],
    symbol: str,
    tick: object,
    info: object,
    equity: float,
    limits: dict[str, float | int],
    daily: float,
    peak: float,
    streak: int,
    lock_text: str,
) -> None:
    """One agent book (EXTRA_BOOKS): one strategy on one timeframe, own magic and position, own
    time stop and losing streak, shared account risk limits and the coordinator's rules. Acts
    once per closed bar of its timeframe."""
    seconds, magic, factor = int(config["seconds"]), int(config["magic"]), float(config["factor"])
    timeframe = str(config.get("timeframe") or key)
    label = str(config.get("name") or f"Sổ {timeframe}")
    books = state.get("books") if isinstance(state.get("books"), dict) else {}
    state["books"] = books
    book = books.get(key) if isinstance(books.get(key), dict) else {}
    books[key] = book
    rates = mt5.copy_rates_from_pos(symbol, int(getattr(mt5, "TIMEFRAME_" + timeframe)), 0, LIVE_BARS)
    if rates is None or len(rates) < 30:
        return
    now = int(tick.time)
    closed_bar, _ = _schedule(rates, now, seconds)
    positions = list(mt5.positions_get(symbol=symbol) or [])
    expired = _expire_positions(mt5, info, tick, symbol, rates, closed_bar, positions, magic, seconds, timeframe, book.get("maxBars"))
    if book.get("manage") == "trail":
        expired += _trail_positions(mt5, info, tick, symbol, rates, closed_bar, list(mt5.positions_get(symbol=symbol) or []), magic, seconds)
    if expired:
        positions = list(mt5.positions_get(symbol=symbol) or [])
        book["note"] = " ".join(expired)
    if book.get("lastBar") == closed_bar:
        return
    book["lastBar"] = closed_bar
    strategy = _strategy_for(rates, closed_bar, float(limits["minRewardRatio"]), timeframe, seconds)
    candle = timeframe + " " + datetime.fromtimestamp(closed_bar, timezone.utc).strftime("%H:%M")
    allowed = tuple(config.get("strategies") or ("trend",))
    if timeframe != LIVE_TIMEFRAME and not agent_real(key):
        _shadow_step(strategy, rates, closed_bar, tick, info, allowed, seconds)
    strategy = _agent_card(strategy, allowed[0])
    if not (strategy.get("confirmed") and strategy.get("side") in {"buy", "sell"}):
        book["last"] = {"candle": candle, "action": "CHỜ", "reason": str(strategy.get("reason") or ""), "points": _points(strategy, allowed), "gates": strategy.get("gates") or [], "signal": False}
        return
    if not agent_real(key):
        side_word = "mua" if strategy.get("side") == "buy" else "bán"
        book["last"] = {"candle": candle, "action": "CHỜ", "signal": True, "side": strategy.get("side"), "points": _points(strategy, allowed), "gates": strategy.get("gates") or [],
                        "reason": f"Agent {label} thấy tín hiệu {side_word} ở nến {candle}, nhưng {RESEARCH_NOTE}. {strategy.get('reason') or ''}"}
        return
    open_risk, unprotected = _open_risk(info, positions, equity)
    streak = _loss_streak(mt5, now, magic)
    plan_risk = _plan_risk(info, strategy, equity)
    blocks = _risk_blocks(len(positions), daily, equity, peak, streak, open_risk, unprotected, plan_risk, limits)
    if any(int(getattr(position, "magic", 0) or 0) == magic for position in positions):
        blocks.append(f"agent {label} đang có lệnh mở, mỗi agent chỉ giữ một lệnh")
    coord_blocks = _coordinator_blocks(strategy, positions, info, equity, limits, plan_risk) if AGENT_MODE else []
    coord_blocks += _manager_block(state, key, closed_bar)
    blocks += coord_blocks
    if lock_text:
        blocks.append(lock_text)
    if state.get("emergency"):
        blocks.append("dừng khẩn cấp")
    if _spread_price(tick) > 0.8:
        blocks.append("chênh lệch quá rộng")
    age = now - (closed_bar + seconds)
    if age > SEND_WINDOW_SECONDS:
        blocks.append(f"nến đã đóng {age // 60} phút {age % 60} giây trước, không vào lệnh trễ")
    reason = (
        f"{LIVE_MARK}. Agent {label}. Nến {candle} đã đóng. {_manager_note(state, key, closed_bar)}{strategy['reason']} "
    )
    sent = False
    claude = None
    if blocks:
        reason += "Không gửi lệnh: " + ", ".join(blocks) + "."
    else:
        gate = _claude_gate(key, strategy, rates, closed_bar, timeframe, symbol, positions, state, equity, info, limits)
        claude = _gate_brief(gate)
        reason += _gate_text(gate) + " "
        if gate is not None and gate["decision"] == "bỏ":
            _record_veto(key, strategy, closed_bar, timeframe, gate)
        else:
            tick = _fresh_tick(mt5, symbol, tick, gate)
            use = factor * (gate["factor"] if gate is not None else 1.0)
            sent, note, detail = _send_order(mt5, info, tick, symbol, strategy, equity, limits, use, magic, timeframe)
            if sent:
                reason += f"Đã gửi {note}."
                book["lastSentBar"] = closed_bar
                book["maxBars"] = int(strategy.get("maxBars") or 0) or None
                book["manage"] = str(strategy.get("manage") or "fixed")
                _write_state(state)
                _journal_open(symbol, strategy, {**detail, "score": None, "size_factor": use, "agent": key}, closed_bar, equity, reason, timeframe)
                _gate_journal(detail, gate, key)
            else:
                reason += "Không gửi được lệnh: " + note + "."
    if book.get("note"):
        reason += " " + str(book.pop("note"))
    decision = {
        "action": ("MUA" if strategy["side"] == "buy" else "BÁN") if sent else "CHỜ",
        "reason": reason,
        "ready": sent,
        "sent": sent,
        "candle": candle,
        "strategy": label,
        "riskPass": not blocks,
        "symbol": symbol,
        "scores": _gate_lines(strategy, allowed) + [f"Agent {label}: khối lượng x{factor:g}"],
        "points": _points(strategy, allowed),
        "gates": strategy.get("gates") or [],
        "signal": True,
        "side": strategy.get("side"),
        "blocks": {"coordinator": list(coord_blocks), "risk": [item for item in blocks if item not in coord_blocks]},
        "claude": claude,
    }
    book["last"] = decision
    history = state.get("history") if isinstance(state.get("history"), list) else []
    state["history"] = [decision, *history][:12]


def _agent_card(selected: dict[str, object], strategy_id: str) -> dict[str, object]:
    """The card of one strategy from the full catalog, shaped like the selector's payload, so an
    agent acts on its own strategy whatever the priority selector picked."""
    catalog = selected.get("catalog") if isinstance(selected.get("catalog"), list) else []
    card = next((item for item in catalog if isinstance(item, dict) and item.get("id") == strategy_id), None)
    if card is None:
        return {**selected, "confirmed": False, "side": "wait", "reason": "Chưa đủ nến để chấm."}
    return {**card, "reason": str(card.get("summary") or ""), "timeframe": selected.get("timeframe"),
            "higherTimeframe": selected.get("higherTimeframe"), "facts": selected.get("facts"), "catalog": catalog}


def _agents_view(
    state: dict[str, object], positions: list[object], info: object, equity: float, limits: dict[str, float | int], strategy: dict[str, object] | None = None
) -> dict[str, object]:
    """What the coordinator sees: every agent with its share, last decision, open position and
    closed-trade record, plus the summed open risk of the account."""
    from services.api import agents as crew

    try:
        records = journal.agent_stats()
        costs = journal.llm_costs()
    except OSError:
        records, costs = {}, {}
    try:
        from services.api import llm_judge

        llm_on = llm_judge.enabled()
    except OSError:
        llm_on = False
    books = state.get("books") if isinstance(state.get("books"), dict) else {}
    main = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    books_all = all_books()
    configs = {key: config for key, config in books_all.items() if agent_real(key)}
    share = round(1 / max(len(configs), 1), 4)
    rows = []
    total = 0.0
    for key, config in configs.items():
        magic = int(config["magic"])
        held = [position for position in positions if int(getattr(position, "magic", 0) or 0) == magic]
        risk = sum(_position_risk(info, position, equity) for position in held) if info is not None else 0.0
        total += risk
        last = main if key == "trend-M15" else (books.get(key, {}) or {}).get("last") or {}
        known = crew._known(key)
        gates = _agent_gates(key, strategy, last)
        decision_reason = str(last.get("reason") or "")
        rows.append({
            "why": crew.profile(key).get("why", ""),
            "rule": crew.profile(key).get("rule", ""),
            "gates": gates,
            "activity": _activity(held, last, gates, decision_reason),
            "stages": _agent_stages(gates, last),
            "tested": crew.TESTED.get(key),
            "strategy": str((config.get("strategies") or ("",))[0]),
            "walkForward": _method_tested(str((config.get("strategies") or ("",))[0]), key) if key not in crew.TESTED else None,
            "real": True,
            "method": crew.method_rules(key),
            "id": key,
            "name": key if known is None else str(known["name"]),
            "alias": crew.alias(key),
            "timeframe": config.get("timeframe"),
            "magic": magic,
            "status": "thật",
            "share": share,
            "budget": round(equity * share, 2),
            "decision": {
                "candle": last.get("candle") or "",
                "action": last.get("action") or "CHỜ",
                "reason": str(last.get("reason") or ""),
                "points": last.get("points") or "",
                "sent": bool(last.get("sent")),
            },
            "positions": [
                {
                    "ticket": int(position.ticket),
                    "side": "Mua" if int(position.type) == 0 else "Bán",
                    "volume": float(position.volume),
                    "open": float(position.price_open),
                    "sl": float(getattr(position, "sl", 0) or 0),
                    "profit": round(float(getattr(position, "profit", 0) or 0), 2),
                }
                for position in held
            ],
            "openRisk": round(risk, 2),
            "llm": (costs.get("agents") or {}).get(key) or {"calls": 0, "cost": 0.0, "averageCost": None, "averageSeconds": None},
            "record": records.get(key) or {"closed": 0, "open": 0, "net": 0.0, "totalR": 0.0, "averageR": None, "winRate": None, "profitFactor": None},
        })
    research = {key: config for key, config in books_all.items() if key not in configs}
    paper = [crew.label(key) for key in research]
    catalog = strategy.get("catalog") if isinstance(strategy, dict) and isinstance(strategy.get("catalog"), list) else []
    lab = []
    for key, config in research.items():
        known = crew._known(key) or {}
        strategy_id = str((config.get("strategies") or ("",))[0])
        last = main if key == "trend-M15" else (books.get(key, {}) or {}).get("last") or {}
        card = None
        if str(config.get("timeframe")) == LIVE_TIMEFRAME:
            card = next((item for item in catalog if isinstance(item, dict) and item.get("id") == strategy_id), None)
        gates = list(card.get("gates") or []) if card is not None else list(last.get("gates") or [])
        side = card.get("side") if card is not None else last.get("side")
        seen = (bool(card.get("confirmed")) if card is not None else bool(last.get("signal"))) and side in {"buy", "sell"}
        summary = str(card.get("summary") or "") if card is not None else str(last.get("reason") or "")
        held = [position for position in positions if int(getattr(position, "magic", 0) or 0) == int(config["magic"])]
        lab.append({
            "id": key,
            "alias": crew.alias(key) or key,
            "name": str(known.get("name") or config.get("name") or key),
            "timeframe": config.get("timeframe"),
            "magic": int(config["magic"]),
            "why": crew.profile(key).get("why", ""),
            "rule": crew.profile(key).get("rule", ""),
            "family": known.get("family") or "",
            "stage": "paper",
            "isMethod": "family" in known,
            "strategy": strategy_id,
            "tested": _method_tested(strategy_id, key) if "family" in known or key not in crew.TESTED else None,
            "gates": gates,
            "method": crew.method_rules(key),
            "signal": ("Mua" if side == "buy" else "Bán") if seen else "",
            "summary": summary,
            "reason": "" if card is None else str(card.get("reason") or ""),
            "real": False,
            "holding": len(held),
            "activity": (f"Còn {len(held)} lệnh thật mở từ trước, vẫn được quản lý tới khi đóng. " if held else "")
            + (("Thấy tín hiệu " + ("mua" if side == "buy" else "bán") + ", chỉ ghi lệnh giấy, không gửi lệnh thật.") if seen
               else ("Đang quan sát: " + (summary or "chưa có tín hiệu.")) if (card is not None or last) else "Đang chờ nến đóng."),
        })
    stars = _star_ratings(records, [str(row["id"]) for row in rows] + [str(entry["id"]) for entry in lab])
    for entry in [*rows, *lab]:
        record = records.get(str(entry["id"])) or {}
        entry["stars"] = stars.get(str(entry["id"]), 0)
        entry["trades"] = int(record.get("closed") or 0) + int(record.get("open") or 0)
        entry["net"] = float(record.get("net") or 0)
    notes = [str(row["decision"]["reason"]) for row in rows]
    conflicts = [text for text in notes if "đang lãi, không vào ngược" in text or "tổng rủi ro các lệnh đang mở" in text]
    holding = [row for row in rows if row["positions"]]
    review = (state.get("manager") or {}).get("last") if isinstance(state.get("manager"), dict) else None
    recent = isinstance(review, dict) and time.time() - float(review.get("at") or 0) < 20 * 60 and review.get("lines")
    if recent:
        boss = " ".join(str(line) for line in review["lines"][:3])
    elif conflicts:
        boss = "Vừa chặn một lệnh: " + conflicts[0].split("Không gửi lệnh:")[-1].strip()
    elif holding:
        boss = f"Đang giám sát {len(holding)} lệnh mở của " + ", ".join(row["alias"] for row in holding) + f". Tổng rủi ro mở {total:.2f}%."
    else:
        boss = "Chưa có lệnh mở. Đang chờ các agent báo tín hiệu, sẵn sàng kiểm tra luật chung trước khi cho vào lệnh."
    return {
        "mode": AGENT_MODE,
        "coordinator": crew.COORDINATOR,
        "coordinatorWhy": crew.COORDINATOR_WHY,
        "coordinatorActivity": boss,
        "llm": {**costs, "enabled": llm_on},
        "lab": lab,
        "agents": rows,
        "openRisk": round(total, 2),
        "openRiskCap": float(limits.get("maxOpenRiskPercent") or 6),
        "rules": [
            "Mỗi agent một chiến lược, một mã sổ, tối đa một lệnh; vốn chia đều.",
            "Nhiều agent báo tín hiệu cùng lúc: trưởng phòng chỉ duyệt agent có lợi thế kiểm thử cao nhất (điều chỉnh dần theo kết quả thật); không mở mua và bán cùng lúc. Tín hiệu ở thời điểm khác vẫn được vào lệnh.",
            "Được vào cùng chiều với agent khác.",
            "Không vào ngược chiều khi lệnh của agent khác đang lãi; được vào khi lệnh đó đang lỗ (lệnh cũ giữ nguyên).",
            f"Tổng rủi ro các lệnh đang mở tối đa {float(limits.get('maxOpenRiskPercent') or 6):g}% vốn; lỗ ngày và khóa sụt giảm {float(limits.get('drawdownPercent') or 30):g}% dùng chung.",
            "Mỗi agent tự nghỉ hết ngày sau chuỗi thua của chính nó.",
            "Tín hiệu qua đủ quy tắc và cổng rủi ro được đưa cho Claude (chuyên gia theo đúng phương pháp của agent) quyết định cuối: vào đủ, giảm nửa khối lượng, hoặc bỏ. Claude không trả lời trong 40 giây thì làm theo quy tắc.",
        ],
        "paper": paper,
    }


def _star_ratings(records: dict[str, dict[str, object]], keys: list[str]) -> dict[str, int]:
    """Stars 0-5 from closed real trades, by net profit: agents in profit get 3-5 (the most
    profitable 5), agents at a loss or flat 1-2 (the smallest loss 2), no closed trade 0."""
    ranked = [(key, float((records.get(key) or {}).get("net") or 0)) for key in keys if int((records.get(key) or {}).get("closed") or 0) > 0]
    stars = {key: 0 for key in keys}
    for group, top, bottom in (([item for item in ranked if item[1] > 0], 5, 3), ([item for item in ranked if item[1] <= 0], 2, 1)):
        group.sort(key=lambda item: -item[1])
        for index, (key, _net) in enumerate(group):
            stars[key] = top if len(group) == 1 else round(top - (top - bottom) * index / (len(group) - 1))
    return stars


def _agent_gates(key: str, strategy: dict[str, object] | None, last: dict[str, object]) -> list[dict[str, str]]:
    """Entry conditions of an agent on its last closed bar."""
    stored = last.get("gates") if isinstance(last.get("gates"), list) else None
    if key == "trend-M30":
        return stored or []
    wanted = {"trend-M15": "trend", "pullback-M15": "pullback"}.get(key)
    catalog = strategy.get("catalog") if isinstance(strategy, dict) and isinstance(strategy.get("catalog"), list) else []
    card = next((item for item in catalog if isinstance(item, dict) and item.get("id") == wanted), None)
    if card is not None and card.get("gates"):
        return list(card["gates"])
    return stored or []


def _activity(held: list[object], last: dict[str, object], gates: list[dict[str, str]], reason: str) -> dict[str, str]:
    """What the agent is doing right now, in one line, with a state for the badge."""
    if held:
        position = held[0]
        side = "mua" if int(position.type) == 0 else "bán"
        profit = float(getattr(position, "profit", 0) or 0)
        return {"state": "holding", "label": "Đang giữ lệnh", "text": f"Đang giữ lệnh {side} {float(position.volume):g} lot, {'lãi' if profit >= 0 else 'lỗ'} {abs(profit):.2f} $."}
    if last.get("sent"):
        return {"state": "sent", "label": "Vừa vào lệnh", "text": "Vừa gửi lệnh ở nến " + str(last.get("candle") or "") + "."}
    if "Không gửi lệnh:" in reason and all(gate.get("state") != "fail" for gate in gates) and gates:
        return {"state": "blocked", "label": "Bị chặn", "text": "Có tín hiệu nhưng bị chặn: " + reason.split("Không gửi lệnh:")[-1].strip()}
    failed = next((gate for gate in gates if gate.get("state") == "fail"), None)
    if failed is not None:
        return {"state": "waiting", "label": "Đang chờ", "text": "Đang chờ điều kiện: " + str(failed["name"]) + "."}
    return {"state": "idle", "label": "Đang theo dõi", "text": "Đang theo dõi thị trường, chờ nến đóng tiếp theo."}


def _position_risk(info: object, position: object, equity: float) -> float:
    tick_size = float(getattr(info, "trade_tick_size", 0) or 0)
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    stop = float(getattr(position, "sl", 0) or 0)
    if equity <= 0 or tick_size <= 0 or tick_value <= 0 or stop <= 0:
        return 0.0
    distance = abs(float(position.price_open) - stop)
    buy = int(position.type) == 0
    # a stop already past the entry (trailing) locks profit: no risk left
    if (buy and stop >= float(position.price_open)) or (not buy and stop <= float(position.price_open)):
        return 0.0
    return distance / tick_size * tick_value * float(position.volume) / equity * 100


# Trưởng phòng ranks agents that signal on the same closed bar by their tested edge (average R per
# trade, the weaker walk-forward period when there are two), pulled toward their real results as
# closed trades build up (MANAGER_PRIOR_TRADES real trades weigh as much as the backtest).
MANAGER_PRIOR_TRADES = 40
# Agents without a walk-forward entry elsewhere: trend-H4 (2022-24 / 2025-26 in the EXTRA_BOOKS
# note), breakout / reversal / range from the 2025-06..2026-11 backtest dump (2026-11-11).
# One-period dumps are shrunk toward 0 by n/(n+100): breakout 73 trades +0.173R, reversal 958 +0.007R, range 4 +0.625R.
MANAGER_EDGE = {"trend-H4": 0.131, "breakout-M15": 0.073, "reversal-M15": 0.006, "range-M15": 0.024}


def _agent_edge(key: str, config: dict[str, object]) -> float:
    from services.api import agents as crew

    if key in MANAGER_EDGE:
        return float(MANAGER_EDGE[key])
    if key in crew.TESTED:
        return float(crew.TESTED[key]["averageR"])
    tested = _method_tested(str((config.get("strategies") or ("",))[0]), key)
    values = [float(period["averageR"]) for period in ((tested or {}).get("periods") or {}).values() if period.get("averageR") is not None]
    return min(values) if values else 0.0


def _manager_score(key: str, config: dict[str, object], records: dict[str, dict[str, object]]) -> tuple[float, float, int]:
    edge = _agent_edge(key, config)
    record = records.get(key) or {}
    closed = int(record.get("closed") or 0)
    score = (MANAGER_PRIOR_TRADES * edge + float(record.get("totalR") or 0)) / (MANAGER_PRIOR_TRADES + closed)
    return score, edge, closed


def _side_word(side: object) -> str:
    return "mua" if side == "buy" else "bán"


def _manager_review(mt5: object, state: dict[str, object], symbol: str, tick: object, limits: dict[str, float | int], positions: list[object]) -> None:
    """Trưởng phòng, once per newly closed bar of each real agent: gather every agent that signals
    now, let only the best suited one open (one new trade per moment, never one buy and one sell at
    the same time). Signals at other moments are each allowed (user, 2026-11-11: an agent whose own
    signal comes later on the same side still trades, so its record shows whether it is right)."""
    manager = state.get("manager") if isinstance(state.get("manager"), dict) else {}
    state["manager"] = manager
    seen = manager.get("seen") if isinstance(manager.get("seen"), dict) else {}
    verdicts = manager.get("verdicts") if isinstance(manager.get("verdicts"), dict) else {}
    manager["seen"], manager["verdicts"] = seen, verdicts
    books_state = state.get("books") if isinstance(state.get("books"), dict) else {}
    now = int(tick.time)
    frames: dict[str, object] = {}
    candidates = []
    records = None
    for key, config in all_books().items():
        if not agent_real(key):
            continue
        timeframe, seconds, magic = str(config["timeframe"]), int(config["seconds"]), int(config["magic"])
        if timeframe not in frames:
            frames[timeframe] = mt5.copy_rates_from_pos(symbol, int(getattr(mt5, "TIMEFRAME_" + timeframe)), 0, LIVE_BARS)
        rates = frames[timeframe]
        if rates is None or len(rates) < 30:
            continue
        closed_bar, _ = _schedule(rates, now, seconds)
        if seen.get(key) == closed_bar or now - (closed_bar + seconds) > SEND_WINDOW_SECONDS:
            continue
        seen[key] = closed_bar
        done = state.get("lastBar") if key == "trend-M15" else (books_state.get(key) or {}).get("lastBar")
        if done == closed_bar or any(int(getattr(position, "magic", 0) or 0) == magic for position in positions):
            continue  # already decided, or holds its own trade (its own rule stops it)
        allowed = tuple(config.get("strategies") or ("trend",))
        card = _agent_card(_strategy_for(rates, closed_bar, float(limits["minRewardRatio"]), timeframe, seconds), allowed[0])
        if not (card.get("confirmed") and card.get("side") in {"buy", "sell"}):
            continue
        if records is None:
            records = journal.agent_stats()
        score, edge, closed = _manager_score(key, config, records)
        candidates.append({"key": key, "label": str(config.get("name") or key), "side": card["side"], "bar": closed_bar,
                           "score": score, "edge": edge, "closed": closed, "seconds": seconds})
    if not candidates:
        return
    candidates.sort(key=lambda item: (-item["score"], -item["seconds"]))
    lines = []
    winner = None
    for item in candidates:
        side_word = _side_word(item["side"])
        if winner is None:
            winner = item
            rivals = [other for other in candidates if other is not item]
            note = f"trưởng phòng chọn {item['label']} (lợi thế {item['score']:+.2f}R/lệnh"
            note += (", hơn " + ", ".join(f"{other['label']} {other['score']:+.2f}R" for other in rivals) + ")") if rivals else ")"
            verdicts[item["key"]] = {"bar": item["bar"], "ok": True, "note": note}
            lines.insert(0, note[0].upper() + note[1:] + f" cho lệnh {side_word}.")
        else:
            same = winner["side"] == item["side"]
            why = f"không mở hai lệnh {side_word} cùng lúc" if same else "không mở mua và bán cùng lúc"
            note = f"trưởng phòng chọn {winner['label']} ({winner['score']:+.2f}R/lệnh) thay vì agent này ({item['score']:+.2f}R): {why}"
            verdicts[item["key"]] = {"bar": item["bar"], "ok": False, "note": note}
            lines.append(f"{item['label']}: {note}.")
    manager["last"] = {"time": now, "at": time.time(), "lines": lines}
    _LOG.info("manager: %s", " | ".join(lines))
    try:
        journal.log_manager("arbitration", " ".join(lines), {"bar": datetime.fromtimestamp(candidates[0]["bar"], timezone.utc).strftime("%d/%m %H:%M UTC"), "candidates": candidates})
    except Exception as error:  # noqa: BLE001
        _LOG.warning("manager log: %s", error)


def _manager_block(state: dict[str, object], key: str, closed_bar: int) -> list[str]:
    verdict = ((state.get("manager") or {}).get("verdicts") or {}).get(key) if isinstance(state.get("manager"), dict) else None
    if isinstance(verdict, dict) and verdict.get("bar") == closed_bar and not verdict.get("ok"):
        return [str(verdict.get("note") or "trưởng phòng không duyệt")]
    return []


def _manager_note(state: dict[str, object], key: str, closed_bar: int) -> str:
    verdict = ((state.get("manager") or {}).get("verdicts") or {}).get(key) if isinstance(state.get("manager"), dict) else None
    if isinstance(verdict, dict) and verdict.get("bar") == closed_bar and verdict.get("ok"):
        text = str(verdict.get("note") or "")
        return text[0].upper() + text[1:] + ". " if text else ""
    return ""


def _coordinator_blocks(
    strategy: dict[str, object], positions: list[object], info: object, equity: float, limits: dict[str, float | int], plan_risk: float | None
) -> list[str]:
    """Agent-coordinator rules on top of the account risk gates: never open against a position
    of another agent that is in profit (against a losing one is allowed, it stays open), and keep
    the summed risk of all open agent positions within maxOpenRiskPercent."""
    side = strategy.get("side")
    if side not in {"buy", "sell"}:
        return []
    blocks = []
    ours = [position for position in positions if int(getattr(position, "magic", 0) or 0) in AGENT_MAGICS]
    winners = [
        position for position in ours
        if ("buy" if int(position.type) == 0 else "sell") != side and float(getattr(position, "profit", 0) or 0) >= 0
    ]
    if winners:
        blocks.append(f"lệnh ngược chiều {int(winners[0].ticket)} của agent khác đang lãi, không vào ngược")
    cap = float(limits.get("maxOpenRiskPercent") or 6)
    total = sum(_position_risk(info, position, equity) for position in ours)
    own = plan_risk if plan_risk is not None else float(limits["perTradePercent"])
    planned = max(min(own, float(limits.get("minLotPercent") or 0)), float(limits["perTradePercent"])) if plan_risk is not None else own
    if total + planned > cap + 0.01:
        blocks.append(f"tổng rủi ro các lệnh đang mở {total:.2f}% + lệnh mới {planned:.2f}% vượt {cap:g}%")
    return blocks


def _claude_gate(
    agent_id: str, strategy: dict[str, object], rates: object, closed_bar: int, timeframe: str, symbol: str,
    positions: list[object], state: dict[str, object], equity: float, info: object, limits: dict[str, float | int],
) -> dict[str, object] | None:
    """Claude's final say (vào / giảm / bỏ) on a signal that passed the rules and the risk gates,
    asked as the expert of this agent's method with the whole desk in view. None = no answer:
    the tested rules decide."""
    try:
        from services.api import agents as crew, llm_judge
        from services.api.chart_analysis import _atr

        rows = [row for row in rates if int(row["time"]) <= closed_bar][-40:]
        bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rows]
        atr = next((value for value in reversed(_atr(bars, 14)) if value is not None), None)
        facts = strategy.get("facts") if isinstance(strategy.get("facts"), dict) else {}
        office = _office_lines(agent_id, positions, state, equity, info, limits, strategy)
        context = {
            "agent": crew.label(agent_id), "agentId": agent_id, "side": strategy.get("side"), "symbol": symbol, "timeframe": timeframe,
            "entry": strategy.get("entry"), "stop": strategy.get("stop"), "take": strategy.get("takeProfit"),
            "atr": None if atr is None else round(float(atr), 2), "hour": datetime.fromtimestamp(closed_bar + _frame_seconds(timeframe), timezone.utc).hour,
            "higher": {"up": "tăng", "down": "giảm"}.get(str(facts.get("higherBias")), str(facts.get("higherBias") or "không rõ")),
            "gates": strategy.get("gates") or [], "office": office,
            "persona": _persona(agent_id),
            "bars": [[datetime.fromtimestamp(int(row["time"]), timezone.utc).strftime("%d/%m %H:%M"), *bar] for row, bar in zip(rows, bars)],
        }
        return llm_judge.decide(context)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        _LOG.warning("claude gate %s: %s", agent_id, error)
        return None


def _frame_seconds(timeframe: str) -> int:
    from services.api.strategies import TF_SECONDS

    return int(TF_SECONDS.get(timeframe, 900))


def _persona(agent_id: str) -> str:
    """Expert role for an agent that has no hand-written persona in llm_judge."""
    from services.api import agents as crew

    found = crew.profile(agent_id)
    if not found:
        return ""
    return (f"Bạn là chuyên gia giao dịch theo phương pháp của {crew.label(agent_id)}. {found.get('why', '')} "
            f"Luật của agent: {found.get('rule', '')} Bạn đánh giá tín hiệu có đúng bản chất phương pháp này không. ")


def _office_lines(
    agent_id: str, positions: list[object], state: dict[str, object], equity: float, info: object, limits: dict[str, float | int], strategy: dict[str, object]
) -> list[str]:
    """The desk as the coordinator sees it, in short lines for the prompt."""
    from services.api import agents as crew

    names = {MAGIC: "trend-M15", **{int(config["magic"]): key for key, config in EXTRA_BOOKS.items()}}
    lines = []
    for position in positions:
        owner = names.get(int(getattr(position, "magic", 0) or 0))
        who = crew.label(owner) if owner else "lệnh tay / ngoài bot"
        side = "MUA" if int(position.type) == 0 else "BÁN"
        lines.append(
            f"Lệnh đang mở của {who}: {side} {float(position.volume):g} lot @ {float(position.price_open):.2f}, cắt lỗ {float(getattr(position, 'sl', 0) or 0):.2f}, "
            f"{'lãi' if float(getattr(position, 'profit', 0) or 0) >= 0 else 'lỗ'} {abs(float(getattr(position, 'profit', 0) or 0)):.2f} $"
        )
    if not positions:
        lines.append("Phòng chưa có lệnh nào đang mở.")
    books = state.get("books") if isinstance(state.get("books"), dict) else {}
    for key in ("trend-M15", *EXTRA_BOOKS.keys()):
        if key == agent_id:
            continue
        last = state.get("decision") if key == "trend-M15" else (books.get(key) or {}).get("last")
        if isinstance(last, dict) and last:
            lines.append(f"{crew.label(key)} ở nến {last.get('candle', '')}: {last.get('action', 'CHỜ')}, điều kiện {last.get('points', '—')}")
    catalog = strategy.get("catalog") if isinstance(strategy.get("catalog"), list) else []
    for config in crew.lab_agents():
        if config.get("status") == "draft":
            continue
        card = next((item for item in catalog if isinstance(item, dict) and item.get("id") == config["strategy"]), None)
        if card is not None:
            lines.append(f"{config['alias']} (phòng nghiên cứu, lệnh giấy): {card.get('summary')}")
    total = sum(_position_risk(info, position, equity) for position in positions) if info is not None else 0.0
    lines.append(f"Vốn {equity:.2f}, tổng rủi ro đang mở {total:.2f}% / tối đa {float(limits.get('maxOpenRiskPercent') or 6):g}%")
    return lines


def _fresh_tick(mt5: object, symbol: str, tick: object, gate: dict[str, object] | None) -> object:
    """After Claude answered (seconds later) price the order from a new quote."""
    reader = getattr(mt5, "symbol_info_tick", None)
    if gate is None or reader is None:
        return tick
    try:
        return reader(symbol) or tick
    except (OSError, RuntimeError):
        return tick


def _has_signal(strategy: dict[str, object]) -> bool:
    return bool(strategy.get("live") and strategy.get("confirmed") and strategy.get("side") in {"buy", "sell"})


def _gate_brief(gate: dict[str, object] | None) -> dict[str, object]:
    """Claude's answer as stored on the decision (for the per-agent stage view)."""
    if gate is None:
        return {"decision": "rules", "reason": "Claude không trả lời (đang tắt, lỗi hoặc quá 40 giây), làm theo quy tắc."}
    meta = gate.get("meta") if isinstance(gate.get("meta"), dict) else {}
    return {"decision": gate["decision"], "reason": str(gate.get("reason") or ""), "cost": meta.get("cost"),
            "seconds": None if meta.get("ms") is None else round(float(meta["ms"]) / 1000, 1)}


def _agent_stages(gates: list[dict[str, str]], last: dict[str, object]) -> list[dict[str, str]]:
    """Where the agent's last closed bar stopped: method -> coordinator -> risk gates -> Claude -> order.
    state: ok / fail / warn / wait (not reached yet or no signal)."""
    signal = bool(last.get("signal"))
    blocks = last.get("blocks") if isinstance(last.get("blocks"), dict) else {}
    coord = [str(item) for item in blocks.get("coordinator") or []]
    risk = [str(item) for item in blocks.get("risk") or []]
    claude = last.get("claude") if isinstance(last.get("claude"), dict) else None
    sent = bool(last.get("sent"))
    side = {"buy": "MUA", "sell": "BÁN"}.get(str(last.get("side")), "")
    counted = [gate for gate in gates if gate.get("state") != "skip"]
    failed = next((gate for gate in counted if gate.get("state") == "fail"), None)
    passed = sum(1 for gate in counted if gate.get("state") == "ok")
    if signal:
        method = {"state": "ok", "text": f"Đủ điều kiện, tín hiệu {side}".strip()}
    elif failed is not None:
        method = {"state": "wait", "text": f"Chưa đạt: {failed.get('name')} ({passed}/{len(counted)})"}
    else:
        method = {"state": "wait", "text": f"Chưa có tín hiệu ({passed}/{len(counted)})" if counted else "Chưa chấm nến nào"}
    idle = {"state": "wait", "text": "—"}
    if not signal:
        stage_coord, stage_risk, stage_claude, stage_send = idle, idle, idle, idle
    else:
        stage_coord = {"state": "fail", "text": "; ".join(coord)} if coord else {"state": "ok", "text": "Cho phép"}
        stage_risk = {"state": "fail", "text": "; ".join(risk)} if risk else {"state": "ok", "text": "Trong giới hạn"}
        if coord or risk:
            stage_claude, stage_send = idle, {"state": "fail", "text": "Không gửi"}
        else:
            word = {"vào": ("ok", "VÀO đủ khối lượng"), "giảm": ("warn", "GIẢM nửa khối lượng"), "bỏ": ("fail", "BỎ tín hiệu"),
                    "rules": ("warn", "Không trả lời, theo quy tắc")}
            if claude is None:
                stage_claude = {"state": "wait", "text": "Không hỏi (nến đã xử lý)"}
            else:
                state, label = word.get(str(claude.get("decision")), ("warn", str(claude.get("decision"))))
                extra = (f" · ${float(claude['cost']):.3f}" if claude.get("cost") else "") + (f" · {claude['seconds']} giây" if claude.get("seconds") else "")
                stage_claude = {"state": state, "text": label + extra, "detail": str(claude.get("reason") or "")}
            if sent:
                stage_send = {"state": "ok", "text": "Đã gửi lệnh"}
            elif claude is not None and claude.get("decision") == "bỏ":
                stage_send = {"state": "fail", "text": "Không gửi (Claude bỏ)"}
            else:
                stage_send = {"state": "fail", "text": "Không gửi được"}
    return [
        {"key": "method", "name": "Phương pháp", **method},
        {"key": "coordinator", "name": "Agent tổng", **stage_coord},
        {"key": "risk", "name": "Cổng rủi ro", **stage_risk},
        {"key": "claude", "name": "Claude", **stage_claude},
        {"key": "send", "name": "Gửi lệnh", **stage_send},
    ]


def _gate_text(gate: dict[str, object] | None) -> str:
    if gate is None:
        return "Claude không trả lời kịp, làm theo quy tắc."
    word = {"vào": "VÀO đủ khối lượng", "giảm": "GIẢM nửa khối lượng", "bỏ": "BỎ tín hiệu"}[str(gate["decision"])]
    return f"Claude quyết định {word}: {gate['reason']}"


def _record_veto(agent_id: str, strategy: dict[str, object], closed_bar: int, timeframe: str, gate: dict[str, object]) -> None:
    try:
        journal.record_veto(
            agent_id, closed_bar, timeframe, str(strategy.get("side")), float(strategy.get("entry") or 0), float(strategy.get("stop") or 0),
            strategy.get("takeProfit"), str(gate.get("reason") or ""), gate.get("meta"),
        )
    except (OSError, ValueError, TypeError) as error:
        _LOG.warning("veto: %s", error)


def _gate_journal(detail: dict[str, object], gate: dict[str, object] | None, agent_id: str) -> None:
    if gate is None or not detail.get("position"):
        return
    try:
        journal.set_llm(int(detail["position"]), str(gate["decision"]), str(gate["reason"]), gate.get("meta"), agent_id, log=False)
    except (OSError, ValueError, TypeError) as error:
        _LOG.warning("gate journal: %s", error)


def _judge(
    detail: dict[str, object], strategy: dict[str, object], rates: object, closed_bar: int, timeframe: str, symbol: str, agent_name: str, agent_id: str = ""
) -> None:
    """Ask Claude for a silent second opinion on a sent order (journal only, never blocks)."""
    try:
        from services.api import llm_judge
        from services.api.chart_analysis import _atr

        rows = [row for row in rates if int(row["time"]) <= closed_bar][-60:]
        bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rows]
        atr = next((value for value in reversed(_atr(bars, 14)) if value is not None), None)
        facts = strategy.get("facts") if isinstance(strategy.get("facts"), dict) else {}
        context = {
            "agent": agent_name, "agentId": agent_id, "side": strategy.get("side"), "symbol": symbol, "timeframe": timeframe,
            "entry": detail.get("fill"), "stop": detail.get("sl"), "take": detail.get("tp") or None,
            "atr": None if atr is None else round(float(atr), 2),
            "hour": datetime.fromtimestamp(closed_bar, timezone.utc).hour, "higher": facts.get("higherBias") or "không rõ",
            "gates": strategy.get("gates") or [],
            "bars": [[datetime.fromtimestamp(int(row["time"]), timezone.utc).strftime("%d/%m %H:%M"), *bar] for row, bar in zip(rows, bars)],
        }
        llm_judge.submit(int(detail["position"]), context)
    except (OSError, ValueError, KeyError, TypeError) as error:
        _LOG.warning("llm judge: %s", error)


TRAIL_ATR = 3.0


def _trail_positions(
    mt5: object,
    info: object,
    tick: object,
    symbol: str,
    rates: object,
    closed_bar: int,
    positions: list[object],
    magic: int = MAGIC,
    seconds: int = DECISION_SECONDS,
) -> list[str]:
    """Trailing stop of the live trend trade on TREND_TRAIL_FRAMES, the same rule as the backtest:
    walk the closed bars since the fill, keep the best price, and once it is 1R past the entry
    ratchet the stop to 3 ATR behind it. Recomputed from the bars each time, so a missed update
    is caught up on the next bar. If price has already gone through the new stop the position is
    closed at market, as the backtest exits at the next open."""
    from services.api.chart_analysis import _atr
    from services.api.strategies import TREND_TRAIL_FRAMES

    if (magic == MAGIC and LIVE_TIMEFRAME not in TREND_TRAIL_FRAMES) or info is None or tick is None or rates is None:
        return []
    rows = [row for row in rates if int(row["time"]) <= closed_bar]
    bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rows]
    opens = [int(row["time"]) for row in rows]
    if len(bars) < 20:
        return []
    atr = _atr(bars, 14)
    spread = _spread_price(tick)
    point = float(getattr(info, "point", 0) or 0.001)
    digits = int(getattr(info, "digits", 2) or 2)
    done = {int(mt5.TRADE_RETCODE_DONE), int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010))}
    notes: list[str] = []
    for position in positions:
        if int(getattr(position, "magic", 0) or 0) != magic or (magic == MAGIC and "pullback" in str(getattr(position, "comment", "") or "")):
            continue
        risk = journal.initial_risk(int(position.ticket))
        if not risk:
            continue
        buy = int(position.type) == 0
        entry = float(position.price_open)
        opened = int(getattr(position, "time", 0) or 0)
        stop = entry - risk if buy else entry + risk
        best = entry
        for index, moment in enumerate(opens):
            if moment + seconds <= opened or atr[index] is None:
                continue
            if buy:
                best = max(best, bars[index][1])
                if best - entry >= risk:
                    stop = max(stop, best - TRAIL_ATR * float(atr[index]))
            else:
                best = min(best, bars[index][2] + spread)
                if entry - best >= risk:
                    stop = min(stop, best + TRAIL_ATR * float(atr[index]))
        current = float(getattr(position, "sl", 0) or 0)
        better = stop > current + point if buy else (current <= 0 or stop < current - point)
        if not better:
            continue
        price = float(tick.bid if buy else tick.ask)
        crossed = stop >= price if buy else stop <= price
        if crossed:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "position": int(position.ticket),
                "volume": float(position.volume),
                "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                "price": price,
                "deviation": 50,
                "magic": magic,
                "comment": "GoldTrader cat lo bam",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": _filling(mt5, info),
            }
            label = f"Giá đã qua cắt lỗ bám {stop:.2f}, đóng vị thế {int(position.ticket)}"
        else:
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": symbol,
                "position": int(position.ticket),
                "sl": round(stop, digits),
                "tp": float(getattr(position, "tp", 0) or 0),
                "magic": magic,
            }
            label = f"Dời cắt lỗ vị thế {int(position.ticket)} từ {current:.2f} lên {stop:.2f}" if buy else f"Dời cắt lỗ vị thế {int(position.ticket)} từ {current:.2f} xuống {stop:.2f}"
        result = mt5.order_send(request)
        if result is not None and int(getattr(result, "retcode", 0)) in done:
            notes.append(label + ".")
        else:
            comment = "không có phản hồi" if result is None else str(getattr(result, "comment", None) or getattr(result, "retcode", ""))
            notes.append(f"{label} chưa được: {comment}.")
            _LOG.warning("trail %s: %s", int(position.ticket), comment)
    return notes
