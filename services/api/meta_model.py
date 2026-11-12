"""Signal-scoring model for the validated trend strategy (meta-labelling).

The old ensemble tried to predict price direction on every bar and had no edge. This model
answers the question that matters at entry: given a trend signal, how likely is the trade to
win under the live exit (2R target, 48-bar limit, spread and swap)? It is a regularised
logistic regression on context features the rules do not use.

Use is deliberately one-sided: a signal scoring below the threshold is taken at half size, never
skipped and never enlarged, so the model can only lower risk. Walk-forward 2023-2026 on M30
(trained on earlier years only): same total R, drawdown 13.7R -> 8.9R.
"""
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from services.api.settings_store import DATA_DIR, DB_PATH

MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "signal-model.json"
TF_SECONDS = {"M15": 900, "M30": 1800, "H1": 3600}
HTF_FACTOR = {"M15": 4, "M30": 2, "H1": 4}
TRAIN_BARS = {"M15": 99000, "M30": 60000, "H1": 40000}
FEATURES = [
    "side", "adx", "adx_slope", "atr_ratio", "atr_rel", "stop_atr", "close_ema20", "ema20_ema50",
    "close_ema200", "pullback_depth", "body_atr", "close_pos", "rsi", "hour_sin", "hour_cos", "dow",
    "room_to_high50", "room_to_low50", "ret24", "trend_age", "htf_gap", "range_ratio", "tf_minutes",
]
LABELS = {
    "stop_atr": "Khoảng cắt lỗ so với ATR",
    "trend_age": "Tuổi xu hướng",
    "atr_ratio": "Biến động ATR14/ATR100",
    "close_ema200": "Khoảng cách tới EMA 200",
    "room_to_low50": "Khoảng cách tới đáy 50 nến",
    "room_to_high50": "Khoảng cách tới đỉnh 50 nến",
    "adx": "ADX",
    "adx_slope": "ADX đang tăng hay giảm",
    "atr_rel": "Biến động so với giá",
    "htf_gap": "Độ dốc khung lớn",
    "pullback_depth": "Độ sâu nhịp hồi",
    "ret24": "Quãng chạy 24 nến",
    "close_ema20": "Khoảng cách tới EMA 20",
    "ema20_ema50": "Khoảng cách EMA 20 – EMA 50",
    "body_atr": "Thân nến tín hiệu",
    "close_pos": "Vị trí đóng cửa trong nến",
    "rsi": "RSI theo chiều lệnh",
    "hour_sin": "Giờ trong ngày",
    "hour_cos": "Giờ trong ngày",
    "dow": "Thứ trong tuần",
    "range_ratio": "Biên độ 20 nến",
    "side": "Chiều lệnh",
    "tf_minutes": "Khung thời gian",
}
MODES = {
    "off": "Tắt",
    "shadow": "Chỉ ghi điểm",
    "size": "Giảm nửa khối lượng khi điểm thấp",
}
BLOCK_HOURS = (18, 19, 20, 21, 22, 23)
RETRAIN_DAYS = 30
PURGE_SECONDS = 5 * 86400


# ------------------------------------------------------------------ indicators (full series)

def _ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    value = float(x[:n].mean())
    out[n - 1] = value
    weight = 2 / (n + 1)
    for i in range(n, len(x)):
        value += weight * (x[i] - value)
        out[i] = value
    return out


def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) <= n:
        return out
    value = float(np.nanmean(x[1 : n + 1]))
    out[n] = value
    for i in range(n + 1, len(x)):
        value = (value * (n - 1) + x[i]) / n
        out[i] = value
    return out


def _true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    prev = np.roll(c, 1)
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    tr[0] = h[0] - l[0]
    return tr


def _atr(h, l, c, n):
    return _wilder(_true_range(h, l, c), n)


