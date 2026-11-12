import json
import math
import threading
import time
from pathlib import Path
from typing import TypedDict

from services.api.settings_store import read_password, read_risk, read_settings

Bar = tuple[float, float, float, float]
TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
SCORE_EVERY = {"M1": 15, "M5": 30, "M15": 60, "M30": 60, "H1": 120, "H4": 300, "D1": 600}
LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "strategy-scores.json"
_SCORE_LOCK = threading.Lock()
_SCORE_CACHE: dict[str, tuple[float, dict[str, object]]] = {}
_SCORE_LOG: list[dict[str, object]] = []


class Level(TypedDict):
    price: float
    label: str
    kind: str


def build_chart(timeframe: str) -> dict[str, object]:
    timeframe = timeframe if timeframe in TIMEFRAMES else "M15"
    settings = read_settings()
    symbol = str(settings["symbol"] or "XAUUSDm")
    live = _load_live(symbol, timeframe)
    if live is None:
        bars = _sample_bars(240)
        times = _sample_times(len(bars), timeframe)
        orders = [_sample_order(bars)]
        quote = None
        source = "sample"
        note = "Chưa đọc được nến MetaTrader. Đang vẽ nến mẫu để xem chiến lược."
    else:
        bars, times, orders, quote = live
        source = "mt5"
        note = "Nến đóng lấy từ MetaTrader."

    closes = [bar[3] for bar in bars]
    ema9 = _ema(closes, 9)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    rsi = _rsi(closes, 14)
    atr = _atr(bars, 14)
    upper, middle, lower = _bollinger(closes, 20, 2.0)
    visible = 90
    start = max(0, len(bars) - visible)
    last_atr = _last_number(atr) or 1.0
    support, resistance = _thresholds(bars, last_atr)
    spread = None if quote is None else round(float(quote["ask"]) - float(quote["bid"]), 2)
    strategy, scored_at, every, score_in, score_log = _cached_strategy(
        symbol,
        bars,
        timeframe,
        support,
        resistance,
        spread,
        float(read_risk()["minRewardRatio"]),
        times,
    )
    window = slice(start, None)

    return {
        "source": source,
        "note": note,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": [{"open": bar[0], "high": bar[1], "low": bar[2], "close": bar[3]} for bar in bars[window]],
        "times": times[window],
        "ema9": _slice_numbers(ema9, start),
        "ema20": _slice_numbers(ema20, start),
        "ema50": _slice_numbers(ema50, start),
        "ema200": _slice_numbers(ema200, start),
        "bollingerUpper": _slice_numbers(upper, start),
        "bollingerMid": _slice_numbers(middle, start),
        "bollingerLower": _slice_numbers(lower, start),
        "rsi": _slice_numbers(rsi, start),
        "atr": round(last_atr, 2),
        "rsiNow": round(_last_number(rsi) or 0.0, 1),
        "support": support,
        "resistance": resistance,
        "swings": _visible_swings(bars, last_atr, start),
        "strategy": strategy,
        "strategyScoredAt": round(scored_at, 3),
        "strategyScoreEvery": every,
        "strategyScoreIn": score_in,
        "strategyLog": score_log,
        "orders": orders,
        "quote": quote,
    }


def _cached_strategy(
    symbol: str,
    bars: list[Bar],
    timeframe: str,
    support: float,
    resistance: float,
    spread: float | None,
    reward_ratio: float,
    times: list[int] | None = None,
) -> tuple[dict[str, object], float, int, int, list[dict[str, object]]]:
    every = SCORE_EVERY.get(timeframe, 60)
    key = symbol + "|" + timeframe
    now = time.time()
    with _SCORE_LOCK:
        _ensure_log()
        cached = _SCORE_CACHE.get(key)
        if cached is not None and now - cached[0] < every:
            scored_at, strategy = cached
        else:
            from services.api.strategies import evaluate_strategies

            seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}.get(timeframe, 900)
            fill_hour = None if not times else time.gmtime(int(times[-1]) + seconds).tm_hour
            strategy = evaluate_strategies(bars, timeframe, support, resistance, spread, reward_ratio, times, fill_hour)["selected"]
            scored_at = now
            _SCORE_CACHE[key] = (scored_at, strategy)
            _remember_score(symbol, timeframe, strategy, scored_at)
        remain = max(0, int(math.ceil(every - (now - scored_at))))
        log = [row for row in _SCORE_LOG if row["symbol"] == symbol and row["timeframe"] == timeframe]
    return strategy, scored_at, every, remain, log[-40:]


