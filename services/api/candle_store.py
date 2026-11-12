import json
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(__file__).resolve().parents[2] / "data" / "candles"
FRAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}
COUNT = 5000


def save_candles(count: int = COUNT) -> dict[str, object]:
    import MetaTrader5 as mt5

    from services.api.mt5_session import open_terminal
    from services.api.settings_store import read_settings

    settings = read_settings()
    symbol = str(settings["symbol"] or "XAUUSDm")
    count = min(max(int(count), 100), 20000)
    saved: list[dict[str, object]] = []
    with open_terminal() as terminal:
        info = terminal.symbol_info(symbol)
        if info is None:
            code, message = terminal.last_error()
            raise RuntimeError(f"Không đọc được thông số {symbol} ({code}): {message}")
        market = _market(info)
        for name, attribute in FRAMES.items():
            rates = terminal.copy_rates_from_pos(symbol, getattr(mt5, attribute), 0, count)
            if rates is None or len(rates) < 80:
                code, message = terminal.last_error()
                saved.append({"timeframe": name, "count": 0, "from": "", "to": "", "error": f"{code}: {message}"})
                continue
            path = _path(symbol, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "time": int(row["time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
                for row in rates
            ]
            payload = {
                "symbol": symbol,
                "timeframe": name,
                "count": len(rows),
                "savedAt": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "from": _stamp(rows[0]["time"]),
                "to": _stamp(rows[-1]["time"]),
                "market": market,
                "bars": rows,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            saved.append({"timeframe": name, "count": len(rows), "from": payload["from"], "to": payload["to"]})
    return {"ok": True, "symbol": symbol, "frames": saved}


def load_candles(symbol: str, timeframe: str) -> dict[str, object] | None:
    path = _path(symbol, timeframe)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
        return None
    return payload


def _path(symbol: str, timeframe: str) -> Path:
    return STORE / symbol / f"{timeframe}.json"


def _stamp(moment: int) -> str:
    return datetime.fromtimestamp(int(moment), timezone.utc).strftime("%d/%m/%Y %H:%M")


def _market(info: object) -> dict[str, float]:
    point = float(getattr(info, "point", 0) or 0) or 0.001
    spread = max(float(getattr(info, "spread", 0) or 0) * point, point)
    return {
        "spread": spread,
        "tickSize": float(getattr(info, "trade_tick_size", 0) or 0) or point,
        "tickValue": float(getattr(info, "trade_tick_value", 0) or 0),
        "volumeMin": float(getattr(info, "volume_min", 0) or 0) or 0.01,
        "volumeMax": float(getattr(info, "volume_max", 0) or 0) or 50.0,
        "volumeStep": float(getattr(info, "volume_step", 0) or 0) or 0.01,
        "swapLong": float(getattr(info, "swap_long", 0) or 0),
        "swapShort": float(getattr(info, "swap_short", 0) or 0),
        "swapMode": float(getattr(info, "swap_mode", 0) or 0),
        "point": point,
    }