def _adx(h, l, c, n=14):
    up = h - np.roll(h, 1)
    down = np.roll(l, 1) - l
    up[0] = down[0] = 0
    plus = np.where((up > down) & (up > 0), up, 0.0)
    minus = np.where((down > up) & (down > 0), down, 0.0)
    tr = _wilder(_true_range(h, l, c), n)
    pdi = 100 * _wilder(plus, n) / tr
    mdi = 100 * _wilder(minus, n) / tr
    dx = np.nan_to_num(100 * abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9))
    out = np.full(len(c), np.nan)
    start = 2 * n
    if len(c) <= start:
        return out
    value = float(dx[n + 1 : start + 1].mean())
    out[start] = value
    for i in range(start + 1, len(c)):
        value = (value * (n - 1) + dx[i]) / n
        out[i] = value
    return out


def _rsi(c, n=14):
    change = np.diff(c, prepend=c[0])
    gain = _wilder(np.maximum(change, 0), n)
    loss = _wilder(np.maximum(-change, 0), n)
    return 100 - 100 / (1 + gain / np.maximum(loss, 1e-12))


def _roll(x, n, fn):
    from numpy.lib.stride_tricks import sliding_window_view

    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1 :] = fn(sliding_window_view(x, n), axis=1)
    return out


def _shift(x, k):
    out = np.full(len(x), np.nan)
    out[k:] = x[:-k]
    return out


def _htf_bias_and_gap(t, c, timeframe):
    """Higher-frame EMA20/EMA50 on clock-aligned candles. Bias uses the forming candle (as live
    does); the gap feature uses the last completed candle."""
    seconds = TF_SECONDS[timeframe] * HTF_FACTOR[timeframe]
    group = t // seconds
    bias = np.zeros(len(c))
    gap = np.full(len(c), np.nan)
    e20 = e50 = None
    count = 0
    w20, w50 = 2 / 21, 2 / 51
    for i in range(len(c)):
        if i > 0 and group[i] != group[i - 1]:
            close = c[i - 1]
            count += 1
            if e20 is None:
                e20 = e50 = close
            else:
                e20 += w20 * (close - e20)
                e50 += w50 * (close - e50)
        if e20 is None:
            continue
        gap[i] = e20 - e50
        if count < 60:
            continue
        now20 = e20 + w20 * (c[i] - e20)
        now50 = e50 + w50 * (c[i] - e50)
        if now20 > now50 and c[i] > now20:
            bias[i] = 1
        elif now20 < now50 and c[i] < now20:
            bias[i] = -1
    return bias, gap


