Bar = tuple[float, float, float, float]

HIGHER = {
    "M1": ("M15", 15),
    "M5": ("M15", 3),
    "M15": ("H1", 4),
    "M30": ("H1", 2),
    "H1": ("H4", 4),
    "H4": ("D1", 6),
    "D1": ("D1", 1),
}
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
# Validated strategies first. A higher-priority card that is only analysis must never mask
# a validated one (the old order let "pullback" hide every "trend" signal in live trading).
PRIORITY = ("trend", "pullback", "breakout", "reversal", "range")
# Walk-forward on XAUUSDm 2021-2026 (M5..H4): only "trend" kept a positive expectancy in
# every timeframe and both the selection (before 2025) and test (2025-2026) periods.
LIVE_STRATEGIES = ("trend", "pullback")
# Candidates followed on paper in live (no orders) before they may be promoted.
SHADOW_STRATEGIES = ("breakout",)
SPREAD_LIMIT = 0.80
# Entries whose fill falls in 18:00-23:59 UTC (late New York, rollover) lost -0.35R per
# trade on average; spreads widen at rollover and liquidity is thin.
BLOCK_HOURS = (18, 19, 20, 21, 22, 23)
WINDOW = 600
# After the drawdown limit is hit, new entries pause this long, then resume once with the
# peak reset to current equity. A second hit stays locked until unlocked by hand.
DRAWDOWN_COOLDOWN_SECONDS = 48 * 3600
TREND_REWARD = 2.0
TREND_MAX_BARS = 48
# On these timeframes the trend trade has no fixed target: once 1R in profit the stop trails
# 3 ATR behind the best price, time stop 400 bars. Walk-forward on M15 (adx15, vol filter, late
# block): 2022-24 +0.054R/trade vs +0.027R for TP 2R/48 bars, 2025-26 +0.164R vs +0.082R, with a
# smaller drawdown in both. On M30 the fixed 2R target stays: the trail was worse in 2022-24.
TREND_TRAIL_FRAMES = ("M15",)
TREND_TRAIL_BARS = 400
# Pullback (redesigned 2026-11-07): RSI(2) dip inside the long trend with expanding volatility.
# Selected on M15 2022-24 only (120 configurations, 21 passed; their 2025-26 median +0.096R),
# chosen config +0.081R/trade 2022-24 and +0.134R 2025-26, positive with 2x spread. Taken only
# when trend has no signal: the M15 book went from R/DD 0.99 to 2.41 in 2022-24 (4.39 -> 4.01 in
# 2025-26, more total R) and from ~0.8 to ~1.1 trades a day.
PULLBACK_RSI_PERIOD = 2
PULLBACK_RSI_LEVEL = 20.0
PULLBACK_REWARD = 1.5
PULLBACK_MAX_BARS = 24
TREND_ADX = 15.0
# Signal-bar filters (2026-11-08), tested on the M15 trend + pullback book 2022-26: skipping trend
# signals whose bar body exceeds 1 ATR and pullback signals whose bar range is under 1 ATR took
# 2022-24 from +52.6R (DD 21.9R) to +61.6R (DD 16.4R) and 2025-26 from +82.4R to +98.3R; 2x spread
# still +88.1R. Neighbouring thresholds 0.9-1.1 all helped. About 12% fewer trades.
TREND_MAX_BODY_ATR = 1.0
# The body filter was tested on M15 only; on the M30 trend book it lowered return/drawdown.
TREND_BODY_FRAMES = ("M15",)
PULLBACK_MIN_RANGE_ATR = 1.0
SWEEP_NOTE = "Chỉ phân tích, không gửi lệnh thật: kiểm thử 2022–2026 trên M5–H4 cho kỳ vọng âm ở mọi năm."


def evaluate_strategies(
    bars: list[Bar],
    timeframe: str,
    support: float,
    resistance: float,
    spread: float | None = None,
    reward_ratio: float = 1.5,
    times: list[int] | None = None,
    hour: int | None = None,
    methods: bool = True,
) -> dict[str, object]:
    """Score every strategy on the last closed bar.

    methods: also score the research methods (services/api/methods). They are never chosen by
    the selector and never send orders; a backtest of another strategy skips them for speed.

    times: open time of each bar (UTC seconds). When given, the higher frame is built on
    clock boundaries, the same way the research engine and MetaTrader do.
    hour: UTC hour in which an order would be filled (the open of the next bar).
    """
    market = _market(bars, timeframe, support, resistance, spread, reward_ratio, times, hour)
    catalog = [
        _trend(market),
        _pullback(market),
        _breakout(market),
        _reversal(market),
        _range(market),
    ]
    if methods:
        from services.api.methods import evaluate_all

        catalog += evaluate_all(market)
    chosen = _choose(catalog)
    for item in catalog:
        item["chosen"] = item["id"] == chosen
        if item["chosen"] and item["status"] == "ready":
            item["status"] = "selected"
    facts = _facts(market)
    selected = _selected_payload(catalog, market)
    selected["facts"] = facts
    return {
        "selected": selected,
        "catalog": catalog,
        "higherTimeframe": market["higherName"],
        "facts": facts,
    }


def _choose(catalog: list[dict[str, object]]) -> str | None:
    ready = {str(item["id"]): item for item in catalog if item["status"] == "ready"}
    for name in PRIORITY:
        if name in ready:
            return name
    blocked = [item for item in catalog if item["status"] == "blocked" and item["side"] in {"buy", "sell"}]
    for name in PRIORITY:
        for item in blocked:
            if item["id"] == name:
                return str(item["id"])
    return None


def _selected_payload(catalog: list[dict[str, object]], market: dict[str, object]) -> dict[str, object]:
    chosen = next((item for item in catalog if item["chosen"]), None)
    price = float(market["price"])
    if chosen is None:
        return {
            "name": "Chưa chọn",
            "reason": "Chưa có chiến lược nào đủ điều kiện trên khung này.",
            "explanation": "Chưa chiến lược nào đủ điều kiện trên nến này.",
            "side": "wait",
            "confirmed": False,
            "entry": round(price, 2),
            "stop": round(price, 2),
            "takeProfit": round(price, 2),
            "timeframe": market["timeframe"],
            "higherTimeframe": market["higherName"],
            "rules": [],
            "catalog": catalog,
        }
    payload = dict(chosen)
    payload["reason"] = str(chosen["summary"])
    payload["timeframe"] = market["timeframe"]
    payload["higherTimeframe"] = market["higherName"]
    payload["catalog"] = catalog
    return payload


