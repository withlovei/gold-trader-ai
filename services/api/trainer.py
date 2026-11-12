import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from services.api.chart_analysis import TIMEFRAMES, _bollinger, _ema, _rsi
from services.api.settings_store import read_password, read_settings

MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
REPORT_PATH = MODEL_DIR / "latest.json"
HORIZON = 8
LABELS = {0: "Chờ", 1: "Mua", 2: "Bán"}
FEATURE_NAMES = [
    "Biến động 1 nến",
    "Biến động 4 nến",
    "Biến động 16 nến",
    "Khoảng cách EMA 20",
    "Khoảng cách EMA 50",
    "Khoảng cách EMA 200",
    "RSI",
    "Vị trí Bollinger",
    "Biến động GARCH",
    "HMM giảm",
    "HMM đi ngang",
    "HMM tăng",
]


def train_now(timeframe: str, bars: int) -> dict[str, object]:
    timeframe = timeframe if timeframe in TIMEFRAMES else "M15"
    bars = min(max(int(bars), 1000), 20000)
    settings = read_settings()
    symbol = str(settings["symbol"] or "XAUUSDm")
    rates, spread = _load_rates(symbol, timeframe, bars)
    if len(rates) < 800:
        raise RuntimeError("Không đủ nến để huấn luyện. Trong MetaTrader hãy tăng Max bars in chart, rồi thử lại.")
    report = _fit_ensemble(rates, symbol, timeframe, spread)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def latest_report() -> dict[str, object]:
    if not REPORT_PATH.exists():
        return {"ok": False, "message": "Chưa có lần huấn luyện nào."}
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def _load_rates(symbol: str, timeframe: str, count: int) -> tuple[list[tuple[float, float, float, float]], float]:
    password = read_password()
    if not password:
        raise RuntimeError("Chưa có mật khẩu MetaTrader. Vào Cài đặt, bấm Lưu và kết nối, rồi huấn luyện.")
    settings = read_settings()
    try:
        import MetaTrader5 as mt5
    except ImportError as error:
        raise RuntimeError("Chưa cài gói MetaTrader5 trong môi trường dự án.") from error

    frame = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }[timeframe]
    from services.api.mt5_session import open_terminal

    with open_terminal() as mt5:
        rates = mt5.copy_rates_from_pos(symbol, frame, 0, count)
        if rates is None or len(rates) == 0:
            code, message = mt5.last_error()
            raise RuntimeError(f"Không đọc được lịch sử {symbol} ({code}): {message}")
        info = mt5.symbol_info(symbol)
        spread = 0.2
        if info is not None and info.point:
            spread = max(float(info.spread) * float(info.point), float(info.point))
        bars = [(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) for row in rates]
        return bars, spread


