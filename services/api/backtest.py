import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.api.settings_store import read_risk, read_settings

REPORT_PATH = Path(__file__).resolve().parents[2] / "data" / "backtest-latest.json"
TIMEFRAMES = ("M5", "M15", "M30", "H1", "H4")
STRATEGIES = {
    "auto": "Bot tự động",
    "agents": "Đa agent",
    "adaptive": "Theo phong độ",
    "trend": "Theo xu hướng",
    "pullback": "Hồi giá",
    "breakout": "Phá vùng",
    "reversal": "Đảo chiều",
    "range": "Đi ngang",
}
from services.api.methods import METHODS as _METHODS  # noqa: E402

STRATEGIES.update({method.id: f"{method.alias} · {method.label}" for method in _METHODS})
METHOD_IDS = frozenset(method.id for method in _METHODS)
BOOKS = ("trend", "pullback", "breakout", "reversal", "range")
MAX_BARS = 40000
TF_SECONDS = {"M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}


def latest_backtest() -> dict[str, object]:
    if not REPORT_PATH.exists():
        return {"ok": False, "message": "Chưa có lần kiểm thử nào."}
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report["ok"] = True
    return report


def run_backtest(strategy: str, timeframe: str, start: str, end: str, capital: float) -> dict[str, object]:
    if strategy not in STRATEGIES:
        raise ValueError("Chiến lược không có trong bộ kiểm thử.")
    if timeframe not in TIMEFRAMES:
        raise ValueError("Khung thời gian không được hỗ trợ.")
    start_day = _parse_day(start)
    end_day = _parse_day(end)
    if end_day < start_day:
        raise ValueError("Ngày kết thúc phải sau ngày bắt đầu.")
    if capital < 100 or capital > 1_000_000:
        raise ValueError("Vốn đầu cần từ 100 đến 1.000.000.")
    settings = read_settings()
    symbol = str(settings["symbol"] or "XAUUSDm")
    limits = read_risk()
    from services.api.live import AGENT_MODE, LIVE_TIMEFRAME

    # "Bot tự động" replays what live does: the multi-agent coordinator when it is on
    run_as = "agents" if strategy == "auto" and AGENT_MODE and timeframe == LIVE_TIMEFRAME else strategy
    bars, times, market = _history(symbol, timeframe, start_day, end_day, _book_warmup_frame(run_as, timeframe))
    report = _simulate(bars, times, market, run_as, timeframe, start_day, end_day, capital, limits)
    if run_as != strategy:
        report["strategy"] = STRATEGIES["auto"] + " (đa agent)"
    report["symbol"] = symbol
    report["message"] = str(report["message"]) + _model_note(timeframe)
    _save_report(report)
    return report


def run_compare(timeframe: str, start: str, end: str, capital: float) -> dict[str, object]:
    if timeframe not in TIMEFRAMES:
        raise ValueError("Khung thời gian không được hỗ trợ.")
    start_day = _parse_day(start)
    end_day = _parse_day(end)
    if end_day < start_day:
        raise ValueError("Ngày kết thúc phải sau ngày bắt đầu.")
    if capital < 100 or capital > 1_000_000:
        raise ValueError("Vốn đầu cần từ 100 đến 1.000.000.")
    settings = read_settings()
    symbol = str(settings["symbol"] or "XAUUSDm")
    limits = read_risk()
    bars, times, market = _history(symbol, timeframe, start_day, end_day)
    runs = _simulate_compare(bars, times, market, timeframe, start_day, end_day, capital, limits)
    for run in runs:
        run["symbol"] = symbol
    report = {
        "ok": True,
        "kind": "compare",
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start_day.strftime("%d/%m/%Y"),
        "end": end_day.strftime("%d/%m/%Y"),
        "capital": capital,
        "runs": runs,
        "message": "Đã chạy lần lượt năm chiến lược trên cùng một đoạn nến." + _model_note(timeframe),
    }
    _save_report(report)
    return report


def _save_report(report: dict[str, object]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _history(
    symbol: str, timeframe: str, start_day: datetime, end_day: datetime, warmup_frame: str | None = None
) -> tuple[list[tuple[float, float, float, float]], list[int], dict[str, float]]:
    try:
        return _history_terminal(symbol, timeframe, start_day, end_day, warmup_frame)
    except (RuntimeError, OSError):
        return _history_archive(symbol, timeframe, start_day, end_day, warmup_frame)


def _extra_books(strategy: str, timeframe: str) -> dict[str, dict[str, object]]:
    """Extra live books (live.EXTRA_BOOKS) replayed next to the main book, only for the live
    replica ("auto") on the live timeframe, whose bars are aggregated into the book's frame."""
    if strategy != "auto":
        return {}
    from services.api.live import EXTRA_BOOKS, LIVE_TIMEFRAME

    if timeframe != LIVE_TIMEFRAME:
        return {}
    base = TF_SECONDS.get(timeframe, 900)
    return {
        str(config.get("timeframe") or key): config
        for key, config in EXTRA_BOOKS.items()
        if int(config["seconds"]) > base and int(config["seconds"]) % base == 0
    }


def _book_warmup_frame(strategy: str, timeframe: str) -> str | None:
    if strategy == "agents":
        from services.api import agents

        frames = [str(config["timeframe"]) for config in agents.AGENTS if agents.FRAME_SECONDS[str(config["timeframe"])] > TF_SECONDS.get(timeframe, 900)]
        return max(frames, key=lambda frame: agents.FRAME_SECONDS[frame]) if frames else None
    books = _extra_books(strategy, timeframe)
    return max(books, key=lambda frame: int(books[frame]["seconds"])) if books else None


def _history_terminal(symbol: str, timeframe: str, start_day: datetime, end_day: datetime, warmup_frame: str | None = None) -> tuple[list[tuple[float, float, float, float]], list[int], dict[str, float]]:
    import MetaTrader5 as mt5

    from services.api.mt5_session import open_terminal

    frame = {
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
    }[timeframe]
    warmup = _warmup(start_day, warmup_frame or timeframe)
    end = end_day + timedelta(days=1)
    with open_terminal() as terminal:
        info = terminal.symbol_info(symbol)
        rates = terminal.copy_rates_range(symbol, frame, warmup, end)
    if info is None or rates is None or len(rates) < 80:
        raise RuntimeError("Chưa đủ nến lịch sử trong khoảng này.")
    if len(rates) > MAX_BARS + 1000:
        raise RuntimeError("Khoảng thời gian quá dài cho khung này. Hãy rút ngắn hoặc chọn khung lớn hơn.")
    point = float(info.point) or 0.001
    spread = max(float(info.spread) * point, point)
    market = {
        "spread": spread,
        "tickSize": float(info.trade_tick_size) or point,
        "tickValue": float(info.trade_tick_value) or 0.0,
        "volumeMin": float(info.volume_min) or 0.01,
        "volumeMax": float(info.volume_max) or 50.0,
        "volumeStep": float(info.volume_step) or 0.01,
        "swapLong": float(getattr(info, "swap_long", 0) or 0),
        "swapShort": float(getattr(info, "swap_short", 0) or 0),
        "swapMode": int(getattr(info, "swap_mode", 0) or 0),
        "point": point,
    }
    bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rates]
    times = [int(row["time"]) for row in rates]
    return bars, times, market


def _history_archive(symbol: str, timeframe: str, start_day: datetime, end_day: datetime, warmup_frame: str | None = None) -> tuple[list[tuple[float, float, float, float]], list[int], dict[str, float]]:
    from services.api.candle_store import load_candles

    payload = load_candles(symbol, timeframe)
    if payload is None:
        raise RuntimeError("MetaTrader không trả nến và chưa có kho nến đã lưu cho khung này.")
    warmup = int(_warmup(start_day, warmup_frame or timeframe).replace(tzinfo=timezone.utc).timestamp())
    end = int((end_day + timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp())
    rows = [row for row in payload["bars"] if isinstance(row, dict) and warmup <= int(row["time"]) < end]
    if len(rows) > MAX_BARS + 1000:
        raise RuntimeError("Khoảng thời gian quá dài cho khung này. Hãy rút ngắn hoặc chọn khung lớn hơn.")
    if len(rows) < 80:
        raise RuntimeError(
            f"Kho nến {timeframe} chỉ còn từ {payload.get('from')} đến {payload.get('to')}, không đủ cho khoảng ngày đã chọn."
        )
    market = {key: float(value) for key, value in dict(payload["market"]).items()}
    bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rows]
    times = [int(row["time"]) for row in rows]
    return bars, times, market


def _simulate(
    bars: list[tuple[float, float, float, float]],
    times: list[int],
    market: dict[str, float],
    strategy: str,
    timeframe: str,
    start_day: datetime,
    end_day: datetime,
    capital: float,
    limits: dict[str, float | int],
    edge_window: int = 6,
    edge_min: int = 4,
    skip_hours: tuple[int, ...] = (),
) -> dict[str, object]:
    from services.api.chart_analysis import _atr, _thresholds
    from services.api.meta_model import read_mode
    from services.api.strategies import WINDOW, evaluate_strategies

    model_mode = read_mode()
    start_ts = int(start_day.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int((end_day + timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp())
    reward_ratio = float(limits["minRewardRatio"])
    per_trade = float(limits["perTradePercent"]) / 100
    daily_limit = float(limits["dailyLossPercent"]) / 100
    drawdown_limit = float(limits["drawdownPercent"]) / 100
    loss_limit = int(limits["maxLossStreak"])
    spread = float(market["spread"])
    cash = capital
    peak = capital
    halted = False
    gate = _new_gate(capital)
    streak = 0
    pause_day = ""
    position: dict[str, float | int | str] | None = None
    day_key = ""
    day_start_equity = capital
    day_pnl = 0.0
    trades: list[dict[str, object]] = []
    equity_curve: list[float] = []
    drawdown_curve: list[float] = []
    taken = 0
    blocked = 0
    books = {name: {"position": None, "recent": [], "trades": []} for name in BOOKS}
    shadow_cash = capital
    shadow_position: dict[str, float | int | str] | None = None
    shadow_trades: list[dict[str, object]] = []
    shadow_peak = capital
    shadow_curve: list[float] = []
    shadow_drawdown: list[float] = []
    # What the live selector decided on every closed bar (strategy "auto" replays live exactly).
    decisions: dict[str, object] = {
        "bars": 0,
        "signals": {},
        "taken": 0,
        "blocked": {"analysis": 0, "filter": 0, "busy": 0, "risk": 0, "lock": 0, "volume": 0},
    }
    blocked_reasons = decisions["blocked"]
    picks = decisions["signals"]
    extra = {
        frame: {
            "seconds": int(config["seconds"]),
            "factor": float(config["factor"]),
            "strategies": tuple(config.get("strategies") or ("trend",)),
            "ratio": int(config["seconds"]) // TF_SECONDS.get(timeframe, 900),
            "bars": [],
            "times": [],
            "position": None,
            "streak": 0,
            "pause": "",
            "stats": {"bars": 0, "signals": 0, "taken": 0, "busy": 0, "risk": 0, "lock": 0, "volume": 0},
        }
        for frame, config in _extra_books(strategy, timeframe).items()
    }
    if extra:
        decisions["books"] = {frame: book["stats"] for frame, book in extra.items()}
    crew = _new_crew(timeframe) if strategy == "agents" else None
    if crew is not None:
        decisions["agents"] = {name: member["stats"] for name, member in crew["members"].items()}

    for index, bar in enumerate(bars):
        moment = times[index]
        in_range = start_ts <= moment < end_ts
        key = datetime.fromtimestamp(moment, timezone.utc).strftime("%Y-%m-%d")
        if in_range and key != day_key:
            day_key = key
            day_start_equity = (
                cash + _open_pnl(position, bar[0], market) + sum(_open_pnl(book["position"], bar[0], market) for book in extra.values()) + _crew_open_pnl(crew, bar[0], market)
            )
            day_pnl = 0.0
        context = None
        catalog = None
        if index >= 80:
            window = bars[max(0, index - WINDOW + 1) : index + 1]
            context = _context(window, timeframe)
            if index + 1 < len(bars):
                atr = _atr(window, 14)
                last_atr = next((value for value in reversed(atr) if value is not None), 1.0)
                support, resistance = _thresholds(window, last_atr)
                catalog = evaluate_strategies(
                    window,
                    timeframe,
                    support,
                    resistance,
                    spread,
                    reward_ratio,
                    times[max(0, index - WINDOW + 1) : index + 1],
                    _fill_hour(times[index + 1]),
                    methods=strategy in METHOD_IDS,
                )["catalog"]
                if model_mode == "size":
                    _attach_model(catalog, window, times[max(0, index - WINDOW + 1) : index + 1], timeframe, _fill_hour(times[index + 1]))
        if position is not None and index >= int(position["fillIndex"]):
            closed = _exit_position(position, bar, index, moment, market, index == len(bars) - 1, context)
            if closed is not None:
                cash += float(closed["pnl"])
                if in_range:
                    day_pnl += float(closed["pnl"])
                if float(closed["pnl"]) < 0:
                    streak += 1
                    if streak >= loss_limit:
                        pause_day = key
                else:
                    streak = 0
                trades.append(closed)
                position = None
        for frame, book in extra.items():
            held = book["position"]
            if held is None or index < int(held["fillIndex"]):
                continue
            closed = _exit_position(held, bar, index, moment, market, index == len(bars) - 1, None)
            if closed is None:
                continue
            closed = _book_trade(closed, book["ratio"], frame)
            cash += float(closed["pnl"])
            if in_range:
                day_pnl += float(closed["pnl"])
            # each book counts its own losing streak (live: _loss_streak by magic); the daily
            # loss limit and the drawdown lock stay shared by the account
            if float(closed["pnl"]) < 0:
                book["streak"] += 1
                if book["streak"] >= loss_limit:
                    book["pause"] = key
            else:
                book["streak"] = 0
            trades.append(closed)
            book["position"] = None
        if crew is not None:
            for closed in _crew_exits(crew, bar, index, moment, market, index == len(bars) - 1, key, loss_limit, per_trade, context):
                cash += float(closed["pnl"])
                if in_range:
                    day_pnl += float(closed["pnl"])
                trades.append(closed)
        if shadow_position is not None and index >= int(shadow_position["fillIndex"]):
            closed = _exit_position(shadow_position, bar, index, moment, market, index == len(bars) - 1, context)
            if closed is not None:
                shadow_cash += float(closed["pnl"])
                shadow_trades.append(closed)
                shadow_position = None
        if in_range:
            equity = (
                cash + _open_pnl(position, bar[3], market) + sum(_open_pnl(book["position"], bar[3], market) for book in extra.values()) + _crew_open_pnl(crew, bar[3], market)
            )
            peak = max(peak, equity)
            drawdown = 0.0 if peak <= 0 else (peak - equity) / peak
            equity_curve.append(round(equity, 2))
            drawdown_curve.append(round(drawdown * 100, 2))
            halted = _drawdown_gate(gate, equity, moment, drawdown_limit)
            shadow_equity = shadow_cash + _open_pnl(shadow_position, bar[3], market)
            shadow_peak = max(shadow_peak, shadow_equity)
            shadow_curve.append(round(shadow_equity, 2))
            shadow_drop = 0.0 if shadow_peak <= 0 else (shadow_peak - shadow_equity) / shadow_peak
            shadow_drawdown.append(round(shadow_drop * 100, 2))
        if catalog is not None and in_range:
            upcoming = None if index + 1 >= len(bars) else bars[index + 1]
            upcoming_time = 0 if upcoming is None else times[index + 1]
            for name, book in books.items():
                _advance_book(book, _pick(catalog, name), bar, index, moment, upcoming, upcoming_time, market, index == len(bars) - 1, context)
        if strategy == "auto" and catalog is not None and in_range and index + 1 < len(bars) and times[index + 1] < end_ts:
            decisions["bars"] = int(decisions["bars"]) + 1
            chosen = next((item for item in catalog if isinstance(item, dict) and item.get("chosen")), None)
            if chosen is not None and chosen.get("side") in {"buy", "sell"}:
                if chosen.get("confirmed"):
                    picks[str(chosen.get("id"))] = int(picks.get(str(chosen.get("id")), 0)) + 1
                    if not chosen.get("live"):
                        blocked_reasons["analysis"] += 1
                    elif position is not None:
                        blocked_reasons["busy"] += 1
                elif chosen.get("live") and chosen.get("status") == "blocked":
                    blocked_reasons["filter"] += 1
        for frame, book in extra.items():
            seconds = int(book["seconds"])
            group = moment // seconds * seconds
            if book["times"] and book["times"][-1] == group:
                o, h, l, _c = book["bars"][-1]
                book["bars"][-1] = (o, max(h, bar[1]), min(l, bar[2]), bar[3])
            else:
                book["bars"].append(bar)
                book["times"].append(group)
                if len(book["bars"]) > WINDOW + 50:
                    del book["bars"][0], book["times"][0]
            if index + 1 >= len(bars) or times[index + 1] // seconds * seconds == group:
                continue  # the book's bar is still forming
            if not in_range or times[index + 1] >= end_ts or len(book["bars"]) < 80:
                continue
            stats = book["stats"]
            stats["bars"] += 1
            frame_bars = book["bars"][-WINDOW:]
            frame_atr = _atr(frame_bars, 14)
            frame_last = next((value for value in reversed(frame_atr) if value is not None), 1.0)
            frame_low, frame_high = _thresholds(frame_bars, frame_last)
            found = evaluate_strategies(
                frame_bars, frame, frame_low, frame_high, spread, reward_ratio, book["times"][-WINDOW:], _fill_hour(times[index + 1]), methods=False
            )["catalog"]
            frame_signal = _pick(found, "auto")
            if frame_signal is None or frame_signal.get("id") not in book["strategies"]:
                continue
            stats["signals"] += 1
            if book["position"] is not None:
                stats["busy"] += 1
                continue
            if book["pause"] and key > book["pause"]:
                book["pause"] = ""
                book["streak"] = 0
            if book["pause"] == key or (day_start_equity > 0 and day_pnl <= -daily_limit * day_start_equity):
                stats["risk"] += 1
                continue
            if halted:
                stats["lock"] += 1
                continue
            frame_open = _open_position(frame_signal, bars[index + 1], index + 1, times[index + 1], cash, per_trade * float(book["factor"]), market)
            if frame_open is None:
                stats["volume"] += 1
                continue
            frame_open["name"] = f"{frame_open['name']} {frame}"
            frame_open["maxBars"] = int(frame_open["maxBars"]) * int(book["ratio"])
            book["position"] = frame_open
            stats["taken"] += 1
        if crew is not None:
            _crew_entries(
                crew, bars, times, index, moment, catalog, in_range and index + 1 < len(bars) and times[index + 1] < end_ts and index >= 80,
                key, cash, cash + _crew_open_pnl(crew, bar[3], market), per_trade, limits, market, spread, reward_ratio,
                day_start_equity > 0 and day_pnl <= -daily_limit * day_start_equity, halted,
            )
            continue
        if strategy == "adaptive":
            active = _leader(books, edge_window, edge_min)
        else:
            active = strategy
        if active is None or not in_range or index < 80 or index + 1 >= len(bars) or times[index + 1] >= end_ts:
            continue
        signal = _pick(catalog, active)
        if signal is None or datetime.fromtimestamp(moment, timezone.utc).hour in skip_hours:
            continue
        if signal is None:
            continue
        if pause_day and key > pause_day:
            pause_day = ""
            streak = 0
        risk_block = pause_day == key or (day_start_equity > 0 and day_pnl <= -daily_limit * day_start_equity)
        if risk_block:
            blocked += 1
            if position is None:
                blocked_reasons["risk"] += 1
            continue
        if position is None and not halted:
            opened = _open_position(signal, bars[index + 1], index + 1, times[index + 1], cash, per_trade, market)
            if opened is None:
                blocked += 1
                blocked_reasons["volume"] += 1
            else:
                position = opened
                taken += 1
                decisions["taken"] = taken
        elif position is None and halted:
            blocked += 1
            blocked_reasons["lock"] += 1
        if shadow_position is None:
            opened = _open_position(signal, bars[index + 1], index + 1, times[index + 1], shadow_cash, per_trade, market)
            if opened is not None:
                shadow_position = opened

    if position is not None:
        last = len(bars) - 1
        closed = _force_close(position, bars[last], last, times[last], market)
        cash += float(closed["pnl"])
        trades.append(closed)
        if equity_curve:
            equity_curve[-1] = round(cash, 2)
    for frame, book in extra.items():
        if book["position"] is not None:
            last = len(bars) - 1
            closed = _book_trade(_force_close(book["position"], bars[last], last, times[last], market), book["ratio"], frame)
            cash += float(closed["pnl"])
            trades.append(closed)
            if equity_curve:
                equity_curve[-1] = round(cash, 2)
    if crew is not None:
        last = len(bars) - 1
        for closed in _crew_close_all(crew, bars[last], last, times[last], market):
            cash += float(closed["pnl"])
            trades.append(closed)
        if equity_curve:
            equity_curve[-1] = round(cash, 2)
    trades.sort(key=lambda trade: (int(trade.get("closedTs") or 0), int(trade.get("openedTs") or 0)))
    if shadow_position is not None:
        last = len(bars) - 1
        closed = _force_close(shadow_position, bars[last], last, times[last], market)
        shadow_cash += float(closed["pnl"])
        shadow_trades.append(closed)
        if shadow_curve:
            shadow_curve[-1] = round(shadow_cash, 2)

    halted = bool(gate["ever"])
    ledger = [
        {"time": trade["time"], "side": trade["side"], "strategy": trade["strategy"], "pnl": trade["pnl"], "r": trade["r"]}
        for trade in trades
    ]
    metrics = _metrics(trades, equity_curve, drawdown_curve, capital, timeframe)
    shadow_metrics = _metrics(shadow_trades, shadow_curve, shadow_drawdown, capital, timeframe)
    paper_rows = books.get("trend", {}).get("trades", [])
    paper = _metrics(paper_rows if isinstance(paper_rows, list) else [], [capital], [0.0], capital, timeframe)
    months = _month_gate(trades)
    return {
        "ok": True,
        "strategy": STRATEGIES[strategy],
        "timeframe": timeframe,
        "start": start_day.strftime("%d/%m/%Y"),
        "end": end_day.strftime("%d/%m/%Y"),
        "capital": capital,
        "spread": round(spread, 2),
        "trades": trades[-40:],
        "ledger": ledger,
        "tradeCount": len(trades),
        "equity": _sample(equity_curve, 240),
        "drawdown": _sample(drawdown_curve, 240),
        "metrics": metrics,
        "halted": halted,
        "signals": taken,
        "blocked": blocked,
        "shadow": shadow_metrics,
        "paper": paper,
        "months": months,
        "promotable": bool(months["promotable"]),
        "message": (_crew_message(crew, metrics, halted) if crew is not None else _message(metrics, shadow_metrics, halted, spread, taken, blocked) + _books_message(extra)),
        "kind": "live" if strategy in {"auto", "agents"} else "single",
        "candles": [
            [times[index], round(bar[0], 2), round(bar[1], 2), round(bar[2], 2), round(bar[3], 2)]
            for index, bar in enumerate(bars)
            if start_ts <= times[index] < end_ts
        ],
        "chartTrades": [
            {
                "strategy": trade["strategy"], "agent": trade.get("agent") or "", "side": trade["side"], "openedTs": trade.get("openedTs"), "closedTs": trade.get("closedTs"),
                "entry": trade["entry"], "exit": trade["exit"], "stop": trade.get("stop"), "take": trade.get("take"),
                "pnl": trade["pnl"], "r": trade["r"], "bars": trade["bars"], "reason": trade["reason"],
            }
            for trade in trades
        ],
        "role": "live" if strategy in {"auto", "agents"} else _role(strategy),
        "decisions": decisions if strategy in {"auto", "agents"} else None,
        "agents": _crew_report(crew) if crew is not None else None,
    }


def _simulate_compare(
    bars: list[tuple[float, float, float, float]],
    times: list[int],
    market: dict[str, float],
    timeframe: str,
    start_day: datetime,
    end_day: datetime,
    capital: float,
    limits: dict[str, float | int],
) -> list[dict[str, object]]:
    from services.api.chart_analysis import _atr, _thresholds
    from services.api.meta_model import read_mode
    from services.api.strategies import WINDOW, evaluate_strategies

    model_mode = read_mode()
    start_ts = int(start_day.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int((end_day + timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp())
    reward_ratio = float(limits["minRewardRatio"])
    per_trade = float(limits["perTradePercent"]) / 100
    daily_limit = float(limits["dailyLossPercent"]) / 100
    drawdown_limit = float(limits["drawdownPercent"]) / 100
    loss_limit = int(limits["maxLossStreak"])
    spread = float(market["spread"])
    accounts = {name: _new_account(capital) for name in BOOKS}

    for index, bar in enumerate(bars):
        moment = times[index]
        in_range = start_ts <= moment < end_ts
        key = datetime.fromtimestamp(moment, timezone.utc).strftime("%Y-%m-%d")
        context = None
        catalog = None
        if index >= 80:
            window = bars[max(0, index - WINDOW + 1) : index + 1]
            context = _context(window, timeframe)
            if index + 1 < len(bars):
                atr = _atr(window, 14)
                last_atr = next((value for value in reversed(atr) if value is not None), 1.0)
                support, resistance = _thresholds(window, last_atr)
                catalog = evaluate_strategies(
                    window,
                    timeframe,
                    support,
                    resistance,
                    spread,
                    reward_ratio,
                    times[max(0, index - WINDOW + 1) : index + 1],
                    _fill_hour(times[index + 1]),
                )["catalog"]
                if model_mode == "size":
                    _attach_model(catalog, window, times[max(0, index - WINDOW + 1) : index + 1], timeframe, _fill_hour(times[index + 1]))
        upcoming = None if index + 1 >= len(bars) else bars[index + 1]
        upcoming_time = 0 if upcoming is None else times[index + 1]
        for name, account in accounts.items():
            _step_account(
                account,
                name,
                bar,
                index,
                moment,
                key,
                in_range,
                context,
                catalog,
                upcoming,
                upcoming_time,
                market,
                per_trade,
                daily_limit,
                drawdown_limit,
                loss_limit,
                end_ts,
                bars,
            )

    for account in accounts.values():
        _close_leftover(account, bars, times, market)
    return [
        _account_report(accounts[name], name, timeframe, start_day, end_day, capital, spread)
        for name in BOOKS
    ]


def _new_account(capital: float) -> dict[str, object]:
    return {
        "cash": capital,
        "peak": capital,
        "halted": False,
        "gate": _new_gate(capital),
        "streak": 0,
        "pause_day": "",
        "position": None,
        "day_key": "",
        "day_start": capital,
        "day_pnl": 0.0,
        "trades": [],
        "equity": [],
        "drawdown": [],
        "taken": 0,
        "blocked": 0,
        "shadow_cash": capital,
        "shadow_position": None,
        "shadow_trades": [],
        "shadow_peak": capital,
        "shadow_equity": [],
        "shadow_drawdown": [],
    }


def _step_account(
    account: dict[str, object],
    name: str,
    bar: tuple[float, float, float, float],
    index: int,
    moment: int,
    key: str,
    in_range: bool,
    context: dict[str, float | str | None] | None,
    catalog: object,
    upcoming: tuple[float, float, float, float] | None,
    upcoming_time: int,
    market: dict[str, float],
    per_trade: float,
    daily_limit: float,
    drawdown_limit: float,
    loss_limit: int,
    end_ts: int,
    bars: list[tuple[float, float, float, float]],
) -> None:
    if in_range and account["day_key"] != key:
        account["day_key"] = key
        account["day_start"] = float(account["cash"]) + _open_pnl(_as_position(account["position"]), bar[0], market)
        account["day_pnl"] = 0.0
    position = _as_position(account["position"])
    if position is not None and index >= int(position["fillIndex"]):
        closed = _exit_position(position, bar, index, moment, market, index == len(bars) - 1, context)
        if closed is not None:
            account["cash"] = float(account["cash"]) + float(closed["pnl"])
            if in_range:
                account["day_pnl"] = float(account["day_pnl"]) + float(closed["pnl"])
            if float(closed["pnl"]) < 0:
                account["streak"] = int(account["streak"]) + 1
                if int(account["streak"]) >= loss_limit:
                    account["pause_day"] = key
            else:
                account["streak"] = 0
            trades = account["trades"]
            if isinstance(trades, list):
                trades.append(closed)
            account["position"] = None
    shadow_position = _as_position(account["shadow_position"])
    if shadow_position is not None and index >= int(shadow_position["fillIndex"]):
        closed = _exit_position(shadow_position, bar, index, moment, market, index == len(bars) - 1, context)
        if closed is not None:
            account["shadow_cash"] = float(account["shadow_cash"]) + float(closed["pnl"])
            shadow_trades = account["shadow_trades"]
            if isinstance(shadow_trades, list):
                shadow_trades.append(closed)
            account["shadow_position"] = None
    if in_range:
        equity = float(account["cash"]) + _open_pnl(_as_position(account["position"]), bar[3], market)
        account["peak"] = max(float(account["peak"]), equity)
        peak = float(account["peak"])
        drawdown = 0.0 if peak <= 0 else (peak - equity) / peak
        equity_curve = account["equity"]
        drawdown_curve = account["drawdown"]
        if isinstance(equity_curve, list):
            equity_curve.append(round(equity, 2))
        if isinstance(drawdown_curve, list):
            drawdown_curve.append(round(drawdown * 100, 2))
        gate = account["gate"]
        if isinstance(gate, dict):
            account["halted"] = _drawdown_gate(gate, equity, moment, drawdown_limit)
        shadow_equity = float(account["shadow_cash"]) + _open_pnl(_as_position(account["shadow_position"]), bar[3], market)
        account["shadow_peak"] = max(float(account["shadow_peak"]), shadow_equity)
        shadow_peak = float(account["shadow_peak"])
        shadow_drop = 0.0 if shadow_peak <= 0 else (shadow_peak - shadow_equity) / shadow_peak
        shadow_curve = account["shadow_equity"]
        shadow_drawdown = account["shadow_drawdown"]
        if isinstance(shadow_curve, list):
            shadow_curve.append(round(shadow_equity, 2))
        if isinstance(shadow_drawdown, list):
            shadow_drawdown.append(round(shadow_drop * 100, 2))
    if not in_range or index < 80 or upcoming is None or upcoming_time >= end_ts:
        return
    signal = _pick(catalog, name)
    if signal is None:
        return
    pause_day = str(account["pause_day"])
    if pause_day and key > pause_day:
        account["pause_day"] = ""
        account["streak"] = 0
        pause_day = ""
    day_start = float(account["day_start"])
    risk_block = pause_day == key or (day_start > 0 and float(account["day_pnl"]) <= -daily_limit * day_start)
    if risk_block:
        account["blocked"] = int(account["blocked"]) + 1
        return
    if account["position"] is None and not bool(account["halted"]):
        opened = _open_position(signal, upcoming, index + 1, upcoming_time, float(account["cash"]), per_trade, market)
        if opened is None:
            account["blocked"] = int(account["blocked"]) + 1
        else:
            account["position"] = opened
            account["taken"] = int(account["taken"]) + 1
    elif account["position"] is None and bool(account["halted"]):
        account["blocked"] = int(account["blocked"]) + 1
    if account["shadow_position"] is None:
        opened = _open_position(signal, upcoming, index + 1, upcoming_time, float(account["shadow_cash"]), per_trade, market)
        if opened is not None:
            account["shadow_position"] = opened


def _close_leftover(
    account: dict[str, object],
    bars: list[tuple[float, float, float, float]],
    times: list[int],
    market: dict[str, float],
) -> None:
    last = len(bars) - 1
    position = _as_position(account["position"])
    if position is not None:
        closed = _force_close(position, bars[last], last, times[last], market)
        account["cash"] = float(account["cash"]) + float(closed["pnl"])
        trades = account["trades"]
        if isinstance(trades, list):
            trades.append(closed)
        equity = account["equity"]
        if isinstance(equity, list) and equity:
            equity[-1] = round(float(account["cash"]), 2)
        account["position"] = None
    shadow_position = _as_position(account["shadow_position"])
    if shadow_position is not None:
        closed = _force_close(shadow_position, bars[last], last, times[last], market)
        account["shadow_cash"] = float(account["shadow_cash"]) + float(closed["pnl"])
        shadow_trades = account["shadow_trades"]
        if isinstance(shadow_trades, list):
            shadow_trades.append(closed)
        shadow_equity = account["shadow_equity"]
        if isinstance(shadow_equity, list) and shadow_equity:
            shadow_equity[-1] = round(float(account["shadow_cash"]), 2)
        account["shadow_position"] = None


def _account_report(
    account: dict[str, object],
    name: str,
    timeframe: str,
    start_day: datetime,
    end_day: datetime,
    capital: float,
    spread: float,
) -> dict[str, object]:
    trades = account["trades"] if isinstance(account["trades"], list) else []
    equity = account["equity"] if isinstance(account["equity"], list) else []
    drawdown = account["drawdown"] if isinstance(account["drawdown"], list) else []
    shadow_trades = account["shadow_trades"] if isinstance(account["shadow_trades"], list) else []
    shadow_equity = account["shadow_equity"] if isinstance(account["shadow_equity"], list) else []
    shadow_drawdown = account["shadow_drawdown"] if isinstance(account["shadow_drawdown"], list) else []
    metrics = _metrics(trades, equity, drawdown, capital, timeframe)
    shadow_metrics = _metrics(shadow_trades, shadow_equity, shadow_drawdown, capital, timeframe)
    taken = int(account["taken"])
    blocked = int(account["blocked"])
    gate = account["gate"]
    halted = bool(gate["ever"]) if isinstance(gate, dict) else bool(account["halted"])
    return {
        "ok": True,
        "id": name,
        "strategy": STRATEGIES[name],
        "timeframe": timeframe,
        "start": start_day.strftime("%d/%m/%Y"),
        "end": end_day.strftime("%d/%m/%Y"),
        "capital": capital,
        "spread": round(spread, 2),
        "trades": trades[-40:],
        "tradeCount": len(trades),
        "equity": _sample(equity, 240),
        "drawdown": _sample(drawdown, 240),
        "metrics": metrics,
        "halted": halted,
        "signals": taken,
        "blocked": blocked,
        "shadow": shadow_metrics,
        "months": _month_gate(trades),
        "message": _compare_message(STRATEGIES[name], metrics, halted, taken),
        "role": _role(name),
    }


def _role(name: str) -> str:
    from services.api.strategies import LIVE_STRATEGIES, SHADOW_STRATEGIES

    if name in LIVE_STRATEGIES:
        return "live"
    if name in SHADOW_STRATEGIES:
        return "shadow"
    return "analysis"


def _compare_message(label: str, metrics: dict[str, float | int | None], halted: bool, taken: int) -> str:
    factor = metrics["profitFactor"] if metrics["profitFactor"] is not None else "—"
    text = (
        f"{label}: lãi {metrics['net']}, hệ số lời {factor}, sụt giảm {metrics['maxDrawdown']}%, "
        f"{metrics['trades']} lệnh. Vào {taken} lệnh. Không gửi lệnh thật."
    )
    if halted:
        text += " Sổ chính đã tạm ngừng lệnh mới khi sụt giảm chạm giới hạn (tự mở lại một lần sau 48 giờ)."
    if taken == 0:
        text = f"{label}: không có lệnh nào đủ điều kiện trong khoảng này."
    return text


def _as_position(value: object) -> dict[str, float | int | str] | None:
    if isinstance(value, dict):
        return value
    return None


def _advance_book(
    book: dict[str, object],
    signal: dict[str, object] | None,
    bar: tuple[float, float, float, float],
    index: int,
    moment: int,
    upcoming: tuple[float, float, float, float] | None,
    upcoming_time: int,
    market: dict[str, float],
    last_bar: bool,
    context: dict[str, float | str | None] | None = None,
) -> None:
    position = book["position"]
    if isinstance(position, dict) and index >= int(position["fillIndex"]):
        closed = _exit_position(position, bar, index, moment, market, last_bar, context)
        if closed is not None:
            recent = book["recent"]
            if isinstance(recent, list):
                recent.append(float(closed["r"]))
                del recent[:-12]
            closed_rows = book["trades"]
            if isinstance(closed_rows, list):
                closed_rows.append(closed)
            book["position"] = None
    if book["position"] is None and signal is not None and upcoming is not None:
        opened = _open_position(signal, upcoming, index + 1, upcoming_time, 1000, 0.02, market)
        if opened is not None:
            book["position"] = opened


def _leader(books: dict[str, dict[str, object]], edge_window: int = 6, edge_min: int = 4) -> str | None:
    best_name = None
    best_score = 0.0
    for name, book in books.items():
        recent = book["recent"]
        if not isinstance(recent, list) or len(recent) < edge_min:
            continue
        score = sum(float(value) for value in recent[-edge_window:])
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _new_gate(capital: float) -> dict[str, float | int | bool]:
    return {"peak": capital, "since": 0, "locked": False, "unlocks": 0, "ever": False}


def _drawdown_gate(gate: dict[str, float | int | bool], equity: float, moment: int, limit: float) -> bool:
    """Same rule as live: hitting the drawdown limit locks new entries; the lock opens once by
    itself after the cooldown with the peak reset to equity; a second hit stays locked.
    Returns True while new entries are locked. The reported drawdown curve keeps its own peak."""
    from services.api.strategies import DRAWDOWN_COOLDOWN_SECONDS

    gate["peak"] = max(float(gate["peak"]), equity)
    peak = float(gate["peak"])
    if not gate["locked"] and peak > 0 and (peak - equity) / peak >= limit:
        gate["locked"] = True
        gate["ever"] = True
        gate["since"] = moment
    if gate["locked"] and int(gate["unlocks"]) == 0 and moment - int(gate["since"]) >= DRAWDOWN_COOLDOWN_SECONDS:
        gate["locked"] = False
        gate["unlocks"] = 1
        gate["peak"] = equity
    return bool(gate["locked"])


def _pick(catalog: object, strategy: str) -> dict[str, object] | None:
    """strategy "auto" follows the live selector exactly: the chosen card, and only if it
    belongs to a strategy that is allowed to send real orders."""
    if not isinstance(catalog, list):
        return None
    for item in catalog:
        if not isinstance(item, dict) or not item.get("confirmed") or item.get("side") not in {"buy", "sell"}:
            continue
        if strategy != "auto" and item.get("id") != strategy:
            continue
        if strategy == "auto" and not (item.get("chosen") and item.get("live")):
            continue
        if item.get("entry") is None or item.get("stop") is None:
            continue
        if item.get("manage") not in {"structure", "trail"} and item.get("takeProfit") is None:
            continue
        return item
    return None


def _model_note(timeframe: str) -> str:
    from services.api.meta_model import TF_SECONDS, latest, read_mode

    if read_mode() != "size" or timeframe not in TF_SECONDS:
        return ""
    report = latest()
    if not report.get("ok"):
        return ""
    return (
        f" Theo xu hướng có áp dụng mô hình chấm tín hiệu (điểm thấp vào nửa khối lượng). Mô hình đã học dữ liệu đến {report.get('to')}, "
        "nên kết quả trong giai đoạn đó lạc quan hơn thực tế; số kiểm định trung thực nằm ở màn Mô hình."
    )


def _attach_model(catalog: object, window: list, times: list[int], timeframe: str, fill_hour: int) -> None:
    from services.api.meta_model import score_window

    if not isinstance(catalog, list):
        return
    for item in catalog:
        if not isinstance(item, dict) or item.get("id") != "trend" or not item.get("confirmed") or item.get("side") not in {"buy", "sell"}:
            continue
        scored = score_window(window, times, timeframe, str(item["side"]), float(item["entry"]), float(item["stop"]), fill_hour)
        if scored is not None:
            item["modelScore"] = scored["score"]
            item["sizeFactor"] = 0.5 if scored["low"] else 1.0


def _warmup(start_day: datetime, timeframe: str) -> datetime:
    from services.api.strategies import WINDOW

    seconds = TF_SECONDS.get(timeframe, 900) * (WINDOW + 50)
    # markets close two days a week, so stretch calendar time by 7/5
    return start_day - max(timedelta(days=45), timedelta(seconds=seconds * 7 / 5))


def _fill_hour(moment: int) -> int:
    return datetime.fromtimestamp(int(moment), timezone.utc).hour


def _min_lot_cap() -> float:
    try:
        return float(read_risk().get("minLotPercent") or 0) / 100
    except (OSError, ValueError, TypeError):
        return 0.0


def _open_position(
    signal: dict[str, object],
    bar: tuple[float, float, float, float],
    index: int,
    moment: int,
    cash: float,
    per_trade: float,
    market: dict[str, float],
    min_lot_cap: float | None = None,
) -> dict[str, float | int | str] | None:
    """Bars are bid prices. A buy fills at the ask (open + spread), a sell at the bid.
    min_lot_cap: like live, a size below the minimum lot is raised to the minimum lot while that
    lot risks at most this share of cash (None = the user's minLotPercent setting).
    Stop and target keep the planned distances from the real fill."""
    side = str(signal["side"])
    spread = float(market["spread"])
    fill = bar[0] + spread if side == "buy" else bar[0]
    manage = str(signal.get("manage") or "fixed")
    risk = abs(float(signal["entry"]) - float(signal["stop"]))
    open_ended = manage in {"structure", "trail"} or signal.get("takeProfit") is None
    reward = 0.0 if open_ended else abs(float(signal["takeProfit"]) - float(signal["entry"]))
    if risk <= 0 or (not open_ended and reward <= 0):
        return None
    tick_size = float(market["tickSize"])
    tick_value = float(market["tickValue"])
    if tick_size <= 0 or tick_value <= 0:
        return None
    # the signal model may halve the size of a low-scoring trade; it never raises it
    risk_money = cash * per_trade * min(1.0, float(signal.get("sizeFactor") or 1.0))
    money_per_lot = risk / tick_size * tick_value
    if money_per_lot <= 0:
        return None
    step = float(market["volumeStep"]) or 0.01
    volume = math.floor((risk_money / money_per_lot) / step + 1e-9) * step
    volume = round(min(float(market["volumeMax"]), volume), 2)
    if volume < float(market["volumeMin"]):
        cap = _min_lot_cap() if min_lot_cap is None else min_lot_cap
        if cap <= 0 or money_per_lot * float(market["volumeMin"]) > cash * cap + 1e-9:
            return None
        volume = round(float(market["volumeMin"]), 2)
    if side == "buy":
        stop = fill - risk
        take = 0.0 if open_ended else fill + reward
    else:
        stop = fill + risk
        take = 0.0 if open_ended else fill - reward
    return {
        "side": side,
        "name": str(signal["name"]),
        "manage": manage,
        "fillIndex": index,
        "openedAt": moment,
        "entry": fill,
        "stop": stop,
        "stopInitial": stop,
        "take": take,
        "risk": risk,
        "best": fill,
        "maxBars": int(signal.get("maxBars") or 8),
        "volume": volume,
        "riskMoney": volume * money_per_lot,
    }


def _exit_position(
    position: dict[str, float | int | str],
    bar: tuple[float, float, float, float],
    index: int,
    moment: int,
    market: dict[str, float],
    last_bar: bool,
    context: dict[str, float | str | None] | None = None,
) -> dict[str, object] | None:
    """Check exits inside the bar with the stop and target known before the bar opened, then
    update trailing stops from the closed bar so they only act from the next bar on. When stop
    and target are both inside one bar the stop is assumed first."""
    side = str(position["side"])
    spread = float(market["spread"])
    first = index == int(position["fillIndex"])
    stop = float(position["stop"])
    if side == "buy":
        if bar[2] <= stop:
            price = stop if first else min(bar[0], stop)
            return _close(position, price, index, moment, market, "Cắt lỗ")
    else:
        if bar[1] + spread >= stop:
            price = stop if first else max(bar[0] + spread, stop)
            return _close(position, price, index, moment, market, "Cắt lỗ")
    manage = position.get("manage")
    if manage not in {"structure", "trail"}:
        take = float(position["take"])
        if side == "buy" and bar[1] >= take:
            price = take if first else max(bar[0], take)
            return _close(position, price, index, moment, market, "Chốt lời")
        if side == "sell" and bar[2] + spread <= take:
            price = take if first else min(bar[0] + spread, take)
            return _close(position, price, index, moment, market, "Chốt lời")
    close_price = bar[3] if side == "buy" else bar[3] + spread
    if manage == "structure" and context is not None and not first:
        reason = _structure_exit(side, bar[3], context)
        if reason is not None:
            return _close(position, close_price, index, moment, market, reason)
    held = index - int(position["fillIndex"]) + 1
    if last_bar:
        return _close(position, close_price, index, moment, market, "Hết mẫu kiểm thử")
    if held >= int(position.get("maxBars") or 8):
        return _close(position, close_price, index, moment, market, f"Hết {int(position.get('maxBars') or 8)} nến")
    if manage == "structure" and context is not None:
        _trail(position, bar, context)
    if manage == "trail" and context is not None:
        _chandelier(position, bar, context, spread)
    return None


def _trail(position: dict[str, float | int | str], bar: tuple[float, float, float, float], context: dict[str, float | str | None]) -> None:
    ema20 = context.get("ema20")
    if ema20 is None:
        return
    entry = float(position["entry"])
    stop = float(position["stop"])
    if position["side"] == "buy" and entry < float(ema20) < bar[3]:
        position["stop"] = max(stop, float(ema20))
    if position["side"] == "sell" and bar[3] < float(ema20) < entry:
        position["stop"] = min(stop, float(ema20))


def _chandelier(
    position: dict[str, float | int | str],
    bar: tuple[float, float, float, float],
    context: dict[str, float | str | None],
    spread: float,
) -> None:
    """Once the trade is 1R in profit, trail the stop 3 ATR behind the best price."""
    atr = context.get("atr")
    if atr is None:
        return
    entry = float(position["entry"])
    risk = float(position.get("risk") or 0)
    if position["side"] == "buy":
        best = max(float(position["best"]), bar[1])
        position["best"] = best
        if best - entry >= risk:
            position["stop"] = max(float(position["stop"]), best - 3 * float(atr))
    else:
        best = min(float(position["best"]), bar[2] + spread)
        position["best"] = best
        if entry - best >= risk:
            position["stop"] = min(float(position["stop"]), best + 3 * float(atr))


def _structure_exit(side: str, close: float, context: dict[str, float | str | None]) -> str | None:
    ema50 = context.get("ema50")
    higher = context.get("higher")
    if ema50 is not None and ((side == "buy" and close < float(ema50)) or (side == "sell" and close > float(ema50))):
        return "Cắt EMA 50"
    if (side == "buy" and higher == "down") or (side == "sell" and higher == "up"):
        return "Khung lớn đảo"
    return None


def _context(window: list[tuple[float, float, float, float]], timeframe: str) -> dict[str, float | str | None]:
    from services.api.chart_analysis import _atr
    from services.api.strategies import HIGHER, _aggregate, _bias, _ema

    closes = [bar[3] for bar in window]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    atr = _atr(window, 14)
    _name, factor = HIGHER.get(timeframe, ("H1", 4))
    higher_bars = window if factor <= 1 else _aggregate(window, factor)
    return {
        "ema20": None if not ema20 or ema20[-1] is None else float(ema20[-1]),
        "ema50": None if not ema50 or ema50[-1] is None else float(ema50[-1]),
        "atr": None if not atr or atr[-1] is None else float(atr[-1]),
        "higher": _bias(higher_bars),
    }


def _force_close(
    position: dict[str, float | int | str],
    bar: tuple[float, float, float, float],
    index: int,
    moment: int,
    market: dict[str, float],
) -> dict[str, object]:
    price = bar[3] if position["side"] == "buy" else bar[3] + float(market["spread"])
    return _close(position, price, index, moment, market, "Hết mẫu kiểm thử")


def _close(
    position: dict[str, float | int | str],
    price: float,
    index: int,
    moment: int,
    market: dict[str, float],
    reason: str,
) -> dict[str, object]:
    entry = float(position["entry"])
    volume = float(position["volume"])
    move = price - entry if position["side"] == "buy" else entry - price
    pnl = move / float(market["tickSize"]) * float(market["tickValue"]) * volume
    pnl += _swap(position, moment, market)
    risk_money = float(position["riskMoney"]) or 1
    return {
        "time": datetime.fromtimestamp(int(position["openedAt"]), timezone.utc).strftime("%d/%m %H:%M"),
        "month": datetime.fromtimestamp(int(position["openedAt"]), timezone.utc).strftime("%Y-%m"),
        "side": "Mua" if position["side"] == "buy" else "Bán",
        "strategy": position["name"],
        "agent": str(position.get("agent") or ""),
        "entry": round(entry, 2),
        "exit": round(price, 2),
        "pnl": round(pnl, 2),
        "r": round(pnl / risk_money, 2),
        "bars": index - int(position["fillIndex"]),
        "reason": reason,
        "openedTs": int(position["openedAt"]),
        "closedTs": int(moment),
        "stop": round(float(position.get("stopInitial") or position["stop"]), 2),
        "take": round(float(position.get("take") or 0), 2) or None,
    }


ROLLOVER_HOUR = 21


def _rollovers(opened: int, closed: int) -> int:
    """Swap nights between two moments: one per weekday rollover at 21:00 UTC, three on
    Wednesday (MetaTrader swap_rollover3days = 3)."""
    if closed <= opened:
        return 0
    day = 86400
    offset = ROLLOVER_HOUR * 3600
    moment = ((opened - offset) // day + 1) * day + offset
    nights = 0
    while moment <= closed:
        weekday = ((moment // day) + 3) % 7
        if weekday < 5:
            nights += 3 if weekday == 2 else 1
        moment += day
    return nights


def _swap(position: dict[str, float | int | str], moment: int, market: dict[str, float]) -> float:
    nights = _rollovers(int(position["openedAt"]), int(moment))
    if nights <= 0:
        return 0.0
    rate = float(market["swapLong"] if position["side"] == "buy" else market["swapShort"])
    volume = float(position["volume"])
    mode = int(market["swapMode"])
    if mode == 1:
        return nights * rate * float(market["point"]) / float(market["tickSize"]) * float(market["tickValue"]) * volume
    if mode in {2, 3, 4, 6}:
        return nights * rate * volume
    return 0.0


def _open_pnl(position: dict[str, float | int | str] | None, price: float, market: dict[str, float]) -> float:
    if position is None:
        return 0.0
    entry = float(position["entry"])
    move = price - entry if position["side"] == "buy" else entry - price
    return move / float(market["tickSize"]) * float(market["tickValue"]) * float(position["volume"])


def _metrics(
    trades: list[dict[str, object]],
    equity: list[float],
    drawdown: list[float],
    capital: float,
    timeframe: str,
) -> dict[str, float | int | None]:
    profits = [float(trade["pnl"]) for trade in trades if float(trade["pnl"]) > 0]
    losses = [float(trade["pnl"]) for trade in trades if float(trade["pnl"]) < 0]
    gross_profit = sum(profits)
    gross_loss = sum(losses)
    net = gross_profit + gross_loss
    wins = _consecutive(trades, True)
    loss_streak = _consecutive(trades, False)
    average_r = sum(float(trade["r"]) for trade in trades) / len(trades) if trades else 0.0
    low, high, verdict = _confidence([float(trade["r"]) for trade in trades])
    holding = sum(int(trade["bars"]) for trade in trades) / len(trades) if trades else 0.0
    max_dd = max(drawdown) if drawdown else 0.0
    max_dd_money = capital * max_dd / 100
    return {
        "trades": len(trades),
        "net": round(net, 2),
        "grossProfit": round(gross_profit, 2),
        "grossLoss": round(gross_loss, 2),
        "winRate": round(len(profits) / len(trades), 4) if trades else 0.0,
        "profitFactor": round(gross_profit / abs(gross_loss), 2) if gross_loss else None,
        "maxDrawdown": round(max_dd, 2),
        "sharpe": _sharpe(equity, timeframe),
        "recovery": round(net / max_dd_money, 2) if max_dd_money > 0 else None,
        "expectancy": round(net / len(trades), 2) if trades else 0.0,
        "averageR": round(average_r, 2),
        "averageRLow": low,
        "averageRHigh": high,
        "reliability": verdict,
        "holdingBars": round(holding, 1),
        "consecutiveWins": wins,
        "consecutiveLosses": loss_streak,
        "finalEquity": equity[-1] if equity else capital,
    }


def _confidence(r_values: list[float]) -> tuple[float | None, float | None, str]:
    """95% interval of the mean R and a plain verdict on how much the sample can say."""
    count = len(r_values)
    if count < 2:
        return None, None, "Chưa có lệnh để đánh giá."
    mean = sum(r_values) / count
    deviation = math.sqrt(sum((value - mean) ** 2 for value in r_values) / (count - 1))
    half = 1.96 * deviation / math.sqrt(count)
    low, high = round(mean - half, 3), round(mean + half, 3)
    if count < 30:
        verdict = f"Chỉ {count} lệnh, quá ít để kết luận. Hãy chạy khoảng dài hơn."
    elif low > 0:
        verdict = f"{count} lệnh, R trung bình dương có ý nghĩa thống kê (95%: {low:+.2f} đến {high:+.2f})."
    elif high < 0:
        verdict = f"{count} lệnh, R trung bình âm có ý nghĩa thống kê (95%: {low:+.2f} đến {high:+.2f})."
    else:
        verdict = f"{count} lệnh, chưa phân biệt được với hòa vốn (95%: {low:+.2f} đến {high:+.2f})."
    return low, high, verdict


def _consecutive(trades: list[dict[str, object]], winners: bool) -> int:
    best = 0
    streak = 0
    for trade in trades:
        win = float(trade["pnl"]) > 0
        if win == winners:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def _sharpe(equity: list[float], timeframe: str) -> float | None:
    if len(equity) < 30:
        return None
    returns = [
        (equity[index] - equity[index - 1]) / equity[index - 1]
        for index in range(1, len(equity))
        if equity[index - 1] > 0
    ]
    if len(returns) < 20:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    deviation = math.sqrt(variance)
    if deviation == 0:
        return None
    per_year = {"M5": 72576, "M15": 24192, "M30": 12096, "H1": 6048, "H4": 1512}[timeframe]
    return round(mean / deviation * math.sqrt(per_year), 2)


def _sample(values: list[float], limit: int) -> list[float]:
    if len(values) <= limit:
        return values
    step = len(values) / limit
    return [values[min(len(values) - 1, int(index * step))] for index in range(limit)]


def _month_gate(trades: list[dict[str, object]]) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = {}
    for trade in trades:
        groups.setdefault(str(trade.get("month") or ""), []).append(trade)
    rows = []
    for key in sorted(groups):
        batch = groups[key]
        gains = sum(float(trade["pnl"]) for trade in batch if float(trade["pnl"]) > 0)
        losses = sum(float(trade["pnl"]) for trade in batch if float(trade["pnl"]) < 0)
        factor = round(gains / abs(losses), 2) if losses else None
        net = round(sum(float(trade["pnl"]) for trade in batch), 2)
        rows.append({"month": key, "trades": len(batch), "net": net, "profitFactor": factor})
    # A validated M30 strategy takes about ten trades a month, so 30 trades in every single
    # month could never pass. Judge three consecutive months together instead.
    promotable = False
    for index in range(0, max(0, len(rows) - 2)):
        keys = {row["month"] for row in rows[index : index + 3]}
        batch = [trade for trade in trades if str(trade.get("month") or "") in keys]
        gains = sum(float(trade["pnl"]) for trade in batch if float(trade["pnl"]) > 0)
        losses = -sum(float(trade["pnl"]) for trade in batch if float(trade["pnl"]) < 0)
        if len(batch) >= 20 and losses > 0 and gains / losses >= 1.2 and gains > losses:
            promotable = True
    return {"rows": rows, "promotable": promotable}


def _new_crew(timeframe: str) -> dict[str, object]:
    """Multi-agent replica: every agent of agents.AGENTS on its own frame (built from the base
    frame's bars), one position each, real or paper, sized by the coordinator's weights."""
    from services.api import agents

    base = TF_SECONDS.get(timeframe, 900)
    members = {}
    for config in agents.AGENTS:
        seconds = int(agents.FRAME_SECONDS[str(config["timeframe"])])
        if seconds < base or seconds % base:
            continue
        members[str(config["id"])] = {
            "config": config,
            "frame": str(config["timeframe"]),
            "ratio": seconds // base,
            "ledger": agents.new_ledger(),
            "position": None,
            "real": False,
            "streak": 0,
            "pause": "",
            "stats": {"name": f"{config['alias']} ({config['name']})", "alias": config["alias"], "real": bool(config["core"]), "signals": 0, "taken": 0, "paper": 0, "busy": 0, "risk": 0, "lock": 0, "volume": 0, "openRisk": 0},
        }
    frames = {
        member["frame"]: {"seconds": TF_SECONDS.get(member["frame"], base), "ratio": member["ratio"], "bars": [], "times": []}
        for member in members.values()
    }
    crew = {"members": members, "frames": frames, "weights": {}, "month": "", "notes": [], "base": timeframe}
    _crew_reweight(crew)
    return crew


def _crew_reweight(crew: dict[str, object]) -> None:
    from services.api import agents

    ledgers = {name: member["ledger"] for name, member in crew["members"].items()}
    for config in agents.AGENTS:
        ledgers.setdefault(str(config["id"]), agents.new_ledger())
    crew["weights"] = agents.weights(ledgers)


def _crew_open_pnl(crew: dict[str, object] | None, price: float, market: dict[str, float]) -> float:
    if crew is None:
        return 0.0
    return sum(_open_pnl(member["position"], price, market) for member in crew["members"].values() if member["position"] is not None and member["real"])


def _crew_exits(
    crew: dict[str, object], bar: tuple[float, float, float, float], index: int, moment: int, market: dict[str, float], last: bool,
    key: str, loss_limit: int, per_trade: float, context: dict[str, float | str | None] | None = None,
) -> list[dict[str, object]]:
    """Close positions hit this bar. Returns the real trades; paper trades only feed ledgers.
    context (indicators of the base frame) drives the trailing stop of base-frame agents."""
    from services.api import agents

    real_trades = []
    for member in crew["members"].values():
        held = member["position"]
        if held is None or index < int(held["fillIndex"]):
            continue
        closed = _exit_position(held, bar, index, moment, market, last, context if member["ratio"] == 1 else None)
        if closed is None:
            continue
        if member["ratio"] > 1:
            closed = _book_trade(closed, member["ratio"], member["frame"])
        member["position"] = None
        if member["real"]:
            real_trades.append(closed)
            if float(closed["pnl"]) < 0:
                member["streak"] += 1
                if member["streak"] >= loss_limit:
                    member["pause"] = key
            else:
                member["streak"] = 0
        count = sum(1 for other in crew["members"].values() if agents.is_real(other["config"], other["ledger"]))
        note = agents.record(member["config"], member["ledger"], float(closed["r"]), per_trade, count)
        if note:
            crew["notes"].append(f"{datetime.fromtimestamp(moment, timezone.utc).strftime('%d/%m/%Y')}: {note}")
            _crew_reweight(crew)
    return real_trades


def _crew_entries(
    crew: dict[str, object], bars: list[tuple[float, float, float, float]], times: list[int], index: int, moment: int,
    catalog: object, active: bool, key: str, cash: float, equity: float, per_trade: float, limits: dict[str, float | int],
    market: dict[str, float], spread: float, reward_ratio: float, daily_hit: bool, halted: bool,
) -> None:
    from services.api import agents
    from services.api.chart_analysis import _atr, _thresholds
    from services.api.strategies import WINDOW, evaluate_strategies

    month = key[:7]
    if month != crew["month"]:
        crew["month"] = month
        _crew_reweight(crew)
    bar = bars[index]
    closed_frames: dict[str, object] = {}
    for frame, state in crew["frames"].items():
        if state["ratio"] == 1:
            closed_frames[frame] = catalog
            continue
        seconds = int(state["seconds"])
        group = moment // seconds * seconds
        if state["times"] and state["times"][-1] == group:
            o, h, l, _c = state["bars"][-1]
            state["bars"][-1] = (o, max(h, bar[1]), min(l, bar[2]), bar[3])
        else:
            state["bars"].append(bar)
            state["times"].append(group)
            if len(state["bars"]) > WINDOW + 50:
                del state["bars"][0], state["times"][0]
        if index + 1 >= len(bars) or times[index + 1] // seconds * seconds == group or not active or len(state["bars"]) < 80:
            continue
        frame_bars = state["bars"][-WINDOW:]
        frame_atr = _atr(frame_bars, 14)
        frame_last = next((value for value in reversed(frame_atr) if value is not None), 1.0)
        low, high = _thresholds(frame_bars, frame_last)
        closed_frames[frame] = evaluate_strategies(frame_bars, frame, low, high, spread, reward_ratio, state["times"][-WINDOW:], _fill_hour(times[index + 1]))["catalog"]
    if not active:
        return
    count = sum(1 for member in crew["members"].values() if agents.is_real(member["config"], member["ledger"]))
    cap = float(limits.get("maxOpenRiskPercent") or 6) / 100
    for name, member in crew["members"].items():
        found = closed_frames.get(member["frame"])
        if found is None:
            continue
        signal = _pick(found, str(member["config"]["strategy"]))
        if signal is None:
            continue
        stats = member["stats"]
        stats["signals"] += 1
        if member["position"] is not None:
            stats["busy"] += 1
            continue
        member["real"] = agents.is_real(member["config"], member["ledger"])
        if not member["real"]:
            # paper: same fill and exits, no money; sized like an equal-share agent
            paper = _open_position(signal, bars[index + 1], index + 1, times[index + 1], 1_000_000.0, per_trade, market, 0.0)
            if paper is not None:
                paper["name"] = f"{paper['name']} {member['frame']}" if member["ratio"] > 1 else paper["name"]
                paper["maxBars"] = int(paper["maxBars"]) * int(member["ratio"])
                member["position"] = paper
                stats["paper"] += 1
            continue
        if member["pause"] and key > member["pause"]:
            member["pause"] = ""
            member["streak"] = 0
        if member["pause"] == key or daily_hit:
            stats["risk"] += 1
            continue
        if halted:
            stats["lock"] += 1
            continue
        factor = agents.size_factor(float(crew["weights"].get(name, 1 / max(count, 1))), count)
        same = any(
            other["position"] is not None and other["real"] and str(other["position"]["side"]) == str(signal["side"])
            for other in crew["members"].values()
        )
        price = float(bars[index][3])
        opposite = [
            other for other in crew["members"].values()
            if other["position"] is not None and other["real"] and str(other["position"]["side"]) != str(signal["side"])
        ]
        if opposite and agents.OPPOSITE == "losing" and any(_open_pnl(other["position"], price, market) >= 0 for other in opposite):
            stats["opposite"] = stats.get("opposite", 0) + 1
            continue
        if same and agents.SAME_SIDE == "skip":
            stats["sameSide"] = stats.get("sameSide", 0) + 1
            continue
        if same and agents.SAME_SIDE == "half":
            factor *= 0.5
        opened = _open_position(signal, bars[index + 1], index + 1, times[index + 1], cash, per_trade * factor, market)
        if opened is None:
            stats["volume"] += 1
            continue
        open_risk = sum(_remaining_risk(other["position"]) for other in crew["members"].values() if other["position"] is not None and other["real"])
        if equity > 0 and open_risk + float(opened["riskMoney"]) > cap * equity + 1e-9:
            stats["openRisk"] += 1
            continue
        if member["ratio"] > 1:
            opened["name"] = f"{opened['name']} {member['frame']}"
        opened["agent"] = str(member["config"]["alias"])
        opened["maxBars"] = int(opened["maxBars"]) * int(member["ratio"])
        member["position"] = opened
        stats["taken"] += 1
        if agents.TIGHTEN_ON_OPPOSITE:
            for other in opposite:
                held = other["position"]
                if _open_pnl(held, price, market) < 0:
                    held["stopInitial"] = held.get("stopInitial") or held["stop"]
                    held["stop"] = (float(held["stop"]) + price) / 2


def _remaining_risk(position: dict[str, object]) -> float:
    """Money still at risk: zero once the stop has moved past the entry (live: _position_risk)."""
    entry, stop = float(position["entry"]), float(position["stop"])
    initial = abs(entry - float(position.get("stopInitial") or stop)) or 1e-9
    if (position["side"] == "buy" and stop >= entry) or (position["side"] == "sell" and stop <= entry):
        return 0.0
    return float(position["riskMoney"]) * abs(entry - stop) / initial


def _crew_close_all(crew: dict[str, object], bar: tuple[float, float, float, float], index: int, moment: int, market: dict[str, float]) -> list[dict[str, object]]:
    real_trades = []
    for member in crew["members"].values():
        if member["position"] is None:
            continue
        closed = _force_close(member["position"], bar, index, moment, market)
        if member["ratio"] > 1:
            closed = _book_trade(closed, member["ratio"], member["frame"])
        if member["real"]:
            real_trades.append(closed)
        member["position"] = None
    return real_trades


def _crew_report(crew: dict[str, object]) -> list[dict[str, object]]:
    from services.api import agents

    rows = []
    for name, member in crew["members"].items():
        rs = [float(value) for value in member["ledger"]["rs"]]
        gains = sum(value for value in rs if value > 0)
        losses = -sum(value for value in rs if value < 0)
        rows.append({
            "id": name,
            "name": member["config"]["name"],
            "alias": member["config"]["alias"],
            "status": "thật" if agents.is_real(member["config"], member["ledger"]) else "giấy",
            "weight": crew["weights"].get(name, 0.0),
            "trades": len(rs),
            "totalR": round(sum(rs), 2),
            "averageR": round(sum(rs) / len(rs), 3) if rs else None,
            "profitFactor": round(gains / losses, 2) if losses > 0 else None,
            **member["stats"],
        })
    return rows


def _crew_message(crew: dict[str, object], metrics: dict[str, float | int | None], halted: bool) -> str:
    factor = metrics["profitFactor"] if metrics["profitFactor"] is not None else "—"
    from services.api import agents

    rows = _crew_report(crew)
    real = [row for row in rows if row["status"] == "thật"]
    parts = [
        f"Đa agent: {len(rows)} agent ({len(real)} tiền thật, {len(rows) - len(real)} lệnh giấy), điều phối {agents.COORDINATOR}. "
        f"Lãi {metrics['net']}, hệ số lời {factor}, sụt giảm {metrics['maxDrawdown']}%, {metrics['trades']} lệnh tiền thật."
    ]
    for row in rows:
        parts.append(f"{row['name']} ({row['status']}, tỷ trọng {row['weight'] * 100:.0f}%): {row['trades']} lệnh, {row['totalR']:+.1f}R.")
    if halted:
        parts.append("Agent tổng đã tạm ngừng lệnh mới khi sụt giảm chạm giới hạn.")
    parts.extend(crew["notes"][-6:])
    return " ".join(parts)


def _book_trade(trade: dict[str, object], ratio: int, frame: str) -> dict[str, object]:
    """A trade of an extra book is walked on the live frame's bars: report its length in the
    book's own bars."""
    held = int(trade["bars"]) // max(ratio, 1)
    reason = str(trade["reason"])
    parts = reason.split()
    if len(parts) == 3 and parts[0] == "Hết" and parts[2] == "nến" and parts[1].isdigit():
        reason = f"Hết {int(parts[1]) // max(ratio, 1)} nến {frame}"
    return {**trade, "bars": held, "reason": reason}


def _books_message(extra: dict[str, dict[str, object]]) -> str:
    parts = []
    for frame, book in extra.items():
        stats = book["stats"]
        parts.append(
            f" Sổ phụ {frame} (Theo xu hướng, nửa khối lượng, chạy song song): {stats['signals']} tín hiệu, vào {stats['taken']} lệnh, "
            f"bỏ {stats['busy']} vì đang giữ lệnh {frame}, {stats['risk'] + stats['lock'] + stats['volume']} vì cổng rủi ro."
        )
    return "".join(parts)


def _message(
    metrics: dict[str, float | int | None],
    shadow: dict[str, float | int | None],
    halted: bool,
    spread: float,
    taken: int,
    blocked: int,
) -> str:
    factor = metrics["profitFactor"] if metrics["profitFactor"] is not None else "—"
    text = (
        f"Sổ chính lãi {metrics['net']}, hệ số lời {factor}, sụt giảm {metrics['maxDrawdown']}%. "
        f"Sổ bóng, vẫn vào lệnh sau khi chạm trần sụt giảm, lãi {shadow['net']}. "
        f"Chênh lệch cố định {spread:.2f}. Vào {taken} lệnh, bỏ qua {blocked} tín hiệu. "
        "Bộ chọn chỉ vào lệnh theo chiến lược được phép gửi lệnh thật, giống hệt chế độ tự động. Không gửi lệnh thật."
    )
    if halted:
        text += " Sổ chính đã tạm ngừng lệnh mới khi sụt giảm chạm giới hạn (tự mở lại một lần sau 48 giờ)."
    if taken == 0:
        text = "Không có lệnh nào đủ điều kiện trong khoảng này. " + text
    return text


def _parse_day(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("Ngày phải theo dạng năm-tháng-ngày.") from error