def _market(
    bars: list[Bar],
    timeframe: str,
    support: float,
    resistance: float,
    spread: float | None,
    reward_ratio: float,
    times: list[int] | None = None,
    hour: int | None = None,
) -> dict[str, object]:
    closes = [bar[3] for bar in bars]
    ema20_series = _ema(closes, 20)
    ema20 = _last(ema20_series)
    ema20_prev = ema20_series[-2] if len(ema20_series) >= 2 else None
    ema50 = _last(_ema(closes, 50))
    ema200 = _last(_ema(closes, 200))
    atr = _last(_atr(bars, 14)) or 1.0
    atr100 = _last(_atr(bars, 100))
    higher_name, factor = HIGHER.get(timeframe, ("H1", 4))
    if factor <= 1:
        higher_bars = bars
    elif times is not None and len(times) == len(bars):
        higher_bars = _aggregate_clock(bars, times, TF_SECONDS.get(timeframe, 900) * factor)
    else:
        higher_bars = _aggregate(bars, factor)
    higher_bias = _bias(higher_bars)
    recent_high = max(bar[1] for bar in bars[-20:])
    recent_low = min(bar[2] for bar in bars[-20:])
    adx = _adx(bars, 14)
    sideways = (recent_high - recent_low) < atr * 2.4 and ema20 is not None and ema50 is not None and abs(ema20 - ema50) < atr * 0.45
    if adx is not None and adx >= 25:
        sideways = False
    return {
        "bars": bars,
        "timeframe": timeframe,
        "higherName": higher_name if factor > 1 else "không có khung lớn hơn",
        "higherBias": higher_bias,
        "price": bars[-1][3],
        "ema20": ema20,
        "ema20Prev": ema20_prev,
        "ema50": ema50,
        "ema200": ema200,
        "atr": atr,
        "atr100": atr100,
        "expanding": atr100 is not None and atr >= atr100,
        "hour": hour,
        "adx": adx,
        "rsi": _last(_rsi(closes, 14)),
        "rsiFastPrev": (lambda series: series[-2] if len(series) >= 2 else None)(_rsi(closes, PULLBACK_RSI_PERIOD)),
        "support": support,
        "resistance": resistance,
        "spread": spread,
        "rewardRatio": reward_ratio if reward_ratio > 0 else 1.5,
        "sideways": sideways,
        "recentHigh": recent_high,
        "recentLow": recent_low,
        "times": times,
    }


def _trend(market: dict[str, object]) -> dict[str, object]:
    """Trend continuation after a shallow pullback, only while volatility is expanding.

    Buy: EMA20 > EMA50, close > EMA200, ADX >= 15, higher frame up, ATR14 >= ATR100,
    one of the three previous bars touched EMA20, the last three closes held above EMA50,
    and the closed bar is bullish and closes above the previous high. Mirror for sell.
    Stop beyond the 3-bar extreme + 0.3 ATR (0.8-3 ATR), target 2R, exit after 48 bars.
    """
    trail = str(market["timeframe"]) in TREND_TRAIL_FRAMES
    hold_bars = TREND_TRAIL_BARS if trail else TREND_MAX_BARS
    rules = _rules(
        "EMA 20 trên EMA 50, giá trên EMA 200 (ngược lại để bán), ADX từ 15, khung lớn cùng chiều và ATR 14 không thấp hơn ATR 100. "
        "Một trong ba nến trước đã chạm EMA 20, ba giá đóng gần nhất vẫn giữ EMA 50, rồi nến vừa đóng cùng chiều và đóng vượt đỉnh (hoặc đáy) nến trước.",
        "Không đặt chốt lời cố định. Khi lời từ 1R, cắt lỗ bám cách giá tốt nhất 3 ATR, cập nhật mỗi khi nến đóng; tối đa 400 nến."
        if trail
        else f"Chốt lời ở {_ratio_text(_trend_ratio(market))} lần khoảng cắt lỗ. Nếu sau {TREND_MAX_BARS} nến chưa chạm chốt lời hay cắt lỗ thì đóng lệnh.",
        "Giá đóng cửa cắt qua EMA 50 ngược chiều trước khi vào lệnh, hoặc khung lớn đổi chiều.",
        market,
        "ATR 14 phải từ ATR 100 trở lên, tức biến động đang mở rộng. Khi biến động co lại, chiến lược nghỉ.",
        hold_bars,
        "Được gửi lệnh thật trên M15, thoát bằng cắt lỗ bám. Kiểm thử XAUUSDm 2023–2026 trên M15: +0,12R mỗi lệnh, khoảng 0,8 lệnh mỗi ngày (chốt lời cố định 2R chỉ được +0,06R).",
        _trend_ratio(market),
    )
    alignment = _trend_alignment(market)
    adx = market["adx"]
    adx_text = "chưa đủ nến tính ADX" if adx is None else f"ADX {adx:.0f}"
    bars = market["bars"]
    name = "Theo xu hướng"
    if alignment is None:
        return _gated(_card("trend", name, "rest", "wait", False, "EMA chưa xếp cùng chiều.", f"Cần EMA 20 trên EMA 50 và giá trên EMA 200 để mua, hoặc ngược lại để bán. Hiện {_ema_sentence(market)} {adx_text}.", None, rules), market, 0)
    if adx is None or adx < TREND_ADX:
        return _gated(_card("trend", name, "rest", alignment, False, f"Xu hướng {_side_name(alignment)} nhưng {adx_text}, dưới {TREND_ADX:.0f}.", f"Các đường EMA đã xếp chiều {_side_name(alignment)}, nhưng xu hướng chưa đủ lực.", None, rules), market, 1)
    wanted = "up" if alignment == "buy" else "down"
    if market["higherBias"] != wanted:
        return _gated(_card("trend", name, "rest", alignment, False, f"Khung {market['higherName']} chưa cùng chiều {_side_name(alignment)}.", f"Khung {market['timeframe']} xếp chiều {_side_name(alignment)}, nhưng {_higher_sentence(market)} Chiến lược chỉ vào khi khung lớn cùng chiều.", None, rules), market, 2)
    atr = float(market["atr"])
    atr100 = market["atr100"]
    if not market["expanding"]:
        detail = "chưa đủ nến tính ATR 100" if atr100 is None else f"ATR 14 là {atr:.2f}, thấp hơn ATR 100 là {float(atr100):.2f}"
        return _gated(_card("trend", name, "rest", alignment, False, "Biến động đang co lại, chiến lược nghỉ.", f"{detail.capitalize()}. Kiểm thử cho thấy vào lệnh xu hướng khi biến động co lại bị lỗ, nên chỉ vào khi biến động mở rộng.", None, rules), market, 3)
    ema20_prev = market["ema20Prev"]
    ema50 = market["ema50"]
    if not isinstance(bars, list) or len(bars) < 5 or ema20_prev is None or ema50 is None:
        return _gated(_card("trend", name, "rest", "wait", False, "Chưa đủ nến để thấy nhịp hồi.", "Cần ít nhất năm nến có EMA 20 và EMA 50.", None, rules), market, 4)
    last, previous = bars[-1], bars[-2]
    prior = bars[-4:-1]
    recent = bars[-3:]
    if alignment == "buy":
        touched = min(bar[2] for bar in prior) <= float(ema20_prev)
        held = min(bar[3] for bar in recent) > float(ema50)
        trigger = last[3] > previous[1] and last[3] > last[0]
        extreme = min(bar[2] for bar in recent)
        distance = last[3] - extreme + atr * 0.3
        trigger_text = "nến tăng đóng vượt đỉnh nến trước"
    else:
        touched = max(bar[1] for bar in prior) >= float(ema20_prev)
        held = max(bar[3] for bar in recent) < float(ema50)
        trigger = last[3] < previous[2] and last[3] < last[0]
        extreme = max(bar[1] for bar in recent)
        distance = extreme - last[3] + atr * 0.3
        trigger_text = "nến giảm đóng thủng đáy nến trước"
    if not touched:
        return _gated(_card("trend", name, "rest", alignment, False, f"Xu hướng {_side_name(alignment)} còn, giá chưa hồi về EMA 20.", f"Không đuổi nến đã chạy. Ba nến trước chưa chạm EMA 20 ({float(ema20_prev):.2f}).", None, rules), market, 4)
    if not held:
        return _gated(_card("trend", name, "rest", alignment, False, "Nhịp hồi đã đóng cửa qua EMA 50.", f"Một trong ba giá đóng gần nhất đã vượt EMA 50 ({float(ema50):.2f}) ngược chiều, nhịp hồi quá sâu.", None, rules), market, 5)
    if not trigger:
        return _gated(_card("trend", name, "rest", alignment, False, "Giá đã hồi về EMA 20, chờ nến quay lại đúng chiều.", f"Chờ {trigger_text}.", None, rules), market, 6)
    body = abs(float(last[3]) - float(last[0]))
    if str(market["timeframe"]) in TREND_BODY_FRAMES and body > atr * TREND_MAX_BODY_ATR:
        return _gated(_card("trend", name, "rest", alignment, False, "Nến tín hiệu quá dài, bỏ qua.", f"Thân nến vừa đóng {body:.2f} dài hơn {TREND_MAX_BODY_ATR:g} ATR ({atr * TREND_MAX_BODY_ATR:.2f}). Kiểm thử 2022–2026: vào sau nến quá dài thì điểm vào xa và hay gặp nhịp chững, kỳ vọng âm.", None, rules), market, 7)
    distance = max(distance, atr * 0.8)
    if distance > atr * 3.0:
        return _gated(_card("trend", name, "rest", alignment, False, "Cắt lỗ quá xa so với biến động.", f"Khoảng cắt lỗ {distance:.2f} vượt 3 ATR ({atr * 3:.2f}). Bỏ qua để giữ rủi ro mỗi lệnh ổn định.", None, rules), market, 8)
    entry = float(last[3])
    ratio = _trend_ratio(market)
    prices = _priced(alignment, entry, distance, ratio)
    if trail:
        prices = (prices[0], prices[1], None)
    summary = f"Hồi về EMA 20 rồi {trigger_text}, xu hướng {_side_name(alignment)}, {adx_text}."
    explanation = (
        f"Xu hướng {_side_name(alignment)} còn hiệu lực vì EMA xếp cùng chiều, {adx_text}, {_higher_sentence(market)} "
        f"Biến động đang mở rộng (ATR 14 {atr:.2f} không thấp hơn ATR 100). Giá vừa hồi chạm EMA 20 mà vẫn giữ EMA 50, rồi {trigger_text}. "
        f"Điểm vào {entry:.2f}. Cắt lỗ ngoài đáy hoặc đỉnh ba nến cộng 0,3 ATR, tại {prices[1]:.2f}. "
        + (
            "Không đặt chốt lời: khi lời từ 1R, cắt lỗ bám cách giá tốt nhất 3 ATR. Đóng lệnh nếu giữ quá 400 nến."
            if trail
            else f"Chốt lời {prices[2]:.2f}, gấp {_ratio_text(ratio)} lần rủi ro. Đóng lệnh nếu sau {TREND_MAX_BARS} nến chưa chạm mức nào."
        )
    )
    card = _gated(_finish("trend", name, alignment, True, summary, explanation, prices, rules, market, hold_bars, "trail" if trail else "fixed"), market, len(TREND_GATES))
    card["pattern"] = "nến vượt đỉnh trước" if alignment == "buy" else "nến thủng đáy trước"
    return card