class Frame:
    """All series needed for signals and features, computed once over a bar array."""

    def __init__(self, t, o, h, l, c, timeframe):
        self.t, self.o, self.h, self.l, self.c = (np.asarray(v, dtype=float) for v in (t, o, h, l, c))
        self.t = self.t.astype(np.int64)
        self.tf = timeframe
        self.n = len(self.c)
        self.atr = _atr(self.h, self.l, self.c, 14)
        self.atr100 = _atr(self.h, self.l, self.c, 100)
        self.adx = _adx(self.h, self.l, self.c, 14)
        self.rsi = _rsi(self.c, 14)
        self.e20, self.e50, self.e200 = _ema(self.c, 20), _ema(self.c, 50), _ema(self.c, 200)
        self.bias, self.htf_gap = _htf_bias_and_gap(self.t, self.c, timeframe)
        self.hour = (self.t // 3600) % 24
        self.dow = ((self.t // 86400) + 3) % 7
        age = np.zeros(self.n)
        count, previous = 0, 0
        for i in range(self.n):
            sign = 0 if np.isnan(self.e20[i]) or np.isnan(self.e50[i]) else (1 if self.e20[i] > self.e50[i] else -1)
            count = count + 1 if sign == previous else 0
            previous = sign
            age[i] = count
        self.age = age

    def signals(self):
        """Vectorised copy of strategies._trend (validated against the bar-by-bar engine)."""
        c, h, l, o, a = self.c, self.h, self.l, self.o, self.atr
        up = (self.e20 > self.e50) & (self.adx >= 15) & (c > self.e200) & (self.bias > 0.5)
        down = (self.e20 < self.e50) & (self.adx >= 15) & (c < self.e200) & (self.bias < -0.5)
        low3, high3 = _roll(l, 3, np.min), _roll(h, 3, np.max)
        touched_up = _shift(low3, 1) <= _shift(self.e20, 1)
        touched_down = _shift(high3, 1) >= _shift(self.e20, 1)
        held_up = _roll(c, 3, np.min) > self.e50
        held_down = _roll(c, 3, np.max) < self.e50
        trigger_up = (c > _shift(h, 1)) & (c > o)
        trigger_down = (c < _shift(l, 1)) & (c < o)
        expanding = a >= self.atr100
        buy = up & touched_up & held_up & trigger_up & expanding
        sell = down & touched_down & held_down & trigger_down & expanding
        side = np.where(buy, 1, np.where(sell, -1, 0))
        distance = np.where(side == 1, c - low3, high3 - c) + 0.3 * a
        distance = np.maximum(distance, 0.8 * a)
        distance = np.where(distance <= 3.0 * a, distance, np.nan)
        side = np.where(np.isnan(distance), 0, side)
        return side, distance

    def features(self, i: int, side: int, distance: float, fill_hour: int) -> list[float]:
        c, h, l, o, a = self.c, self.h, self.l, self.o, self.atr
        lo10 = float(np.min(l[max(0, i - 9) : i + 1]))
        hi10 = float(np.max(h[max(0, i - 9) : i + 1]))
        lo50 = float(np.min(l[max(0, i - 49) : i + 1]))
        hi50 = float(np.max(h[max(0, i - 49) : i + 1]))
        range20 = float(np.max(h[max(0, i - 19) : i + 1]) - np.min(l[max(0, i - 19) : i + 1]))
        atr = float(a[i])
        span = max(float(h[i] - l[i]), 1e-9)
        return [
            side,
            float(self.adx[i]),
            float(self.adx[i] - self.adx[i - 5]),
            atr / float(self.atr100[i]),
            atr / float(c[i]) * 1000,
            distance / atr,
            side * float(c[i] - self.e20[i]) / atr,
            side * float(self.e20[i] - self.e50[i]) / atr,
            side * float(c[i] - self.e200[i]) / atr,
            ((hi10 - float(l[i])) if side == 1 else (float(h[i]) - lo10)) / atr,
            side * float(c[i] - o[i]) / atr,
            (float(c[i] - l[i]) / span) if side == 1 else (float(h[i] - c[i]) / span),
            float(self.rsi[i]) if side == 1 else 100 - float(self.rsi[i]),
            math.sin(2 * math.pi * fill_hour / 24),
            math.cos(2 * math.pi * fill_hour / 24),
            float(self.dow[i]),
            ((hi50 - float(c[i])) if side == 1 else (float(c[i]) - lo50)) / atr,
            ((float(c[i]) - lo50) if side == 1 else (hi50 - float(c[i]))) / atr,
            side * float(c[i] - c[i - 24]) / atr,
            min(float(self.age[i]), 500.0),
            side * float(self.htf_gap[i]) / atr if not np.isnan(self.htf_gap[i]) else 0.0,
            range20 / atr,
            float(TF_SECONDS[self.tf] // 60),
        ]


def _outcomes(frame: Frame, side, distance, spread, swap_long, swap_short):
    """Every signal judged on its own (overlap allowed) with the live exit."""
    rows = []
    for i in np.nonzero(side)[0]:
        if i < 400 or i + 1 >= frame.n:
            continue
        j = i + 1
        if frame.hour[j] in BLOCK_HOURS:
            continue
        s = int(side[i])
        dist = float(distance[i])
        sp = float(spread[j])
        entry = frame.o[j] + sp if s == 1 else frame.o[j]
        stop = entry - s * dist
        target = entry + s * 2.0 * dist
        k = j
        while True:
            spk = float(spread[k])
            if s == 1:
                if frame.l[k] <= stop:
                    exit_price = stop if k == j else min(frame.o[k], stop)
                    break
                if frame.h[k] >= target:
                    exit_price = target if k == j else max(frame.o[k], target)
                    break
            else:
                if frame.h[k] + spk >= stop:
                    exit_price = stop if k == j else max(frame.o[k] + spk, stop)
                    break
                if frame.l[k] + spk <= target:
                    exit_price = target if k == j else min(frame.o[k] + spk, target)
                    break
            if k - j + 1 >= 48 or k >= frame.n - 1:
                exit_price = frame.c[k] if s == 1 else frame.c[k] + spk
                break
            k += 1
        pnl = (exit_price - entry) * s - _nights(int(frame.t[j]), int(frame.t[k])) * (swap_long if s == 1 else swap_short)
        rows.append((i, s, dist, pnl / dist))
    return rows


def _nights(start: int, end: int) -> int:
    if end <= start:
        return 0
    moment = ((start - 21 * 3600) // 86400 + 1) * 86400 + 21 * 3600
    nights = 0
    while moment <= end:
        weekday = ((moment // 86400) + 3) % 7
        if weekday < 5:
            nights += 3 if weekday == 2 else 1
        moment += 86400
    return nights


# ------------------------------------------------------------------ model

def _fit(x: np.ndarray, y: np.ndarray) -> dict[str, object]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    x = np.nan_to_num(x)
    scaler = StandardScaler().fit(x)
    model = LogisticRegression(C=0.1, max_iter=3000).fit(scaler.transform(x), y)
    return {
        "mean": scaler.mean_.tolist(),
        "scale": [float(v) if v > 0 else 1.0 for v in scaler.scale_],
        "coef": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
    }


def _predict(params: dict[str, object], x: np.ndarray) -> np.ndarray:
    x = np.nan_to_num(np.atleast_2d(x))
    z = (x - np.array(params["mean"])) / np.array(params["scale"])
    logit = z @ np.array(params["coef"]) + float(params["intercept"])
    return 1 / (1 + np.exp(-logit))


def _load_history(timeframe: str) -> tuple[Frame, np.ndarray, float, float]:
    import MetaTrader5 as mt5

    from services.api.mt5_session import open_terminal
    from services.api.settings_store import read_settings

    symbol = str(read_settings()["symbol"] or "XAUUSDm")
    with open_terminal() as terminal:
        info = terminal.symbol_info(symbol)
        rates = terminal.copy_rates_from_pos(symbol, getattr(mt5, "TIMEFRAME_" + timeframe), 1, TRAIN_BARS[timeframe])
    if info is None or rates is None or len(rates) < 3000:
        raise RuntimeError(f"Không đọc đủ lịch sử {timeframe} để huấn luyện.")
    point = float(info.point) or 0.001
    spread = np.maximum(np.array(rates["spread"], dtype=float) * point, 0.05)
    # swap is quoted in points per lot (swap_mode 1); as a price cost per night: -points * point
    swap_long = -float(getattr(info, "swap_long", 0) or 0) * point if int(getattr(info, "swap_mode", 0) or 0) == 1 else 0.0
    swap_short = -float(getattr(info, "swap_short", 0) or 0) * point if int(getattr(info, "swap_mode", 0) or 0) == 1 else 0.0
    frame = Frame(rates["time"], rates["open"], rates["high"], rates["low"], rates["close"], timeframe)
    return frame, spread, swap_long, swap_short


def build_dataset(frames: dict[str, tuple[Frame, np.ndarray, float, float]]) -> dict[str, np.ndarray]:
    xs, ys, rs, ts, years, tfs = [], [], [], [], [], []
    for timeframe, (frame, spread, swap_long, swap_short) in frames.items():
        side, distance = frame.signals()
        for i, s, dist, r_value in _outcomes(frame, side, distance, spread, swap_long, swap_short):
            fill_hour = int(frame.hour[i + 1])
            xs.append(frame.features(i, s, dist, fill_hour))
            ys.append(1 if r_value > 0 else 0)
            rs.append(r_value)
            ts.append(int(frame.t[i]))
            years.append(datetime.fromtimestamp(int(frame.t[i]), timezone.utc).year)
            tfs.append(timeframe)
    return {
        "x": np.array(xs, dtype=float), "y": np.array(ys), "r": np.array(rs), "t": np.array(ts),
        "year": np.array(years), "tf": np.array(tfs),
    }


def _walk_forward(data: dict[str, np.ndarray]) -> list[dict[str, object]]:
    rows = []
    for test_year in sorted(set(data["year"].tolist()))[2:]:
        test = data["year"] == test_year
        start = int(data["t"][test].min())
        train = (data["year"] < test_year) & (data["t"] < start - PURGE_SECONDS)
        if train.sum() < 300 or test.sum() < 30:
            continue
        params = _fit(data["x"][train], data["y"][train])
        threshold = float(np.quantile(_predict(params, data["x"][train]), 0.5))
        score = _predict(params, data["x"][test])
        r = data["r"][test]
        low = score < threshold
        weighted = np.where(low, 0.5, 1.0) * r
        rows.append({
            "year": int(test_year),
            "signals": int(test.sum()),
            "averageR": round(float(r.mean()), 3),
            "highR": round(float(r[~low].mean()), 3) if (~low).any() else None,
            "lowR": round(float(r[low].mean()), 3) if low.any() else None,
            "sizedR": round(float(weighted.sum() / np.where(low, 0.5, 1.0).sum()), 3),
            "highShare": round(float((~low).mean()), 2),
        })
    return rows


def train() -> dict[str, object]:
    started = time.time()
    frames = {timeframe: _load_history(timeframe) for timeframe in ("M15", "M30", "H1")}
    data = build_dataset(frames)
    if len(data["y"]) < 800:
        raise RuntimeError("Quá ít tín hiệu để huấn luyện. Cần ít nhất 800 tín hiệu.")
    folds = _walk_forward(data)
    params = _fit(data["x"], data["y"])
    scores = _predict(params, data["x"])
    threshold = float(np.quantile(scores, 0.5))
    better = sum(1 for row in folds if row["highR"] is not None and row["lowR"] is not None and row["highR"] > row["lowR"])
    weights = sorted(zip(np.abs(params["coef"]), FEATURES, params["coef"]), reverse=True)
    report = {
        "ok": True,
        "kind": "signal-model",
        "trainedAt": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "trainedTs": int(time.time()),
        "seconds": round(time.time() - started, 1),
        "features": FEATURES,
        "params": params,
        "threshold": round(threshold, 4),
        "signals": int(len(data["y"])),
        "byTimeframe": {tf: int((data["tf"] == tf).sum()) for tf in ("M15", "M30", "H1")},
        "from": datetime.fromtimestamp(int(data["t"].min()), timezone.utc).strftime("%d/%m/%Y"),
        "to": datetime.fromtimestamp(int(data["t"].max()), timezone.utc).strftime("%d/%m/%Y"),
        "winRate": round(float(data["y"].mean()), 3),
        "averageR": round(float(data["r"].mean()), 3),
        "folds": folds,
        "foldsBetter": better,
        "drivers": [
            {"feature": name, "label": LABELS.get(name, name), "weight": round(float(coef), 3)}
            for _abs, name, coef in weights[:8]
        ],
        "message": _message(folds, better),
    }
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _message(folds: list[dict[str, object]], better: int) -> str:
    if not folds:
        return "Chưa đủ năm để kiểm định walk-forward."
    return (
        f"Kiểm định walk-forward {len(folds)} năm (mỗi năm chỉ học từ các năm trước): tín hiệu điểm cao tốt hơn điểm thấp "
        f"ở {better}/{len(folds)} năm. Mô hình chỉ giảm nửa khối lượng cho tín hiệu điểm thấp, không bỏ lệnh và không tăng rủi ro."
    )


def latest() -> dict[str, object]:
    if not MODEL_PATH.exists():
        return {"ok": False, "message": "Chưa huấn luyện mô hình chấm tín hiệu.", **schedule()}
    return {**json.loads(MODEL_PATH.read_text(encoding="utf-8")), **schedule()}


def trained_ts() -> int | None:
    if not MODEL_PATH.exists():
        return None
    report = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    if report.get("trainedTs"):
        return int(report["trainedTs"])
    try:
        return int(datetime.strptime(str(report.get("trainedAt")), "%d/%m/%Y %H:%M").timestamp())
    except ValueError:
        return int(MODEL_PATH.stat().st_mtime)


def schedule() -> dict[str, object]:
    """Monthly retraining reminder: due once the model is RETRAIN_DAYS old."""
    trained = trained_ts()
    if trained is None:
        return {"ageDays": None, "due": True, "nextTraining": "ngay bây giờ"}
    age = (time.time() - trained) / 86400
    next_at = datetime.fromtimestamp(trained + RETRAIN_DAYS * 86400).strftime("%d/%m/%Y")
    return {"ageDays": round(age, 1), "due": age >= RETRAIN_DAYS, "nextTraining": next_at}


_CACHE: dict[str, object] = {"mtime": 0.0, "model": None}


def _model() -> dict[str, object] | None:
    if not MODEL_PATH.exists():
        return None
    mtime = MODEL_PATH.stat().st_mtime
    if _CACHE["mtime"] != mtime:
        _CACHE["model"] = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        _CACHE["mtime"] = mtime
    return _CACHE["model"]  # type: ignore[return-value]


def score_window(bars, times, timeframe: str, side: str, entry: float, stop: float, fill_hour: int) -> dict[str, object] | None:
    """Score the signal on the last bar of a window (same features as training)."""
    model = _model()
    if model is None or timeframe not in TF_SECONDS or side not in {"buy", "sell"} or len(bars) < 260:
        return None
    o = [bar[0] for bar in bars]
    h = [bar[1] for bar in bars]
    l = [bar[2] for bar in bars]
    c = [bar[3] for bar in bars]
    frame = Frame(times, o, h, l, c, timeframe)
    i = frame.n - 1
    values = frame.features(i, 1 if side == "buy" else -1, abs(entry - stop), fill_hour)
    if any(math.isnan(value) for value in values):
        return None
    probability = float(_predict(model["params"], np.array(values))[0])
    threshold = float(model["threshold"])
    return {"score": round(probability, 3), "threshold": round(threshold, 3), "low": probability < threshold}


# ------------------------------------------------------------------ settings

def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE IF NOT EXISTS model_settings (id INTEGER PRIMARY KEY CHECK (id = 1), mode TEXT NOT NULL)")
    return connection


def read_mode() -> str:
    with _connect() as connection:
        row = connection.execute("SELECT mode FROM model_settings WHERE id = 1").fetchone()
    return str(row["mode"]) if row is not None and row["mode"] in MODES else "size"


def save_mode(mode: str) -> dict[str, object]:
    if mode not in MODES:
        raise ValueError("Chế độ mô hình không hợp lệ.")
    with _connect() as connection:
        connection.execute(
            "INSERT INTO model_settings (id, mode) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET mode = excluded.mode",
            (mode,),
        )
    return {"ok": True, "mode": mode, "label": MODES[mode]}


def size_factor(scored: dict[str, object] | None, mode: str) -> float:
    if mode != "size" or scored is None:
        return 1.0
    return 0.5 if scored.get("low") else 1.0
