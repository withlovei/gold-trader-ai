"""Telegram notifications for order decisions and closed-trade results. Sending runs on a
background thread so a slow or unreachable Telegram never delays a trading decision."""
import html
import json
import logging
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from services.api.secrets import protect, unprotect
from services.api.settings_store import DATA_DIR, DB_PATH

VN_TZ = timezone(timedelta(hours=7))
_LOG = logging.getLogger("goldtrader.telegram")
_STATUS = {"lastError": "", "lastSent": ""}


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER NOT NULL,
            chat_id TEXT NOT NULL,
            token_blob BLOB
        )
        """
    )
    return connection


def read_telegram() -> dict[str, object]:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM telegram_settings WHERE id = 1").fetchone()
    if row is None:
        return {"enabled": False, "chatId": "", "hasToken": False, **_STATUS}
    return {"enabled": bool(row["enabled"]), "chatId": row["chat_id"], "hasToken": row["token_blob"] is not None, **_STATUS}


def save_telegram(enabled: bool, chat_id: str, token: str) -> dict[str, object]:
    chat_id = chat_id.strip()
    token = token.strip()
    with _connect() as connection:
        current = connection.execute("SELECT token_blob FROM telegram_settings WHERE id = 1").fetchone()
        blob = current["token_blob"] if current else None
        if token:
            blob = protect(token)
        if enabled and (blob is None or not chat_id):
            raise ValueError("Cần mã bot và mã chat trước khi bật Telegram.")
        connection.execute(
            """
            INSERT INTO telegram_settings (id, enabled, chat_id, token_blob) VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled, chat_id = excluded.chat_id, token_blob = excluded.token_blob
            """,
            (1 if enabled else 0, chat_id, blob),
        )
    return {"ok": True, **read_telegram()}


def _credentials() -> tuple[str, str] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM telegram_settings WHERE id = 1").fetchone()
    if row is None or not row["enabled"] or row["token_blob"] is None or not row["chat_id"]:
        return None
    return unprotect(row["token_blob"]), str(row["chat_id"])


def _post(token: str, chat_id: str, text: str) -> None:
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("description") or str(error)
        except (ValueError, OSError):
            detail = str(error)
        raise RuntimeError(detail) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"Không kết nối được Telegram: {error}") from error
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("description") or "Telegram từ chối tin nhắn."))


def send(text: str) -> None:
    """Fire and forget. Does nothing when Telegram is off."""
    credentials = _credentials()
    if credentials is None:
        return

    def worker() -> None:
        try:
            _post(credentials[0], credentials[1], text)
            _STATUS["lastError"] = ""
            _STATUS["lastSent"] = datetime.now(VN_TZ).strftime("%d/%m %H:%M:%S")
        except RuntimeError as error:
            _STATUS["lastError"] = str(error)
            _LOG.warning("telegram: %s", error)

    threading.Thread(target=worker, name="telegram", daemon=True).start()


def send_test() -> dict[str, object]:
    credentials = _credentials()
    if credentials is None:
        return {"ok": False, "message": "Telegram đang tắt hoặc thiếu mã bot, mã chat."}
    try:
        _post(credentials[0], credentials[1], "✅ <b>GoldTrader</b>\nKết nối Telegram thành công. Bot sẽ gửi quyết định vào lệnh và kết quả mỗi lệnh.")
    except RuntimeError as error:
        _STATUS["lastError"] = str(error)
        return {"ok": False, "message": str(error)}
    _STATUS["lastError"] = ""
    _STATUS["lastSent"] = datetime.now(VN_TZ).strftime("%d/%m %H:%M:%S")
    return {"ok": True, "message": "Đã gửi tin thử. Kiểm tra Telegram của bạn."}


def _money(value: float) -> str:
    return f"{value:+,.2f} $".replace(",", " ")


def order_text(symbol: str, timeframe: str, strategy: str, row: dict[str, object], equity: float, reason: str) -> str:
    """Short order message: side, agent, price, stop/take, size, risk. No explanation."""
    side = "MUA" if row["side"] == "buy" else "BÁN"
    icon = "🟢" if row["side"] == "buy" else "🔴"
    risk = float(row["risk_money"] or 0)
    risk_pct = risk / equity * 100 if equity > 0 else 0
    take = float(row["tp"] or 0)
    return (
        f"{icon} <b>{side} {html.escape(symbol)}</b> {float(row['volume']):g} lot @ <code>{float(row['fill']):.2f}</code>\n"
        f"SL <code>{float(row['sl']):.2f}</code> · " + (f"TP <code>{take:.2f}</code>" if take else "TP bám") + f" · rủi ro {risk:.2f}$ ({risk_pct:.1f}%)\n"
        f"{html.escape(strategy)}"
    )


def close_text(symbol: str, row: dict[str, object], stats: dict[str, object]) -> str:
    net = float(row["net"] or 0)
    icon = "✅" if net > 0 else "❌" if net < 0 else "➖"
    side = "MUA" if row["side"] == "buy" else "BÁN"
    r_value = row.get("r")
    r_text = f" ({float(r_value):+.2f}R)" if r_value is not None else ""
    return (
        f"{icon} <b>Đóng {side} {html.escape(symbol)}: {_money(net)}</b>{r_text}\n"
        f"{float(row['fill']):.2f} → {float(row['exit_price'] or 0):.2f} · {html.escape(str(row['exit_reason'] or ''))}"
    )