# Entry conditions of the live strategies, in the order the code checks them. Each card carries
# them as "gates" (ok / fail / wait = not reached / skip = not used on this frame), so the
# screens show exactly where a bar stopped instead of a made-up score.
TREND_GATES = (
    "EMA 20/50/200 xếp cùng chiều",
    f"ADX từ {TREND_ADX:.0f}",
    "Khung lớn cùng chiều",
    "Biến động mở rộng (ATR 14 ≥ ATR 100)",
    "Một trong ba nến trước chạm EMA 20",
    "Ba giá đóng gần nhất giữ EMA 50",
    "Nến đóng cùng chiều, vượt đỉnh/thủng đáy nến trước",
    f"Thân nến tín hiệu ≤ {TREND_MAX_BODY_ATR:g} ATR",
    "Cắt lỗ ≤ 3 ATR",
)
PULLBACK_GATES = (
    "Giá và EMA 50 cùng phía EMA 200",
    "Biến động mở rộng (ATR 14 ≥ ATR 100)",
    f"RSI({PULLBACK_RSI_PERIOD}) nến trước ≤ {PULLBACK_RSI_LEVEL:.0f} (≥ {100 - PULLBACK_RSI_LEVEL:.0f} để bán)",
    "Nến đóng vượt đỉnh/thủng đáy nến trước",
    f"Biên độ nến bật lại ≥ {PULLBACK_MIN_RANGE_ATR:g} ATR",
    "Cắt lỗ ≤ 3 ATR",
)
HOUR_GATE = "Giờ khớp ngoài 18–24 giờ UTC"


def _gated(card: dict[str, object], market: dict[str, object], failed: int) -> dict[str, object]:
    names = TREND_GATES if card["id"] == "trend" else PULLBACK_GATES
    skip = {7} if card["id"] == "trend" and str(market["timeframe"]) not in TREND_BODY_FRAMES else set()
    gates = [
        {"name": name, "state": "skip" if index in skip else "ok" if index < failed else "fail" if index == failed else "wait"}
        for index, name in enumerate(names)
    ]
    if failed >= len(names):
        hour = market.get("hour")
        gates.append({"name": HOUR_GATE, "state": "fail" if hour is not None and int(hour) in BLOCK_HOURS else "ok"})
    else:
        gates.append({"name": HOUR_GATE, "state": "wait"})
    card["gates"] = gates
    return card


def _trend_alignment(market: dict[str, object]) -> str | None:
    """EMA 20 against EMA 50 for direction, price against EMA 200 for the long trend."""
    ema20, ema50, ema200 = market["ema20"], market["ema50"], market["ema200"]
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    price = float(market["price"])
    if float(ema20) > float(ema50) and price > float(ema200):
        return "buy"
    if float(ema20) < float(ema50) and price < float(ema200):
        return "sell"
    return None


def _trend_ratio(market: dict[str, object]) -> float:
    return max(TREND_REWARD, _reward(market))


