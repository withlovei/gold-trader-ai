"""Paper tracking for candidate strategies (SHADOW_STRATEGIES). Signals are recorded and managed
bar by bar with the backtest's exit rules, but no order is ever sent. After a few months the
paper results are compared with the backtest before a strategy may be promoted to live."""
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from services.api.settings_store import DATA_DIR, DB_PATH

VN_TZ = timezone(timedelta(hours=7))
# Backtest yardstick for the breakout candidate on M30, 2021-2026.
EXPECTED = {"breakout": {"averageR": 0.106, "winRate": 0.40, "profitFactor": 1.19}}
NAMES = {"breakout": "Phá vùng"}
TRAIL_ATR = 3.0
MAX_BARS = 400


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shadow_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            side TEXT NOT NULL,
            signal_bar INTEGER NOT NULL,
            opened_at INTEGER NOT NULL,
            entry REAL NOT NULL,
            stop REAL NOT NULL,
            risk REAL NOT NULL,
            best REAL NOT NULL,
            last_bar INTEGER NOT NULL,
            bars_held INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            closed_at INTEGER,
            exit_price REAL,
            swap REAL DEFAULT 0,
            r REAL,
            reason TEXT
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(shadow_trades)")}
    for column, kind in (("take", "REAL"), ("max_bars", "INTEGER"), ("manage", "TEXT"), ("frame_seconds", "INTEGER")):
        if column not in columns:
            connection.execute(f"ALTER TABLE shadow_trades ADD COLUMN {column} {kind}")
    return connection


def _atr_series(bars: list[tuple[float, float, float, float]], period: int = 14) -> list[float | None]:
    output: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return output
    ranges = [bars[0][1] - bars[0][2]]
    for index in range(1, len(bars)):
        high, low, previous = bars[index][1], bars[index][2], bars[index - 1][3]
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    value = sum(ranges[1 : period + 1]) / period
    output[period] = value
    for index in range(period + 1, len(bars)):
        value = (value * (period - 1) + ranges[index]) / period
        output[index] = value
    return output


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