def _fit_ensemble(
    bars: list[tuple[float, float, float, float]],
    symbol: str,
    timeframe: str,
    spread: float,
) -> dict[str, object]:
    try:
        import lightgbm as lgb
        import xgboost as xgb
        from hmmlearn.hmm import GaussianHMM
    except ImportError as error:
        raise RuntimeError("Thiếu LightGBM, XGBoost hoặc hmmlearn trong môi trường dự án.") from error

    closes = np.array([bar[3] for bar in bars], dtype=float)
    highs = np.array([bar[1] for bar in bars], dtype=float)
    lows = np.array([bar[2] for bar in bars], dtype=float)
    returns = np.zeros(len(closes))
    returns[1:] = np.diff(np.log(np.maximum(closes, 1e-8)))
    split_price = int(len(closes) * 0.75)
    omega, alpha, beta = _fit_garch(returns[1:split_price])
    sigma = _garch_sigma(returns, omega, alpha, beta)
    opens = np.array([bar[0] for bar in bars], dtype=float)
    labels, risks, drifts = _barriers(closes, opens, highs, lows, sigma, spread)
    base = _base_features(closes, bars, sigma)
    valid = [index for index in range(200, len(closes) - HORIZON - 1) if base[index] is not None]
    if len(valid) < 500:
        raise RuntimeError("Sau khi tính chỉ báo còn quá ít mẫu. Hãy lấy nhiều nến hơn.")

    split_at = int(len(valid) * 0.75)
    train_index = valid[:split_at]
    test_index = valid[split_at:]
    drift = (returns / np.maximum(sigma, 1e-6)).reshape(-1, 1)
    hmm = GaussianHMM(n_components=3, covariance_type="diag", n_iter=50, random_state=7, tol=1e-3, min_covar=0.05)
    try:
        hmm.fit(drift[train_index])
        separated = float(np.max(hmm.means_) - np.min(hmm.means_)) >= 0.15
        state_probs = _forward_filter(hmm, drift) if separated else np.full((len(drift), 3), 1.0 / 3.0)
    except ValueError:
        separated = False
        state_probs = np.full((len(drift), 3), 1.0 / 3.0)
        hmm = None
    regime_order = _regime_order(hmm) if separated and hmm is not None else [0, 1, 2]
    ordered_probs = state_probs[:, regime_order]
    train_states = np.argmax(ordered_probs[train_index], axis=1)
    occupancy = np.bincount(train_states, minlength=3) / max(len(train_states), 1)
    regimes_ready = separated and bool(np.all(occupancy >= 0.05))
    hmm_params = _pack_hmm(hmm, separated, regimes_ready, regime_order)
    features = np.array([list(base[index] or []) + ordered_probs[index].tolist() for index in valid], dtype=float)
    y = np.array([labels[index] for index in valid], dtype=int)
    risk_values = np.array([risks[index] for index in valid], dtype=float)
    drift_values = np.array([drifts[index] for index in valid], dtype=float)
    x_train, x_test = features[:split_at], features[split_at:]
    y_train, y_test = y[:split_at], y[split_at:]
    if len(set(y_train.tolist())) < 3:
        raise RuntimeError("Tập học thiếu một trong ba nhãn mua, bán, chờ. Hãy lấy nhiều nến hơn.")

    inner = int(split_at * 0.7)
    light_primary = _train_lightgbm(lgb, x_train[:inner], y_train[:inner])
    primary_probs = light_primary.predict(x_train[inner:])
    meta_y = _meta_labels(primary_probs, y_train[inner:], risk_values[inner:split_at], drift_values[inner:split_at], spread)
    meta_x = np.column_stack((x_train[inner:], primary_probs))
    score_model = _train_xgboost(xgb, meta_x, meta_y)
    direction_model = _train_lightgbm(lgb, x_train, y_train)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    direction_model.save_model(str(MODEL_DIR / "lightgbm.txt"))
    score_model.save_model(str(MODEL_DIR / "xgboost.json"))

    direction_probs = direction_model.predict(x_test)
    direction = np.argmax(direction_probs, axis=1)
    score = score_model.predict(xgb.DMatrix(np.column_stack((x_test, direction_probs))))
    regime_probs = x_test[:, -3:]
    combined = _combine(direction, score, regime_probs, regimes_ready)
    light_only = direction.copy()
    ensemble_stats = _pnl_stats(combined, y_test, risk_values[split_at:], drift_values[split_at:], spread)
    light_stats = _pnl_stats(light_only, y_test, risk_values[split_at:], drift_values[split_at:], spread)
    usable = ensemble_stats["trades"] >= 20 and ensemble_stats["average"] > 0 and ensemble_stats["profitFactor"] > 1 and ensemble_stats["average"] > light_stats["average"]
    now = _latest_call(
        direction_probs[-1],
        float(score[-1]),
        regime_probs[-1],
        float(sigma[test_index[-1]] * closes[test_index[-1]]),
        separated,
    )
    message = (
        "Bốn mô hình thống nhất hơn LightGBM đứng một mình trên nến kiểm tra, sau khi trừ chênh lệch."
        if usable
        else "Đã ghép GARCH, HMM, LightGBM và XGBoost. Trên nến kiểm tra, bản ghép chưa có lời kỳ vọng dương hơn LightGBM một mình."
    ) + (
        " Mô hình chỉ để tham khảo, không tham gia quyết định vào lệnh: kiểm định 2025–2026 trên M30 cho thấy dự đoán"
        " không hơn tỷ lệ ngẫu nhiên, và dùng làm bộ lọc lại bỏ đi chính các tín hiệu tốt nhất của chiến lược."
    )
    return {
        "ok": True,
        "active": False,
        "usable": usable,
        "trainedAt": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "symbol": symbol,
        "timeframe": timeframe,
        "samples": int(len(valid)),
        "testSamples": int(len(test_index)),
        "spread": round(spread, 4),
        "message": message,
        "ensemble": ensemble_stats,
        "lightgbmOnly": light_stats,
        "garch": {"omega": round(omega, 10), "alpha": round(alpha, 4), "beta": round(beta, 4)},
        "hmmModel": hmm_params,
        "now": now,
        "models": [
            {"name": "GARCH", "role": "Biến động và rủi ro", "value": now["garch"]},
            {"name": "HMM", "role": "Trạng thái thị trường", "value": now["hmm"]},
            {"name": "LightGBM", "role": "Tín hiệu mua / bán / chờ", "value": now["lightgbm"]},
            {"name": "XGBoost", "role": "Điểm cơ hội", "value": now["xgboost"]},
        ],
    }