def _pullback(market: dict[str, object]) -> dict[str, object]:
    """Short dip inside the long trend. Buy: close above EMA200 and EMA50 above EMA200, RSI(2) of
    the previous bar at or below 20, the closed bar closes above the previous high, ATR14 >=
    ATR100. Mirror for sell. Stop beyond the 3-bar extreme + 0.3 ATR (0.8-3 ATR), target 1.5R,
    exit after 24 bars."""
    rules = _rules(
        "Giá trên EMA 200 và EMA 50 trên EMA 200 (ngược lại để bán), ATR 14 không thấp hơn ATR 100. "
        f"Nến trước có RSI({PULLBACK_RSI_PERIOD}) từ {PULLBACK_RSI_LEVEL:.0f} trở xuống (từ {100 - PULLBACK_RSI_LEVEL:.0f} trở lên để bán), rồi nến vừa đóng vượt đỉnh (thủng đáy) nến trước.",
        f"Chốt lời {_ratio_text(PULLBACK_REWARD)} lần khoảng cắt lỗ. Nếu sau {PULLBACK_MAX_BARS} nến chưa chạm mức nào thì đóng lệnh.",
        "Giá đóng cửa qua EMA 200 ngược chiều trước khi vào lệnh.",
        market,
        "ATR 14 phải từ ATR 100 trở lên. Khi biến động co lại, chiến lược nghỉ.",
        PULLBACK_MAX_BARS,
        "Được gửi lệnh thật khi Theo xu hướng không có tín hiệu. Kiểm thử XAUUSDm M15: chọn trên 2022–2024 (+0,08R mỗi lệnh), kiểm tra 2025–2026 (+0,13R mỗi lệnh).",
        PULLBACK_REWARD,
    )
    name = "Hồi giá"
    ema50, ema200 = market["ema50"], market["ema200"]
    rsi_prev = market["rsiFastPrev"]
    bars = market["bars"]
    price = float(market["price"])
    atr = float(market["atr"])
    if ema50 is None or ema200 is None or rsi_prev is None or not isinstance(bars, list) or len(bars) < 3:
        return _gated(_card("pullback", name, "rest", "wait", False, "Chưa đủ nến để tính EMA 200 và RSI.", "Cần đủ nến để tính EMA 200, EMA 50 và RSI(2).", None, rules), market, 0)
    if price > float(ema200) and float(ema50) > float(ema200):
        side = "buy"
    elif price < float(ema200) and float(ema50) < float(ema200):
        side = "sell"
    else:
        return _gated(_card("pullback", name, "rest", "wait", False, "Chưa có xu hướng dài.", f"Cần giá và EMA 50 cùng phía EMA 200 ({float(ema200):.2f}).", None, rules), market, 0)
    if not market["expanding"]:
        return _gated(_card("pullback", name, "rest", side, False, "Biến động đang co lại, chiến lược nghỉ.", "ATR 14 thấp hơn ATR 100. Kiểm thử cho thấy nhịp hồi khi biến động co lại không có lợi thế.", None, rules), market, 1)
    dipped = float(rsi_prev) <= PULLBACK_RSI_LEVEL if side == "buy" else float(rsi_prev) >= 100 - PULLBACK_RSI_LEVEL
    if not dipped:
        return _gated(_card("pullback", name, "rest", side, False, f"Xu hướng {_side_name(side)}, chờ một nhịp hồi ngắn.", f"RSI({PULLBACK_RSI_PERIOD}) nến trước là {float(rsi_prev):.0f}, chưa {'xuống' if side == 'buy' else 'lên'} tới {PULLBACK_RSI_LEVEL if side == 'buy' else 100 - PULLBACK_RSI_LEVEL:.0f}.", None, rules), market, 2)
    last, previous = bars[-1], bars[-2]
    recent = bars[-3:]
    if side == "buy":
        trigger = last[3] > previous[1]
        distance = last[3] - min(bar[2] for bar in recent) + atr * 0.3
        trigger_text = "nến vừa đóng vượt đỉnh nến trước"
    else:
        trigger = last[3] < previous[2]
        distance = max(bar[1] for bar in recent) - last[3] + atr * 0.3
        trigger_text = "nến vừa đóng thủng đáy nến trước"
    if not trigger:
        return _gated(_card("pullback", name, "rest", side, False, "Đã có nhịp hồi, chờ nến quay lại đúng chiều.", f"RSI({PULLBACK_RSI_PERIOD}) nến trước {float(rsi_prev):.0f}. Chờ {trigger_text.replace('nến vừa đóng ', 'nến đóng ')}.", None, rules), market, 3)
    span = float(last[1]) - float(last[2])
    if span < atr * PULLBACK_MIN_RANGE_ATR:
        return _gated(_card("pullback", name, "rest", side, False, "Nến bật lại quá yếu, bỏ qua.", f"Biên độ nến vừa đóng {span:.2f} nhỏ hơn {PULLBACK_MIN_RANGE_ATR:g} ATR ({atr * PULLBACK_MIN_RANGE_ATR:.2f}). Kiểm thử 2022–2026: nhịp hồi bật lại bằng nến nhỏ chưa có lực, kỳ vọng âm.", None, rules), market, 4)
    distance = max(distance, atr * 0.8)
    if distance > atr * 3.0:
        return _gated(_card("pullback", name, "rest", side, False, "Cắt lỗ quá xa so với biến động.", f"Khoảng cắt lỗ {distance:.2f} vượt 3 ATR ({atr * 3:.2f}).", None, rules), market, 5)
    entry = float(last[3])
    prices = _priced(side, entry, distance, PULLBACK_REWARD)
    summary = f"Nhịp hồi ngắn trong xu hướng {_side_name(side)} (RSI({PULLBACK_RSI_PERIOD}) {float(rsi_prev):.0f}), {trigger_text}."
    explanation = (
        f"Xu hướng dài {_side_name(side)}: giá và EMA 50 cùng phía EMA 200 ({float(ema200):.2f}), biến động đang mở rộng. "
        f"Nến trước hồi mạnh ngược chiều (RSI({PULLBACK_RSI_PERIOD}) {float(rsi_prev):.0f}), rồi {trigger_text}. "
        f"Điểm vào {entry:.2f}. Cắt lỗ ngoài đáy hoặc đỉnh ba nến cộng 0,3 ATR, tại {prices[1]:.2f}. "
        f"Chốt lời {prices[2]:.2f}, gấp {_ratio_text(PULLBACK_REWARD)} lần rủi ro. Đóng lệnh nếu sau {PULLBACK_MAX_BARS} nến chưa chạm mức nào."
    )
    card = _gated(_finish("pullback", name, side, True, summary, explanation, prices, rules, market, PULLBACK_MAX_BARS), market, len(PULLBACK_GATES))
    card["pattern"] = "nhịp hồi RSI(2)"
    return card


