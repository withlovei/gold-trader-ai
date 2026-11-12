import sqlite3
from pathlib import Path

from services.api.secrets import protect, unprotect

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "app.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mt5_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            terminal_path TEXT NOT NULL,
            server TEXT NOT NULL,
            login TEXT NOT NULL,
            symbol TEXT NOT NULL,
            password_blob BLOB
        )
        """
    )
    return connection


def read_settings() -> dict[str, str | bool]:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM mt5_settings WHERE id = 1").fetchone()
    if row is None:
        return {
            "terminalPath": r"C:\Program Files\MetaTrader 5\terminal64.exe",
            "server": "Exness-MT5Trial",
            "login": "",
            "symbol": "XAUUSDm",
            "hasPassword": False,
        }
    return {
        "terminalPath": row["terminal_path"],
        "server": row["server"],
        "login": row["login"],
        "symbol": row["symbol"],
        "hasPassword": row["password_blob"] is not None,
    }


def save_settings(terminal_path: str, server: str, login: str, symbol: str, password: str) -> None:
    with _connect() as connection:
        current = connection.execute("SELECT password_blob FROM mt5_settings WHERE id = 1").fetchone()
        blob = current["password_blob"] if current else None
        if password:
            blob = protect(password)
        connection.execute(
            """
            INSERT INTO mt5_settings (id, terminal_path, server, login, symbol, password_blob)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                terminal_path = excluded.terminal_path,
                server = excluded.server,
                login = excluded.login,
                symbol = excluded.symbol,
                password_blob = excluded.password_blob
            """,
            (terminal_path, server, login, symbol, blob),
        )


def read_risk() -> dict[str, float | int]:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                per_trade_percent REAL NOT NULL,
                daily_loss_percent REAL NOT NULL,
                drawdown_percent REAL NOT NULL,
                max_positions INTEGER NOT NULL,
                max_loss_streak INTEGER NOT NULL,
                min_reward_ratio REAL NOT NULL
            )
            """
        )
        _ensure_min_lot_column(connection)
        row = connection.execute("SELECT * FROM risk_settings WHERE id = 1").fetchone()
    if row is None:
        return dict(_RISK_DEFAULTS)
    return {
        "minLotPercent": float(row["min_lot_percent"]),
        "maxOpenRiskPercent": float(row["max_open_risk_percent"]),
        "perTradePercent": float(row["per_trade_percent"]),
        "dailyLossPercent": float(row["daily_loss_percent"]),
        "drawdownPercent": float(row["drawdown_percent"]),
        "maxPositions": int(row["max_positions"]),
        "maxLossStreak": int(row["max_loss_streak"]),
        "minRewardRatio": float(row["min_reward_ratio"]),
    }


def save_risk(values: dict[str, float | int]) -> dict[str, float | int]:
    current = read_risk()
    saved = {
        # A trade whose risk-based size is below the broker's minimum lot may still be sent at
        # the minimum lot while that lot risks at most this % of equity (0 = never). Lets a small
        # account trade; the per-trade % keeps sizing larger accounts. Kept when not given.
        "minLotPercent": _clamp(current.get("minLotPercent") if values.get("minLotPercent") is None else values.get("minLotPercent"), 0, 50, 0),
        # summed risk of all open agent positions (multi-agent coordinator)
        "maxOpenRiskPercent": _clamp(current.get("maxOpenRiskPercent") if values.get("maxOpenRiskPercent") is None else values.get("maxOpenRiskPercent"), 0.5, 50, 6),
        "perTradePercent": _clamp(values.get("perTradePercent"), 0.1, 5, 0.5),
        "dailyLossPercent": _clamp(values.get("dailyLossPercent"), 0.5, 20, 2),
        "drawdownPercent": _clamp(values.get("drawdownPercent"), 1, 50, 10),
        "maxPositions": int(_clamp(values.get("maxPositions"), 1, 20, 2)),
        "maxLossStreak": int(_clamp(values.get("maxLossStreak"), 1, 20, 3)),
        "minRewardRatio": _clamp(values.get("minRewardRatio"), 1, 5, 1.5),
    }
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                per_trade_percent REAL NOT NULL,
                daily_loss_percent REAL NOT NULL,
                drawdown_percent REAL NOT NULL,
                max_positions INTEGER NOT NULL,
                max_loss_streak INTEGER NOT NULL,
                min_reward_ratio REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO risk_settings (
                id, per_trade_percent, daily_loss_percent, drawdown_percent,
                max_positions, max_loss_streak, min_reward_ratio
            )
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                per_trade_percent = excluded.per_trade_percent,
                daily_loss_percent = excluded.daily_loss_percent,
                drawdown_percent = excluded.drawdown_percent,
                max_positions = excluded.max_positions,
                max_loss_streak = excluded.max_loss_streak,
                min_reward_ratio = excluded.min_reward_ratio
            """,
            (
                saved["perTradePercent"],
                saved["dailyLossPercent"],
                saved["drawdownPercent"],
                saved["maxPositions"],
                saved["maxLossStreak"],
                saved["minRewardRatio"],
            ),
        )
        _ensure_min_lot_column(connection)
        connection.execute(
            "UPDATE risk_settings SET min_lot_percent = ?, max_open_risk_percent = ? WHERE id = 1", (saved["minLotPercent"], saved["maxOpenRiskPercent"])
        )
    return saved


def _ensure_min_lot_column(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(risk_settings)")}
    if "min_lot_percent" not in columns:
        connection.execute("ALTER TABLE risk_settings ADD COLUMN min_lot_percent REAL NOT NULL DEFAULT 0")
    if "max_open_risk_percent" not in columns:
        connection.execute("ALTER TABLE risk_settings ADD COLUMN max_open_risk_percent REAL NOT NULL DEFAULT 6")


def _clamp(value: object, low: float, high: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return round(min(high, max(low, number)), 2)


_RISK_DEFAULTS: dict[str, float | int] = {
    "perTradePercent": 0.5,
    "dailyLossPercent": 2.0,
    "drawdownPercent": 10.0,
    "maxPositions": 2,
    "maxLossStreak": 3,
    "minRewardRatio": 1.5,
    "minLotPercent": 0.0,
    "maxOpenRiskPercent": 6.0,
}


def read_flag(name: str, default: str = "") -> str:
    """Small named switches (for example llmJudge = on/off)."""
    with _connect() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS app_flags (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = connection.execute("SELECT value FROM app_flags WHERE name = ?", (name,)).fetchone()
    return default if row is None else str(row["value"])


def write_flag(name: str, value: str) -> str:
    with _connect() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS app_flags (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO app_flags (name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value", (name, str(value))
        )
    return str(value)


def read_password() -> str | None:
    with _connect() as connection:
        row = connection.execute("SELECT password_blob FROM mt5_settings WHERE id = 1").fetchone()
    if row is None or row["password_blob"] is None:
        return None
    return unprotect(row["password_blob"])