def _ensure_log() -> None:
    if _SCORE_LOG or not LOG_PATH.exists():
        return
    try:
        loaded = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(loaded, list):
        _SCORE_LOG.extend(row for row in loaded if isinstance(row, dict))


def _remember_score(symbol: str, timeframe: str, strategy: dict[str, object], scored_at: float) -> None:
    _SCORE_LOG.append(
        {
            "scoredAt": round(scored_at, 3),
            "symbol": symbol,
            "timeframe": timeframe,
            "name": strategy.get("name") or "Chưa chọn",
            "side": strategy.get("side") or "wait",
            "reason": strategy.get("reason") or "",
        }
    )
    del _SCORE_LOG[:-40]
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(_SCORE_LOG, ensure_ascii=False), encoding="utf-8")


def _load_live(symbol: str, timeframe: str) -> tuple[list[Bar], list[int], list[dict[str, float | str]], dict[str, float] | None] | None:
    password = read_password()
    if not password:
        return None
    settings = read_settings()
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None

    frame = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }[timeframe]
    try:
        from services.api.mt5_session import open_terminal

        with open_terminal() as mt5:
            return _rates_from_terminal(mt5, symbol, frame)
    except (RuntimeError, OSError):
        return None


def _rates_from_terminal(mt5: object, symbol: str, frame: int) -> tuple[list[Bar], list[int], list[dict[str, float | str]], dict[str, float] | None] | None:
    # Position 1: closed bars only, so the strategy card does not repaint with the forming bar.
    rates = mt5.copy_rates_from_pos(symbol, frame, 1, 600)
    if rates is None or len(rates) < 50:
        return None
    bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rates]
    times = [int(row["time"]) for row in rates]
    orders: list[dict[str, float | str]] = []
    positions = mt5.positions_get(symbol=symbol) or []
    for position in positions:
        orders.append(
            {
                "side": "buy" if int(position.type) == 0 else "sell",
                "entry": float(position.price_open),
                "stop": float(position.sl),
                "takeProfit": float(position.tp),
                "volume": float(position.volume),
                "magic": int(getattr(position, "magic", 0) or 0),
                "ticket": int(getattr(position, "ticket", 0) or 0),
                "profit": float(getattr(position, "profit", 0) or 0),
                "label": "Lệnh đang mở",
            }
        )
    tick = mt5.symbol_info_tick(symbol)
    quote = None if tick is None else {"bid": float(tick.bid), "ask": float(tick.ask)}
    return bars, times, orders, quote


def _sample_bars(count: int) -> list[Bar]:
    price = 2610.0
    bars: list[Bar] = []
    for index in range(count):
        drift = 0.42 if index < count - 14 else -0.62
        wave = math.sin(index / 5.5) * 1.15
        open_price = price
        close_price = open_price + drift + wave * 0.25
        high = max(open_price, close_price) + 0.85 + abs(math.sin(index / 2.2)) * 0.35
        low = min(open_price, close_price) - 0.72
        bars.append((round(open_price, 2), round(high, 2), round(low, 2), round(close_price, 2)))
        price = close_price
    return bars


def _sample_times(count: int, timeframe: str) -> list[int]:
    seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}[timeframe]
    end = int(time.time())
    return [end - (count - 1 - index) * seconds for index in range(count)]


def _sample_order(bars: list[Bar]) -> dict[str, float | str]:
    entry = bars[-18][3]
    return {
        "side": "buy",
        "entry": round(entry, 2),
        "stop": round(entry - 7.6, 2),
        "takeProfit": round(entry + 11.4, 2),
        "volume": 0.02,
        "label": "Lệnh mẫu",
    }