def _breakout(market: dict[str, object]) -> dict[str, object]:
    """Close out of a 12-bar squeeze (<= 2.5 ATR) with a strong body, with the higher frame
    and with expanding volatility. Stop beyond the box middle, chandelier trail of 3 ATR
    once the trade is 1R in profit."""
    rules = _rules(
        "12 nến trước nén trong biên độ không quá 2,5 ATR. Nến vừa đóng phá ra ngoài, thân từ nửa ATR, đóng ở phần ba ngoài cùng, cùng chiều khung lớn và ATR 14 không thấp hơn ATR 100.",
        "Khi lệnh lời từ 1R, cắt lỗ bám theo đỉnh (đáy) cao nhất trừ 3 ATR. Không đặt chốt lời cố định.",
        "Giá quay về giữa vùng nén. Đó là phá giả.",
        market,
        "Chỉ xét sau một vùng nén và khi biến động đang mở rộng.",
        400,
        "Chỉ phân tích, không gửi lệnh thật: kiểm thử M30 và H1 dương nhẹ nhưng M15 hòa vốn và chỉ khoảng 30 lệnh mỗi năm.",
    )
    for rule in rules:
        if rule["label"] in {"Chốt lời", "Tỷ lệ lời"}:
            rule["value"] = "Không cố định. Cắt lỗ bám 3 ATR sau khi lệnh lời từ 1R."
    bars = market["bars"]
    name = "Phá vùng"
    if not isinstance(bars, list) or len(bars) < 14:
        return _card("breakout", name, "rest", "wait", False, "Chưa đủ nến để thấy vùng nén.", "Cần ít nhất 12 nến đi ngang trước nến phá.", None, rules)
    box = bars[-13:-1]
    last = bars[-1]
    box_high = max(bar[1] for bar in box)
    box_low = min(bar[2] for bar in box)
    atr = float(market["atr"])
    if (box_high - box_low) > atr * 2.5:
        return _card("breakout", name, "rest", "wait", False, "12 nến gần nhất chưa tạo vùng nén.", f"Biên độ vùng là {box_high - box_low:.2f}, rộng hơn 2,5 ATR ({atr * 2.5:.2f}). Phá vùng chỉ bật sau một đoạn đi ngang.", None, rules)
    broke_up = last[3] > box_high and last[3] > last[0]
    broke_down = last[3] < box_low and last[3] < last[0]
    if not broke_up and not broke_down:
        return _card("breakout", name, "rest", "wait", False, f"Đang có vùng nén {box_low:.2f} – {box_high:.2f}, chưa bị phá.", "Giá vẫn nằm trong vùng 12 nến. Chiến lược chờ một nến đóng cửa ra ngoài biên, cùng chiều với thân nến.", None, rules)
    side = "buy" if broke_up else "sell"
    span = max(last[1] - last[2], 0.01)
    close_pos = (last[3] - last[2]) / span
    strong_close = close_pos >= 0.70 if side == "buy" else close_pos <= 0.30
    body = abs(last[3] - last[0])
    if body < atr * 0.5 or not strong_close:
        return _card("breakout", name, "rest", side, False, "Giá có chọc qua biên nhưng thân nến yếu, coi là phá giả.", f"Thân nến {body:.2f}, trong khi nửa ATR là {atr * 0.5:.2f}. Nến phá cần đóng ở phần ba ngoài cùng của chính nó.", None, rules)
    wanted = "up" if side == "buy" else "down"
    if market["higherBias"] != wanted:
        return _card("breakout", name, "rest", side, False, f"Phá vùng chiều {_side_name(side)} nhưng khung lớn chưa cùng chiều.", f"{_higher_sentence(market)} Phá vùng ngược khung lớn dễ là phá giả.", None, rules)
    if not market["expanding"]:
        return _card("breakout", name, "rest", side, False, "Phá vùng khi biến động đang co lại.", "ATR 14 thấp hơn ATR 100. Chiến lược chỉ nhận phá vùng khi biến động mở rộng.", None, rules)
    entry = float(last[3])
    middle = (box_high + box_low) / 2
    distance = max(abs(entry - middle) + atr * 0.2, atr * 0.8)
    if distance > atr * 3.0:
        return _card("breakout", name, "rest", side, False, "Cắt lỗ quá xa so với biến động.", f"Khoảng cắt lỗ {distance:.2f} vượt 3 ATR.", None, rules)
    stop = entry - distance if side == "buy" else entry + distance
    prices = (round(entry, 2), round(stop, 2), None)
    summary = f"Nến đóng cửa phá vùng nén theo chiều {_side_name(side)}, cùng chiều khung lớn."
    explanation = (
        f"12 nến trước tạo vùng {box_low:.2f} – {box_high:.2f}, biên độ không quá 2,5 ATR. "
        f"Nến vừa đóng ra ngoài biên chiều {_side_name(side)}, thân nến {body:.2f} đạt trên nửa ATR và giá đóng ở phần mạnh của nến. "
        f"Điểm vào {entry:.2f}. Cắt lỗ qua giữa vùng nén, tại {stop:.2f}. Khi lời từ 1R, cắt lỗ bám 3 ATR theo giá."
    )
    card = _finish("breakout", name, side, True, summary, explanation, prices, rules, market, 400, "trail")
    return card


def _reversal(market: dict[str, object]) -> dict[str, object]:
    rules = _rules(
        "Giá quét qua hỗ trợ hoặc kháng cự rồi đóng lại trong vùng. Cần sao mai, sao hôm, nhíp, búa hoặc nhấn chìm đúng chiều.",
        "Chốt lời theo tỷ lệ lời đã cấu hình. Thoát nếu giá phá đỉnh hoặc đáy của cú quét.",
        "Giá vượt đỉnh hoặc đáy cú quét. Cú quét khi đó đã thất bại.",
        market,
        "Cần một cú quét thanh khoản. RSI dưới 30 hoặc trên 70 là dấu hiệu kiệt sức, không bắt buộc nhưng được ghi vào giải thích.",
        8,
        SWEEP_NOTE,
    )
    bars = market["bars"]
    if not isinstance(bars, list) or len(bars) < 3:
        return _card("reversal", "Đảo chiều", "rest", "wait", False, "Chưa đủ nến để thấy cú quét.", "Cần nến hiện tại và nến ngay trước để xác nhận đảo chiều.", None, rules)
    last = bars[-1]
    recent = bars[-3:]
    support = float(market["support"])
    resistance = float(market["resistance"])
    rsi = market["rsi"]
    swept_low = min(bar[2] for bar in recent) < support and last[3] > support
    swept_high = max(bar[1] for bar in recent) > resistance and last[3] < resistance
    if not swept_low and not swept_high:
        rsi_text = "RSI chưa tính được." if rsi is None else f"RSI hiện {float(rsi):.0f}."
        return _card("reversal", "Đảo chiều", "rest", "wait", False, "Chưa có cú quét qua hỗ trợ hoặc kháng cự.", f"Đảo chiều cần giá chọc ra ngoài ngưỡng rồi đóng lại bên trong. {rsi_text}", None, rules)
    side = "buy" if swept_low else "sell"
    exhausted = rsi is not None and ((side == "buy" and float(rsi) <= 30) or (side == "sell" and float(rsi) >= 70))
    pattern = _pattern(market, side, "reversal")
    if pattern is None:
        return _card("reversal", "Đảo chiều", "rest", side, False, "Đã có cú quét nhưng chưa có mẫu nến đảo.", "Chờ sao mai, đáy nhíp, búa hoặc nhấn chìm tăng nếu mua. Chờ sao hôm, đỉnh nhíp, sao băng hoặc nhấn chìm giảm nếu bán.", None, rules)
    entry = float(last[3])
    atr = float(market["atr"])
    extreme = min(bar[2] for bar in recent) if side == "buy" else max(bar[1] for bar in recent)
    risk = max(abs(entry - extreme) + atr * 0.2, 0.5)
    prices = _priced(side, entry, risk, _reward(market))
    rsi_sentence = "RSI chưa ở vùng kiệt sức, cú quét vẫn được nhận." if not exhausted else f"RSI {float(rsi):.0f} nằm ở vùng kiệt sức, củng cố nhịp đảo."
    summary = f"Mẫu {pattern} sau cú quét, chiều {_side_name(side)}."
    explanation = (
        f"Đảo chiều tìm chỗ thanh khoản bị quét. Giá đã chọc {'dưới hỗ trợ ' + format(support, '.2f') if side == 'buy' else 'trên kháng cự ' + format(resistance, '.2f')} "
        f"rồi đóng lại trong vùng bằng mẫu {pattern}. {rsi_sentence} "
        f"Điểm vào {entry:.2f}. Cắt lỗ nằm ngoài đầu cú quét, tại {prices[1]:.2f}. "
        f"Kế hoạch hết hiệu lực nếu giá quay lại phá đầu cú quét đó."
    )
    card = _finish("reversal", "Đảo chiều", side, True, summary, explanation, prices, rules, market, 8)
    card["pattern"] = pattern
    return card