def _fit_garch(returns: NDArray[np.float64]) -> tuple[float, float, float]:
    from scipy.optimize import minimize

    series = returns[np.isfinite(returns)]
    variance = float(np.var(series))
    variance = max(variance, 1e-8)

    def loss(params: NDArray[np.float64]) -> float:
        omega, alpha, beta = (float(params[0]), float(params[1]), float(params[2]))
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.995:
            return 1e9
        sigma2 = variance
        total = 0.0
        for value in series:
            sigma2 = omega + alpha * value * value + beta * sigma2
            if sigma2 <= 1e-12:
                return 1e9
            total += math.log(sigma2) + (value * value) / sigma2
        return total / len(series)

    start = np.array([variance * 0.05, 0.06, 0.9], dtype=float)
    fitted = minimize(loss, start, method="Nelder-Mead", options={"maxiter": 250, "xatol": 1e-10})
    if not fitted.success:
        return variance * 0.05, 0.06, 0.9
    return float(fitted.x[0]), float(fitted.x[1]), float(fitted.x[2])


def _garch_sigma(returns: NDArray[np.float64], omega: float, alpha: float, beta: float) -> NDArray[np.float64]:
    sigma2 = max(float(np.var(returns[1:200])), 1e-8)
    output = np.empty(len(returns))
    for index, value in enumerate(returns):
        output[index] = math.sqrt(sigma2)
        sigma2 = max(omega + alpha * value * value + beta * sigma2, 1e-12)
    return output


def _barriers(
    closes: NDArray[np.float64],
    opens: NDArray[np.float64],
    highs: NDArray[np.float64],
    lows: NDArray[np.float64],
    sigma: NDArray[np.float64],
    spread: float,
) -> tuple[dict[int, int], dict[int, float], dict[int, float]]:
    labels: dict[int, int] = {}
    risks: dict[int, float] = {}
    drifts: dict[int, float] = {}
    for index in range(200, len(closes) - HORIZON - 1):
        risk = max(float(sigma[index] * closes[index]), spread * 3)
        buy_fill = float(opens[index + 1]) + spread / 2
        sell_fill = float(opens[index + 1]) - spread / 2
        buy_pnl = _barrier_pnl("buy", buy_fill, risk, highs, lows, index + 1, index + 1 + HORIZON)
        sell_pnl = _barrier_pnl("sell", sell_fill, risk, highs, lows, index + 1, index + 1 + HORIZON)
        if buy_pnl > 0 and buy_pnl >= sell_pnl:
            label = 1
        elif sell_pnl > 0:
            label = 2
        else:
            label = 0
        labels[index] = label
        risks[index] = risk
        drifts[index] = float(closes[index + HORIZON] - buy_fill)
    return labels, risks, drifts