def process(
    strategies: tuple[str, ...],
    catalog: object,
    bars: list[tuple[float, float, float, float]],
    times: list[int],
    bar_seconds: int,
    tick: object,
    spread: float,
    swap_long: float,
    swap_short: float,
) -> None:
    """Called once per newly closed bar. bars/times end with the closed bar."""
    atr = _atr_series(bars)
    with _connect() as connection:
        # Only rows of this bar size: a call with M30 bars must not walk M15 paper trades (and the
        # reverse). Rows from before the column existed: breakout ran on M30, the rest on M15.
        open_rows = [dict(row) for row in connection.execute("SELECT * FROM shadow_trades WHERE status = 'open'")
                     if _frame(dict(row)) == int(bar_seconds)]
        for row in open_rows:
            update = _advance(row, bars, times, atr, spread, swap_long, swap_short)
            connection.execute(
                f"UPDATE shadow_trades SET {', '.join(key + ' = ?' for key in update)} WHERE id = ?",
                (*update.values(), row["id"]),
            )
        busy = {row["strategy"] for row in connection.execute("SELECT * FROM shadow_trades WHERE status = 'open'") if _frame(dict(row)) == int(bar_seconds)}
        if not isinstance(catalog, list):
            return
        for item in catalog:
            name = str(item.get("id")) if isinstance(item, dict) else ""
            if name not in strategies or name in busy or not item.get("confirmed") or item.get("side") not in {"buy", "sell"}:
                continue
            side = str(item["side"])
            risk = abs(float(item["entry"]) - float(item["stop"]))
            if risk <= 0:
                continue
            entry = float(tick.ask) if side == "buy" else float(tick.bid)
            stop = entry - risk if side == "buy" else entry + risk
            manage = str(item.get("manage") or "trail")
            take = None
            if manage != "trail" and item.get("takeProfit") is not None:
                reward = abs(float(item["takeProfit"]) - float(item["entry"]))
                take = entry + reward if side == "buy" else entry - reward
            connection.execute(
                """INSERT INTO shadow_trades (strategy, side, signal_bar, opened_at, entry, stop, risk, best, last_bar, status, take, max_bars, manage, frame_seconds)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
                (name, side, int(times[-1]), int(times[-1]) + bar_seconds, entry, stop, risk, entry, int(times[-1]),
                 take, int(item.get("maxBars") or MAX_BARS), manage, int(bar_seconds)),
            )


def _frame(row: dict[str, object]) -> int:
    if row.get("frame_seconds"):
        return int(row["frame_seconds"])
    return 1800 if row.get("strategy") == "breakout" else 900


def _advance(row, bars, times, atr, spread, swap_long, swap_short) -> dict[str, object]:
    """Walk the bars that closed since the trade was last updated, with the backtest's rules:
    stop first, then a 3-ATR chandelier trail once 1R in profit, applied from the next bar."""
    side = row["side"]
    entry, stop, risk, best = float(row["entry"]), float(row["stop"]), float(row["risk"]), float(row["best"])
    held = int(row["bars_held"])
    last_bar = int(row["last_bar"])
    take = row.get("take")
    limit = int(row.get("max_bars") or MAX_BARS)
    trail = (row.get("manage") or "trail") == "trail"
    for index, moment in enumerate(times):
        if moment <= last_bar or moment < int(row["opened_at"]):
            continue
        bar = bars[index]
        first = held == 0
        held += 1
        last_bar = moment
        exit_price = None
        reason = ""
        if side == "buy" and bar[2] <= stop:
            exit_price, reason = (stop if first else min(bar[0], stop)), "Cắt lỗ"
        elif side == "sell" and bar[1] + spread >= stop:
            exit_price, reason = (stop if first else max(bar[0] + spread, stop)), "Cắt lỗ"
        elif take is not None and side == "buy" and bar[1] >= float(take):
            exit_price, reason = (max(bar[0], float(take)) if not first else float(take)), "Chốt lời"
        elif take is not None and side == "sell" and bar[2] + spread <= float(take):
            exit_price, reason = (min(bar[0] + spread, float(take)) if not first else float(take)), "Chốt lời"
        elif held >= limit:
            exit_price, reason = (bar[3] if side == "buy" else bar[3] + spread), f"Hết {limit} nến"
        if exit_price is not None:
            closed = int(moment) + (int(times[1]) - int(times[0]) if len(times) > 1 else 0)
            swap = _nights(int(row["opened_at"]), closed) * (swap_long if side == "buy" else swap_short)
            move = (exit_price - entry) if side == "buy" else (entry - exit_price)
            return {
                "stop": stop, "best": best, "last_bar": last_bar, "bars_held": held, "status": "closed",
                "closed_at": closed, "exit_price": round(exit_price, 3), "swap": round(swap, 4),
                "r": round((move - swap) / risk, 3), "reason": reason if reason != "Cắt lỗ" or (stop - entry) * (1 if side == "buy" else -1) < 0 else "Cắt lỗ bám",
            }
        value = atr[index]
        if value is not None and trail:
            if side == "buy":
                best = max(best, bar[1])
                if best - entry >= risk:
                    stop = max(stop, best - TRAIL_ATR * value)
            else:
                best = min(best, bar[2] + spread)
                if entry - best >= risk:
                    stop = min(stop, best + TRAIL_ATR * value)
    return {"stop": stop, "best": best, "last_bar": last_bar, "bars_held": held}


def _names() -> dict[str, str]:
    try:
        from services.api.methods import METHODS

        return {**NAMES, **{method.id: f"{method.alias} · {method.label}" for method in METHODS}}
    except ImportError:
        return dict(NAMES)


def summary(limit: int = 40) -> dict[str, object]:
    with _connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM shadow_trades ORDER BY opened_at DESC LIMIT ?", (limit,))]
        closed = [dict(row) for row in connection.execute("SELECT * FROM shadow_trades WHERE status = 'closed'")]
    names = _names()
    out = {}
    for name in sorted({*NAMES, *(row["strategy"] for row in closed)}):
        mine = [row for row in closed if row["strategy"] == name]
        r_values = [float(row["r"]) for row in mine if row["r"] is not None]
        wins = [value for value in r_values if value > 0]
        losses = -sum(value for value in r_values if value < 0)
        count = len(r_values)
        average = sum(r_values) / count if count else None
        expected = EXPECTED.get(name) or {"averageR": 0.0, "winRate": None, "profitFactor": None}
        if count < 30:
            verdict = f"Mới {count} lệnh giấy đóng. Cần khoảng 30 lệnh (thường 6–9 tháng trên M30) trước khi cân nhắc gửi lệnh thật."
        elif average is not None and average >= expected["averageR"] * 0.5:
            verdict = f"{count} lệnh giấy, trung bình {average:+.2f}R, khớp kiểm thử (+{expected['averageR']:.2f}R). Có thể cân nhắc cho gửi lệnh thật."
        else:
            verdict = f"{count} lệnh giấy, trung bình {average:+.2f}R, kém kiểm thử (+{expected['averageR']:.2f}R). Chưa nên gửi lệnh thật."
        out[name] = {
            "name": names.get(name, name),
            "closed": count,
            "open": sum(1 for row in rows if row["strategy"] == name and row["status"] == "open"),
            "totalR": round(sum(r_values), 2),
            "averageR": None if average is None else round(average, 3),
            "winRate": round(len(wins) / count, 3) if count else None,
            "profitFactor": round(sum(wins) / losses, 2) if losses > 0 else None,
            "expected": expected,
            "verdict": verdict,
        }

    def stamp(value: object) -> str:
        return datetime.fromtimestamp(int(value), VN_TZ).strftime("%d/%m %H:%M") if value else ""

    return {
        "strategies": out,
        "rows": [
            {
                "strategy": names.get(row["strategy"], row["strategy"]),
                "side": "Mua" if row["side"] == "buy" else "Bán",
                "opened": stamp(row["opened_at"]),
                "entry": row["entry"],
                "stop": round(float(row["stop"]), 2),
                "status": "Đang mở" if row["status"] == "open" else "Đã đóng",
                "closed": stamp(row["closed_at"]),
                "exit": row["exit_price"],
                "r": row["r"],
                "reason": row["reason"] or "",
                "bars": row["bars_held"],
            }
            for row in rows
        ],
    }