def _ema(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    seed = sum(values[:period]) / period
    output[period - 1] = seed
    weight = 2 / (period + 1)
    previous = seed
    for index in range(period, len(values)):
        previous = values[index] * weight + previous * (1 - weight)
        output[index] = previous
    return output


def _rsi(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return output
    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    average_gain = gains / period
    average_loss = losses / period
    output[period] = 100.0 if average_loss == 0 else 100 - 100 / (1 + average_gain / average_loss)
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        average_gain = (average_gain * (period - 1) + max(change, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-change, 0.0)) / period
        output[index] = 100.0 if average_loss == 0 else 100 - 100 / (1 + average_gain / average_loss)
    return output


def _atr(bars: list[Bar], period: int) -> list[float | None]:
    true_ranges = [bars[0][1] - bars[0][2]]
    for index in range(1, len(bars)):
        high, low, previous_close = bars[index][1], bars[index][2], bars[index - 1][3]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    output: list[float | None] = [None] * len(bars)
    if len(true_ranges) < period:
        return output
    current = sum(true_ranges[:period]) / period
    output[period - 1] = current
    for index in range(period, len(true_ranges)):
        current = (current * (period - 1) + true_ranges[index]) / period
        output[index] = current
    return output


def _bollinger(values: list[float], period: int, width: float) -> tuple[list[float | None], list[float | None], list[float | None]]:
    upper: list[float | None] = [None] * len(values)
    middle: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((item - mean) ** 2 for item in window) / period
        deviation = math.sqrt(variance)
        middle[index] = mean
        upper[index] = mean + width * deviation
        lower[index] = mean - width * deviation
    return upper, middle, lower


def _swing_points(bars: list[Bar], atr: float) -> list[dict[str, float | int | str]]:
    prominence = max(atr * 0.45, 0.6)
    span = 5
    points: list[dict[str, float | int | str]] = []
    for index in range(span, len(bars) - span):
        window = bars[index - span : index + span + 1]
        high = bars[index][1]
        low = bars[index][2]
        if high == max(bar[1] for bar in window) and high - min(bar[1] for bar in window) >= prominence:
            points.append({"index": index, "kind": "high", "price": round(high, 2)})
        if low == min(bar[2] for bar in window) and max(bar[2] for bar in window) - low >= prominence:
            points.append({"index": index, "kind": "low", "price": round(low, 2)})
    return points


def _visible_swings(bars: list[Bar], atr: float, start: int) -> list[dict[str, float | int | str]]:
    visible: list[dict[str, float | int | str]] = []
    for point in _swing_points(bars, atr):
        index = int(point["index"])
        if index < start:
            continue
        visible.append({"index": index - start, "kind": point["kind"], "price": point["price"]})
    return visible


def _thresholds(bars: list[Bar], atr: float) -> tuple[float, float]:
    price = bars[-1][3]
    band = max(atr * 0.5, 0.8)
    gap = max(atr, 1.0)
    points = _swing_points(bars, atr)
    highs = [float(point["price"]) for point in points if point["kind"] == "high"]
    lows = [float(point["price"]) for point in points if point["kind"] == "low"]
    support = _outside_level(_cluster(lows, band), price, gap, below=True)
    resistance = _outside_level(_cluster(highs, band), price, gap, below=False)
    if support is None:
        support = price - atr * 1.4
    if resistance is None:
        resistance = price + atr * 1.4
    return round(support, 2), round(resistance, 2)


def _outside_level(levels: list[float], price: float, gap: float, below: bool) -> float | None:
    if below:
        candidates = [level for level in levels if level <= price - gap]
        return max(candidates) if candidates else None
    candidates = [level for level in levels if level >= price + gap]
    return min(candidates) if candidates else None


def _cluster(levels: list[float], band: float) -> list[float]:
    if not levels:
        return []
    ordered = sorted(levels)
    groups: list[list[float]] = [[ordered[0]]]
    for level in ordered[1:]:
        if level - groups[-1][-1] <= band:
            groups[-1].append(level)
        else:
            groups.append([level])
    return [sum(group) / len(group) for group in groups]


def _last_number(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _slice_numbers(values: list[float | None], start: int) -> list[float | None]:
    return [None if value is None else round(value, 2) for value in values[start:]]