def _barrier_pnl(
    side: str,
    fill: float,
    risk: float,
    highs: NDArray[np.float64],
    lows: NDArray[np.float64],
    start: int,
    end: int,
) -> float:
    stop = fill - risk if side == "buy" else fill + risk
    take = fill + 1.5 * risk if side == "buy" else fill - 1.5 * risk
    for index in range(start, end + 1):
        stop_hit = float(lows[index]) <= stop if side == "buy" else float(highs[index]) >= stop
        take_hit = float(highs[index]) >= take if side == "buy" else float(lows[index]) <= take
        if stop_hit:
            return -risk
        if take_hit:
            return 1.5 * risk
    return 0.0


def _base_features(
    closes: NDArray[np.float64],
    bars: list[tuple[float, float, float, float]],
    sigma: NDArray[np.float64],
) -> list[list[float] | None]:
    close_list = closes.tolist()
    ema20 = _ema(close_list, 20)
    ema50 = _ema(close_list, 50)
    ema200 = _ema(close_list, 200)
    rsi = _rsi(close_list, 14)
    upper, _middle, lower = _bollinger(close_list, 20, 2.0)
    rows: list[list[float] | None] = [None] * len(closes)
    for index in range(200, len(closes)):
        scale = float(sigma[index] * closes[index])
        if scale <= 0 or ema200[index] is None or upper[index] is None or lower[index] is None or rsi[index] is None:
            continue
        width = (upper[index] or 0) - (lower[index] or 0)
        if width <= 0:
            continue
        rows[index] = [
            (closes[index] - closes[index - 1]) / scale,
            (closes[index] - closes[index - 4]) / scale,
            (closes[index] - closes[index - 16]) / scale,
            (closes[index] - (ema20[index] or closes[index])) / scale,
            (closes[index] - (ema50[index] or closes[index])) / scale,
            (closes[index] - (ema200[index] or closes[index])) / scale,
            (rsi[index] or 50) / 100,
            (closes[index] - (lower[index] or closes[index])) / width,
            float(sigma[index]),
        ]
    return rows


HMM_WINDOW = 4


def regime_now(closes: list[float]) -> dict[str, object]:
    report = latest_report()
    params = report.get("hmmModel") if isinstance(report.get("hmmModel"), dict) else None
    garch = report.get("garch") if isinstance(report.get("garch"), dict) else None
    if params is None or not params.get("ready") or garch is None or len(closes) < 30:
        return {
            "line": "HMM chưa có tham số mới, không dùng trạng thái cũ để chặn",
            "veto": None,
            "block": "",
        }
    series = np.array(closes, dtype=float)
    returns = np.zeros(len(series))
    returns[1:] = np.diff(np.log(np.maximum(series, 1e-8)))
    sigma = _garch_sigma(returns, float(garch["omega"]), float(garch["alpha"]), float(garch["beta"]))
    drift = (returns / np.maximum(sigma, 1e-6)).reshape(-1, 1)
    ordered = _filter_packed(params, drift)
    latest = ordered[-1]
    window = ordered[-HMM_WINDOW:]
    smooth = window.mean(axis=0)
    return _regime_view(smooth, latest, bool(params.get("regimesReady")))


def refresh_hmm() -> dict[str, object]:
    report = latest_report()
    if not isinstance(report.get("garch"), dict):
        raise RuntimeError("Chưa có GARCH. Hãy huấn luyện trước khi cập nhật HMM.")
    settings = read_settings()
    symbol = str(settings["symbol"] or report.get("symbol") or "XAUUSDm")
    rates, _spread = _load_rates(symbol, "M15", 5000)
    closes = np.array([bar[3] for bar in rates], dtype=float)
    returns = np.zeros(len(closes))
    returns[1:] = np.diff(np.log(np.maximum(closes, 1e-8)))
    garch = report["garch"]
    sigma = _garch_sigma(returns, float(garch["omega"]), float(garch["alpha"]), float(garch["beta"]))
    drift = (returns / np.maximum(sigma, 1e-6)).reshape(-1, 1)
    train_end = max(200, int(len(drift) * 0.75))
    params = _fit_hmm(drift[200:train_end])
    report["hmmModel"] = params
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return regime_now(closes.tolist())