def _range(market: dict[str, object]) -> dict[str, object]:
    rules = _rules(
        "ADX dưới 20, biên độ 20 nến không quá 2,4 ATR và EMA 20 sát EMA 50. Mua khi nến chạm đáy vùng 20 nến rồi đóng tăng, bán khi chạm đỉnh vùng rồi đóng giảm.",
        "Chốt ở biên đối diện nếu còn đủ tỷ lệ lời đã cấu hình. Nếu không đủ, chiến lược này nghỉ.",
        "ADX từ 25, hoặc biên độ 20 nến nới quá 3 ATR. Lúc đó chiến lược đi ngang bị tắt.",
        market,
        "Tắt khi ADX từ 25 hoặc biên độ mở rộng. Không đánh ở giữa vùng.",
        16,
        "Chỉ phân tích, không gửi lệnh thật: đánh ngược về giữa vùng trên vàng cho kỳ vọng âm ở mọi năm 2022–2026.",
    )
    adx = market["adx"]
    atr = float(market["atr"])
    bars = market["bars"]
    if not isinstance(bars, list) or len(bars) < 22:
        return _card("range", "Đi ngang", "rest", "wait", False, "Chưa đủ nến để thấy vùng đi ngang.", "Cần ít nhất 21 nến.", None, rules)
    box = bars[-21:-1]
    floor = min(bar[2] for bar in box)
    ceiling = max(bar[1] for bar in box)
    width = ceiling - floor
    if adx is not None and adx >= 25:
        return _card("range", "Đi ngang", "blocked", "wait", False, f"Đang tắt vì ADX {adx:.0f} từ 25 trở lên.", "Thị trường có xu hướng đủ mạnh. Chiến lược đi ngang bị tắt để tránh bán đáy hoặc mua đỉnh của một xu hướng.", None, rules)
    if width > atr * 3:
        return _card("range", "Đi ngang", "blocked", "wait", False, "Đang tắt vì biên độ 20 nến đã nới quá 3 ATR.", f"Biên độ {width:.2f} lớn hơn {atr * 3:.2f}. Vùng đi ngang không còn rõ.", None, rules)
    if not market["sideways"]:
        adx_text = "ADX chưa tính được." if adx is None else f"ADX {adx:.0f}."
        return _card("range", "Đi ngang", "rest", "wait", False, "Chưa phải thị trường đi ngang.", f"Cần ADX dưới 20, biên độ 20 nến dưới 2,4 ATR và EMA 20 sát EMA 50. {adx_text} {_ema_sentence(market)}", None, rules)
    last = bars[-1]
    # The old version compared price with support/resistance levels that are, by construction,
    # at least one ATR away from price, so it could never fire. Use the 20-bar box instead.
    buy_reaction = last[2] <= floor + atr * 0.35 and last[3] > last[0] and last[3] > floor
    sell_reaction = last[1] >= ceiling - atr * 0.35 and last[3] < last[0] and last[3] < ceiling
    if not buy_reaction and not sell_reaction:
        return _card("range", "Đi ngang", "rest", "wait", False, "Đang đi ngang nhưng giá chưa phản ứng tại biên.", f"Vùng {floor:.2f} – {ceiling:.2f}. Giá {float(last[3]):.2f} chưa chạm sát một biên và đóng nến ngược lại.", None, rules)
    side = "buy" if buy_reaction else "sell"
    entry = float(last[3])
    stop = min(floor, last[2]) - atr * 0.3 if side == "buy" else max(ceiling, last[1]) + atr * 0.3
    risk = max(abs(entry - stop), atr * 0.5)
    opposite = ceiling if side == "buy" else floor
    reward = abs(opposite - entry)
    ratio = _reward(market)
    if reward < risk * ratio:
        return _card("range", "Đi ngang", "rest", side, False, f"Có phản ứng tại biên nhưng khoảng tới biên kia chưa đủ 1:{_ratio_label(market)}.", f"Từ {entry:.2f} tới biên đối diện chỉ được {reward:.2f}, trong khi {_ratio_label(market)} lần rủi ro là {risk * ratio:.2f}.", None, rules)
    prices = (round(entry, 2), round(entry - risk, 2) if side == "buy" else round(entry + risk, 2), round(opposite, 2))
    summary = f"Giá phản ứng tại {'đáy' if side == 'buy' else 'đỉnh'} vùng đi ngang, chiều {_side_name(side)}."
    explanation = (
        f"Đi ngang được bật vì ADX dưới 20, biên độ 20 nến là {width:.2f} và hai EMA ngắn nằm sát nhau. "
        f"Giá chạm {'đáy' if side == 'buy' else 'đỉnh'} vùng rồi đóng nến ngược lại vào trong. "
        f"Điểm vào {entry:.2f}. Cắt lỗ ngoài biên 0,3 ATR. Chốt lời tại biên đối diện {opposite:.2f}."
    )
    return _finish("range", "Đi ngang", side, True, summary, explanation, prices, rules, market, 16)


def _finish(
    strategy_id: str,
    name: str,
    side: str,
    confirmed: bool,
    summary: str,
    explanation: str,
    prices: tuple[float, float, float | None],
    rules: list[dict[str, str]],
    market: dict[str, object],
    max_bars: int = 8,
    manage: str = "fixed",
) -> dict[str, object]:
    status = "ready"
    spread = market["spread"]
    hour = market.get("hour")
    if spread is not None and float(spread) > SPREAD_LIMIT:
        status = "blocked"
        confirmed = False
        summary = f"Chênh lệch {float(spread):.2f} rộng hơn 0,80. " + summary
        explanation = f"Bộ lọc chênh lệch đang chặn vào lệnh vì chênh lệch giá là {float(spread):.2f}, trên mức 0,80. " + explanation
    elif hour is not None and int(hour) in BLOCK_HOURS:
        status = "blocked"
        confirmed = False
        summary = f"Giờ khớp {int(hour):02d}:00 UTC nằm trong khung 18–24 giờ bị chặn. " + summary
        explanation = (
            "Bộ lọc giờ đang chặn: lệnh vào từ 18 giờ đến hết 23 giờ UTC (cuối phiên Mỹ, giờ qua đêm) "
            "có kỳ vọng âm trong kiểm thử và chênh lệch hay giãn rộng. " + explanation
        )
    card = _card(strategy_id, name, status, side, confirmed, summary, explanation, prices, rules)
    card["maxBars"] = max_bars
    card["manage"] = manage
    card["live"] = strategy_id in LIVE_STRATEGIES
    return card