def _fit_hmm(drift: NDArray[np.float64]) -> dict[str, object]:
    from hmmlearn.hmm import GaussianHMM

    model = GaussianHMM(n_components=3, covariance_type="diag", n_iter=50, random_state=7, tol=1e-3, min_covar=0.05)
    try:
        model.fit(drift)
        separated = float(np.max(model.means_) - np.min(model.means_)) >= 0.15
    except ValueError:
        return _pack_hmm(None, False, False, [0, 1, 2])
    order = _regime_order(model) if separated else [0, 1, 2]
    filtered = _forward_filter(model, drift) if separated else np.full((len(drift), 3), 1.0 / 3.0)
    ordered = filtered[:, order]
    occupancy = np.bincount(np.argmax(ordered, axis=1), minlength=3) / max(len(ordered), 1)
    ready = separated and bool(np.all(occupancy >= 0.05))
    return _pack_hmm(model, separated, ready, order)


def _pack_hmm(model: object, separated: bool, regimes_ready: bool, order: list[int]) -> dict[str, object]:
    if model is None or not separated:
        return {"ready": False, "separated": False, "regimesReady": False, "order": order}
    means = np.array(getattr(model, "means_"), dtype=float)
    covars = np.array(getattr(model, "covars_"), dtype=float)
    if covars.ndim == 3:
        covars = np.diagonal(covars, axis1=1, axis2=2)
    return {
        "ready": True,
        "separated": separated,
        "regimesReady": regimes_ready,
        "order": order,
        "means": means.round(6).tolist(),
        "covars": np.maximum(covars, 0.05).round(6).tolist(),
        "transmat": np.array(getattr(model, "transmat_"), dtype=float).round(6).tolist(),
        "startprob": np.array(getattr(model, "startprob_"), dtype=float).round(6).tolist(),
    }


def _filter_packed(params: dict[str, object], observations: NDArray[np.float64]) -> NDArray[np.float64]:
    means = np.array(params["means"], dtype=float)
    covars = np.maximum(np.array(params["covars"], dtype=float), 0.05)
    transition = np.clip(np.array(params["transmat"], dtype=float), 1e-6, None)
    transition = transition / transition.sum(axis=1, keepdims=True)
    start = np.clip(np.array(params["startprob"], dtype=float), 1e-6, None)
    start = start / start.sum()
    order = [int(index) for index in list(params["order"])]
    states = means.shape[0]
    output = np.zeros((len(observations), states))
    log_alpha = np.log(start)
    for time, observation in enumerate(observations):
        log_emission = np.zeros(states)
        for state in range(states):
            variance = covars[state]
            gap = observation - means[state]
            log_emission[state] = -0.5 * float(np.sum(gap * gap / variance + np.log(2 * math.pi * variance)))
        if time == 0:
            log_alpha = log_emission + np.log(start)
        else:
            next_alpha = np.zeros(states)
            for state in range(states):
                next_alpha[state] = log_emission[state] + _logsumexp(log_alpha + np.log(transition[:, state]))
            log_alpha = next_alpha
        log_alpha -= _logsumexp(log_alpha)
        probs = np.exp(log_alpha)
        output[time] = probs / max(float(probs.sum()), 1e-12)
    return output[:, order]


def _regime_view(smooth: NDArray[np.float64], latest: NDArray[np.float64], regimes_ready: bool) -> dict[str, object]:
    down, flat, up = (float(smooth[0]), float(smooth[1]), float(smooth[2]))
    latest_down, latest_flat, latest_up = (float(latest[0]), float(latest[1]), float(latest[2]))
    smooth_name = _regime_name(down, flat, up)
    latest_name = _regime_name(latest_down, latest_flat, latest_up)
    line = (
        f"HMM 4 nến: {smooth_name} {max(down, flat, up):.0%} · "
        f"nến này: {latest_name} {max(latest_down, latest_flat, latest_up):.0%}"
    )
    if not regimes_ready:
        return {"line": line + " · chưa tách đủ ba trạng thái, không chặn", "veto": None, "block": ""}
    if smooth_name != latest_name:
        return {"line": line + " · vừa đổi nên không chặn", "veto": None, "block": ""}
    veto = None
    if down >= 0.55 and latest_down >= 0.55:
        veto = "buy"
    elif up >= 0.55 and latest_up >= 0.55:
        veto = "sell"
    if veto is None:
        return {"line": line + " · chưa đủ mạnh để chặn", "veto": None, "block": ""}
    side_name = "mua" if veto == "buy" else "bán"
    return {
        "line": line + f" · chặn {side_name}",
        "veto": veto,
        "block": f"HMM 4 nến gần nhất và nến vừa đóng cùng ngược chiều lệnh {side_name}",
    }