def _card(
    strategy_id: str,
    name: str,
    status: str,
    side: str,
    confirmed: bool,
    summary: str,
    explanation: str,
    prices: tuple[float, float, float | None] | None,
    rules: list[dict[str, str]],
) -> dict[str, object]:
    entry = stop = take = None
    if prices is not None:
        entry, stop, take = prices
    return {
        "id": strategy_id,
        "name": name,
        "status": status,
        "chosen": False,
        "side": side if status in {"ready", "blocked"} else "wait",
        "confirmed": confirmed if status == "ready" else False,
        "summary": summary,
        "explanation": explanation,
        "entry": entry,
        "stop": stop,
        "takeProfit": take,
        "rules": rules,
        "live": strategy_id in LIVE_STRATEGIES,
    }


def _rules(
    entry: str,
    exit_rule: str,
    invalid: str,
    market: dict[str, object],
    volatility: str,
    max_bars: int = 8,
    live_note: str = "",
    ratio: float | None = None,
) -> list[dict[str, str]]:
    higher = str(market["higherName"])
    frame = str(market["timeframe"])
    ratio_text = _ratio_label(market) if ratio is None else _ratio_text(ratio)
    hold = f"Tối đa {max_bars} nến {frame}." if max_bars < 400 else "Không giới hạn, thoát theo cắt lỗ bám."
    return [
        {"label": "Vào lệnh", "value": entry},
        {"label": "Thoát lệnh", "value": exit_rule},
        {"label": "Cắt lỗ", "value": "Theo khoảng cách ghi trong giải thích, luôn nằm ngoài vùng vô hiệu."},
        {"label": "Chốt lời", "value": f"{ratio_text} lần khoảng cắt lỗ."},
        {"label": "Tỷ lệ lời", "value": f"1 : {ratio_text}"},
        {"label": "Khung thời gian", "value": f"Tín hiệu trên {frame}. Khung đối chiếu: {higher}."},
        {"label": "Chênh lệch", "value": "Chỉ vào khi chênh lệch giá không quá 0,80."},
        {"label": "Giờ vào lệnh", "value": "Không vào lệnh từ 18 giờ đến hết 23 giờ UTC."},
        {"label": "Biến động", "value": volatility},
        {"label": "Thời gian giữ", "value": hold},
        {"label": "Hủy kế hoạch", "value": invalid},
        {"label": "Lệnh thật", "value": live_note or "Chỉ phân tích, không gửi lệnh thật."},
    ]


def _facts(market: dict[str, object]) -> dict[str, object]:
    alignment = _alignment(market)
    ema20 = market["ema20"]
    ema50 = market["ema50"]
    price = float(market["price"])
    atr = float(market["atr"])
    pulled = False
    if alignment in {"buy", "sell"} and ema20 is not None and ema50 is not None:
        pulled = (alignment == "buy" and float(ema50) < price <= float(ema20) + atr * 0.15) or (
            alignment == "sell" and float(ema20) - atr * 0.15 <= price < float(ema50)
        )
    pattern = _pattern(market, alignment, "trend") if pulled and alignment in {"buy", "sell"} else None
    adx = market["adx"]
    return {
        "alignment": alignment or "none",
        "adx": None if adx is None else round(float(adx), 1),
        "sideways": bool(market["sideways"]),
        "higherBias": market["higherBias"],
        "higherName": market["higherName"],
        "pulled": pulled,
        "pattern": pattern or "",
        "label": _market_label(bool(market["sideways"]), alignment, pulled),
        "trendSide": _trend_alignment(market) or "none",
        "expanding": bool(market["expanding"]),
        "hourBlocked": market.get("hour") is not None and int(market["hour"]) in BLOCK_HOURS,
    }


def _market_label(sideways: bool, alignment: str | None, pulled: bool) -> str:
    if sideways:
        return "Đi ngang"
    if alignment == "buy" and pulled:
        return "Hồi trong tăng"
    if alignment == "sell" and pulled:
        return "Hồi trong giảm"
    if alignment == "buy":
        return "Tăng"
    if alignment == "sell":
        return "Giảm"
    return "Chưa xếp xu hướng"


def _alignment(market: dict[str, object]) -> str | None:
    ema20, ema50, ema200 = market["ema20"], market["ema50"], market["ema200"]
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    if float(ema20) > float(ema50) > float(ema200):
        return "buy"
    if float(ema20) < float(ema50) < float(ema200):
        return "sell"
    return None


def _higher_opposes(market: dict[str, object], side: str) -> bool:
    bias = market["higherBias"]
    return (side == "buy" and bias == "down") or (side == "sell" and bias == "up")


def _higher_sentence(market: dict[str, object]) -> str:
    name = str(market["higherName"])
    bias = market["higherBias"]
    if bias == "unknown":
        return f"Chưa đủ nến để đọc khung {name}."
    if name == "không có khung lớn hơn":
        return "Khung này không có khung lớn hơn để đối chiếu."
    label = {"up": "tăng", "down": "giảm", "flat": "chưa có xu hướng rõ"}[str(bias)]
    return f"Khung {name} đang {label}."


def _ema_sentence(market: dict[str, object]) -> str:
    ema20, ema50, ema200 = market["ema20"], market["ema50"], market["ema200"]
    if ema20 is None or ema50 is None or ema200 is None:
        return "chưa đủ nến để xếp EMA 20, 50 và 200."
    return f"EMA 20 ở {float(ema20):.2f}, EMA 50 ở {float(ema50):.2f}, EMA 200 ở {float(ema200):.2f}."


def _pattern(market: dict[str, object], side: str, kind: str) -> str | None:
    bars = market["bars"]
    if not isinstance(bars, list) or len(bars) < 2 or side not in {"buy", "sell"}:
        return None
    last, previous = bars[-1], bars[-2]
    atr = float(market["atr"])
    if kind == "trend":
        names = (("búa", _hammer(last)), ("nhấn chìm tăng", _engulfing(previous, last, "buy")), ("sao mai", _star(bars, "buy")))
        if side == "sell":
            names = (("sao băng", _shooting_star(last)), ("nhấn chìm giảm", _engulfing(previous, last, "sell")), ("sao hôm", _star(bars, "sell")))
    else:
        names = (
            ("sao mai", _star(bars, "buy")),
            ("đáy nhíp", _tweezer(previous, last, "buy", atr)),
            ("búa", _hammer(last)),
            ("nhấn chìm tăng", _engulfing(previous, last, "buy")),
        )
        if side == "sell":
            names = (
                ("sao hôm", _star(bars, "sell")),
                ("đỉnh nhíp", _tweezer(previous, last, "sell", atr)),
                ("sao băng", _shooting_star(last)),
                ("nhấn chìm giảm", _engulfing(previous, last, "sell")),
            )
    for name, matched in names:
        if matched:
            return name
    return None


def _hammer(bar: Bar) -> bool:
    body = abs(bar[3] - bar[0])
    span = max(bar[1] - bar[2], 1e-9)
    lower = min(bar[0], bar[3]) - bar[2]
    upper = bar[1] - max(bar[0], bar[3])
    return bar[3] >= bar[0] and lower >= max(body * 2, span * 0.5) and upper <= max(body, span * 0.2)


def _shooting_star(bar: Bar) -> bool:
    body = abs(bar[3] - bar[0])
    span = max(bar[1] - bar[2], 1e-9)
    upper = bar[1] - max(bar[0], bar[3])
    lower = min(bar[0], bar[3]) - bar[2]
    return bar[3] <= bar[0] and upper >= max(body * 2, span * 0.5) and lower <= max(body, span * 0.2)


def _engulfing(previous: Bar, last: Bar, side: str) -> bool:
    if side == "buy":
        return previous[3] < previous[0] and last[3] > last[0] and last[0] <= previous[3] and last[3] >= previous[0] and abs(last[3] - last[0]) > abs(previous[3] - previous[0])
    return previous[3] > previous[0] and last[3] < last[0] and last[0] >= previous[3] and last[3] <= previous[0] and abs(last[3] - last[0]) > abs(previous[3] - previous[0])


def _star(bars: list[Bar], side: str) -> bool:
    if len(bars) < 3:
        return False
    first, middle, last = bars[-3], bars[-2], bars[-1]
    first_body = abs(first[3] - first[0])
    if first_body <= 0 or abs(middle[3] - middle[0]) > first_body * 0.5:
        return False
    midpoint = (first[0] + first[3]) / 2
    if side == "buy":
        return first[3] < first[0] and last[3] > last[0] and last[3] >= midpoint
    return first[3] > first[0] and last[3] < last[0] and last[3] <= midpoint


def _tweezer(previous: Bar, last: Bar, side: str, atr: float) -> bool:
    tolerance = max(atr * 0.1, 0.05)
    if side == "buy":
        return abs(previous[2] - last[2]) <= tolerance and last[3] > last[0]
    return abs(previous[1] - last[1]) <= tolerance and last[3] < last[0]


def _confirmed(market: dict[str, object], side: str) -> bool:
    bars = market["bars"]
    if not isinstance(bars, list) or len(bars) < 2:
        return False
    last, previous = bars[-1], bars[-2]
    if side == "buy":
        return last[3] > previous[1]
    if side == "sell":
        return last[3] < previous[2]
    return False


def _confirm_sentence(confirmed: bool) -> str:
    if confirmed:
        return "Nến đã xác nhận: giá đóng vượt đỉnh nến trước nếu mua, hoặc thủng đáy nến trước nếu bán."
    return "Nến chưa xác nhận, nên đây mới là kế hoạch, chưa phải lệnh."


def _side_name(side: str) -> str:
    if side == "buy":
        return "mua"
    if side == "sell":
        return "bán"
    return "chờ"


def _reward(market: dict[str, object]) -> float:
    try:
        ratio = float(market["rewardRatio"])
    except (TypeError, ValueError, KeyError):
        ratio = 1.5
    return ratio if ratio > 0 else 1.5


def _ratio_label(market: dict[str, object]) -> str:
    text = f"{_reward(market):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _atr_prices(market: dict[str, object], side: str, entry: float, atr: float) -> tuple[float, float, float]:
    return _priced(side, entry, max(atr * 1.2, 0.5), _reward(market))


def _priced(side: str, entry: float, risk: float, ratio: float) -> tuple[float, float, float]:
    if side == "buy":
        return (round(entry, 2), round(entry - risk, 2), round(entry + risk * ratio, 2))
    return (round(entry, 2), round(entry + risk, 2), round(entry - risk * ratio, 2))


def _aggregate(bars: list[Bar], factor: int) -> list[Bar]:
    usable = (len(bars) // factor) * factor
    trimmed = bars[-usable:] if usable else []
    output: list[Bar] = []
    for index in range(0, len(trimmed), factor):
        chunk = trimmed[index : index + factor]
        output.append((chunk[0][0], max(bar[1] for bar in chunk), min(bar[2] for bar in chunk), chunk[-1][3]))
    return output


def _bias(bars: list[Bar]) -> str:
    if len(bars) < 50:
        return "unknown"
    closes = [bar[3] for bar in bars]
    ema20 = _last(_ema(closes, 20))
    ema50 = _last(_ema(closes, 50))
    price = closes[-1]
    if ema20 is None or ema50 is None:
        return "unknown"
    if ema20 > ema50 and price > ema20:
        return "up"
    if ema20 < ema50 and price < ema20:
        return "down"
    return "flat"


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
    gains = []
    losses = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
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


def _adx(bars: list[Bar], period: int) -> float | None:
    if len(bars) < period * 2 + 1:
        return None
    trs: list[float] = []
    plus: list[float] = []
    minus: list[float] = []
    for index in range(1, len(bars)):
        high, low = bars[index][1], bars[index][2]
        prev_high, prev_low, prev_close = bars[index - 1][1], bars[index - 1][2], bars[index - 1][3]
        up_move = high - prev_high
        down_move = prev_low - low
        plus.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    def wilder(values: list[float]) -> list[float]:
        current = sum(values[:period])
        smoothed = [current]
        for value in values[period:]:
            current = current - current / period + value
            smoothed.append(current)
        return smoothed

    smooth_tr = wilder(trs)
    smooth_plus = wilder(plus)
    smooth_minus = wilder(minus)
    dx: list[float] = []
    for true_range, plus_dm, minus_dm in zip(smooth_tr, smooth_plus, smooth_minus):
        if true_range == 0:
            dx.append(0.0)
            continue
        plus_di = 100 * plus_dm / true_range
        minus_di = 100 * minus_dm / true_range
        total = plus_di + minus_di
        dx.append(0.0 if total == 0 else 100 * abs(plus_di - minus_di) / total)
    if len(dx) < period:
        return None
    adx = sum(dx[:period]) / period
    for value in dx[period:]:
        adx = (adx * (period - 1) + value) / period
    return adx


def _last(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _ratio_text(ratio: float) -> str:
    return f"{ratio:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _aggregate_clock(bars: list[Bar], times: list[int], seconds: int) -> list[Bar]:
    """Group bars into higher-frame candles on clock boundaries. The last candle may be
    still forming; it only contains bars that are already closed."""
    output: list[Bar] = []
    current = None
    group = None
    for bar, moment in zip(bars, times):
        key = int(moment) // seconds
        if key != group:
            if current is not None:
                output.append(current)
            group = key
            current = (bar[0], bar[1], bar[2], bar[3])
        else:
            current = (current[0], max(current[1], bar[1]), min(current[2], bar[2]), bar[3])
    if current is not None:
        output.append(current)
    return output