def _regime_name(down: float, flat: float, up: float) -> str:
    if up >= down and up >= flat:
        return "tăng"
    if down >= up and down >= flat:
        return "giảm"
    return "đi ngang"


def _regime_opposes(window: NDArray[np.float64], side: int) -> bool:
    if len(window) < HMM_WINDOW:
        return False
    view = _regime_view(window[-HMM_WINDOW:].mean(axis=0), window[-1], True)
    return (side == 1 and view["veto"] == "buy") or (side == 2 and view["veto"] == "sell")


def _regime_order(model: object) -> list[int]:
    means = np.array(getattr(model, "means_"), dtype=float)
    ranked = sorted(range(len(means)), key=lambda index: float(means[index][0]))
    return ranked


def _forward_filter(model: object, observations: NDArray[np.float64]) -> NDArray[np.float64]:
    means = np.array(getattr(model, "means_"), dtype=float)
    covars = np.array(getattr(model, "covars_"), dtype=float)
    if covars.ndim == 3:
        covars = np.diagonal(covars, axis1=1, axis2=2)
    covars = np.maximum(covars, 0.05)
    transition = np.clip(np.array(getattr(model, "transmat_"), dtype=float), 1e-6, None)
    transition = transition / transition.sum(axis=1, keepdims=True)
    start = np.clip(np.array(getattr(model, "startprob_"), dtype=float), 1e-6, None)
    start = start / start.sum()
    states = means.shape[0]
    output = np.zeros((len(observations), states))
    log_alpha = np.log(start)
    for time, observation in enumerate(observations):
        log_emission = np.zeros(states)
        for state in range(states):
            variance = covars[state]
            gap = observation - means[state]
            log_emission[state] = -0.5 * float(np.sum(gap * gap / variance + np.log(2 * math.pi * variance)))
        if time == 0:
            log_alpha = log_emission + np.log(start)
        else:
            next_alpha = np.zeros(states)
            for state in range(states):
                next_alpha[state] = log_emission[state] + _logsumexp(log_alpha + np.log(transition[:, state]))
            log_alpha = next_alpha
        log_alpha -= _logsumexp(log_alpha)
        probs = np.exp(log_alpha)
        output[time] = probs / max(float(probs.sum()), 1e-12)
    return output


def _logsumexp(values: NDArray[np.float64]) -> float:
    peak = float(np.max(values))
    return peak + math.log(float(np.sum(np.exp(values - peak))))


def _train_lightgbm(lgb: object, features: NDArray[np.float64], labels: NDArray[np.int64]) -> object:
    counts = {label: int(np.sum(labels == label)) for label in (0, 1, 2)}
    weights = np.array([len(labels) / max(counts[int(label)], 1) for label in labels], dtype=float)
    dataset = lgb.Dataset(features, label=labels, weight=weights, feature_name=FEATURE_NAMES)
    return lgb.train(
        {
            "objective": "multiclass",
            "num_class": 3,
            "learning_rate": 0.05,
            "num_leaves": 15,
            "max_depth": 4,
            "min_child_samples": 30,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "feature_fraction": 0.8,
            "verbosity": -1,
        },
        dataset,
        num_boost_round=80,
    )


def _meta_labels(
    probabilities: NDArray[np.float64],
    labels: NDArray[np.int64],
    risks: NDArray[np.float64],
    drifts: NDArray[np.float64],
    spread: float,
) -> NDArray[np.int64]:
    calls = np.argmax(probabilities, axis=1)
    target = []
    for index, call in enumerate(calls):
        result = _one_pnl(int(call), int(labels[index]), float(risks[index]), float(drifts[index]), spread)
        target.append(1 if call != 0 and result > 0 else 0)
    return np.array(target, dtype=int)


def _train_xgboost(xgb: object, features: NDArray[np.float64], labels: NDArray[np.int64]) -> object:
    weight = np.where(labels == 1, max(float(np.sum(labels == 0)) / max(float(np.sum(labels == 1)), 1), 8), 1)
    matrix = xgb.DMatrix(features, label=labels, weight=weight)
    return xgb.train(
        {
            "objective": "binary:logistic",
            "max_depth": 3,
            "eta": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 10,
            "eval_metric": "logloss",
            "verbosity": 0,
        },
        matrix,
        num_boost_round=80,
    )


def _combine(
    direction: NDArray[np.int64],
    score: NDArray[np.float64],
    regime_probs: NDArray[np.float64],
    regimes_ready: bool,
) -> NDArray[np.int64]:
    combined = []
    for index, call in enumerate(direction):
        side = int(call)
        down, _flat, up = (float(regime_probs[index][0]), float(regime_probs[index][1]), float(regime_probs[index][2]))
        if side == 0 or float(score[index]) < 0.55:
            side = 0
        elif regimes_ready and _regime_opposes(regime_probs[max(0, index - 3) : index + 1], side):
            side = 0
        combined.append(side)
    return np.array(combined, dtype=int)


def _one_pnl(side: int, label: int, risk: float, drift: float, spread: float) -> float:
    if side == 0:
        return 0.0
    if side == 1:
        if label == 1:
            return 1.5 * risk - spread
        if label == 2:
            return -1.5 * risk - spread
        return drift - spread
    if label == 2:
        return 1.5 * risk - spread
    if label == 1:
        return -1.5 * risk - spread
    return -drift - spread


def _pnl_stats(
    sides: NDArray[np.int64],
    labels: NDArray[np.int64],
    risks: NDArray[np.float64],
    drifts: NDArray[np.float64],
    spread: float,
) -> dict[str, float | int | None]:
    results = [
        _one_pnl(int(sides[index]), int(labels[index]), float(risks[index]), float(drifts[index]), spread)
        for index in range(len(sides))
        if int(sides[index]) != 0
    ]
    wins = sum(value for value in results if value > 0)
    losses = -sum(value for value in results if value < 0)
    hits = sum(1 for value in results if value > 0)
    return {
        "trades": len(results),
        "winRate": round(hits / len(results), 4) if results else None,
        "average": round(sum(results) / len(results), 2) if results else 0.0,
        "profitFactor": round(wins / losses, 2) if losses > 0 else None,
        "net": round(sum(results), 2),
    }


def _latest_call(
    probabilities: NDArray[np.float64],
    score: float,
    regime_probs: NDArray[np.float64],
    sigma_price: float,
    separated: bool,
) -> dict[str, object]:
    call = int(np.argmax(probabilities))
    down, flat, up = (float(regime_probs[0]), float(regime_probs[1]), float(regime_probs[2]))
    if not separated:
        regime = "Chưa tách được"
    else:
        regime = "Tăng" if up >= down and up >= flat else "Giảm" if down >= up and down >= flat else "Đi ngang"
    side = call
    regime_veto = separated and min(down, flat, up) >= 0.05
    if call == 0 or score < 0.55 or (regime_veto and ((call == 1 and down > 0.55) or (call == 2 and up > 0.55))):
        side = 0
    return {
        "decision": LABELS[side],
        "garch": f"Biến động một nến {sigma_price:.2f} giá",
        "hmm": f"{regime} · tăng {up:.0%} · đi ngang {flat:.0%} · giảm {down:.0%}",
        "lightgbm": f"Mua {float(probabilities[1]):.0%} · bán {float(probabilities[2]):.0%} · chờ {float(probabilities[0]):.0%}",
        "xgboost": f"Điểm cơ hội {score:.0%}" + (" · đủ ngưỡng" if score >= 0.55 else " · dưới ngưỡng 55%"),
    }
