"""Trade journal: every automated order is recorded when sent and reconciled with MetaTrader's
deal history when it closes, so live results can be compared with the backtest."""
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from services.api.settings_store import DB_PATH, DATA_DIR

VN_TZ = timezone(timedelta(hours=7))
# Walk-forward expectation of the live book (trend with trailing stop + RSI(2) pullback, M15,
# 2022-2026, one position at a time, signal-bar filters from 2026-11-08), used as the yardstick.
EXPECTED = {"averageR": 0.15, "winRate": 0.42, "profitFactor": 1.3}
_COLUMNS = (
    "position", "opened_at", "signal_bar", "strategy", "side", "planned_entry", "requested",
    "fill", "slippage", "sl", "tp", "volume", "risk_money", "spread", "status", "closed_at",
    "exit_price", "profit", "commission", "swap", "net", "r", "exit_reason", "bars_held",
)


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_journal (
            position INTEGER PRIMARY KEY,
            opened_at INTEGER NOT NULL,
            signal_bar INTEGER,
            strategy TEXT,
            side TEXT NOT NULL,
            planned_entry REAL,
            requested REAL,
            fill REAL,
            slippage REAL,
            sl REAL,
            tp REAL,
            volume REAL,
            risk_money REAL,
            spread REAL,
            status TEXT NOT NULL,
            closed_at INTEGER,
            exit_price REAL,
            profit REAL,
            commission REAL,
            swap REAL,
            net REAL,
            r REAL,
            exit_reason TEXT,
            bars_held INTEGER
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(trade_journal)")}
    for name, kind in (("score", "REAL"), ("size_factor", "REAL"), ("agent", "TEXT"), ("llm_verdict", "TEXT"), ("llm_reason", "TEXT"), ("llm_cost", "REAL"), ("llm_ms", "INTEGER")):
        if name not in columns:
            connection.execute(f"ALTER TABLE trade_journal ADD COLUMN {name} {kind}")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at INTEGER NOT NULL,
            agent TEXT,
            position INTEGER,
            verdict TEXT,
            cost REAL NOT NULL DEFAULT 0,
            ms INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            model TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_vetoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at INTEGER NOT NULL,
            agent TEXT,
            signal_bar INTEGER,
            timeframe TEXT,
            side TEXT,
            entry REAL,
            stop REAL,
            take REAL,
            reason TEXT
        )
        """
    )
    return connection


def record_open(entry: dict[str, object]) -> dict[str, object]:
    """entry: position, signal_bar, strategy, side, planned_entry, requested, fill, sl, tp,
    volume, risk_money, spread. Slippage is signed so that a positive value is a worse fill."""
    side = str(entry["side"])
    requested = float(entry["requested"])
    fill = float(entry["fill"])
    slippage = (fill - requested) if side == "buy" else (requested - fill)
    row = {
        "position": int(entry["position"]),
        "opened_at": int(entry.get("opened_at") or time.time()),
        "signal_bar": int(entry.get("signal_bar") or 0),
        "strategy": str(entry.get("strategy") or ""),
        "side": side,
        "planned_entry": float(entry.get("planned_entry") or 0),
        "requested": requested,
        "fill": fill,
        "slippage": round(slippage, 3),
        "sl": float(entry.get("sl") or 0),
        "tp": float(entry.get("tp") or 0),
        "volume": float(entry.get("volume") or 0),
        "risk_money": float(entry.get("risk_money") or 0),
        "spread": float(entry.get("spread") or 0),
        "status": "open",
        "score": None if entry.get("score") is None else float(entry["score"]),
        "size_factor": float(entry.get("size_factor") or 1.0),
        "agent": str(entry.get("agent") or ""),
    }
    with _connect() as connection:
        connection.execute(
            f"INSERT OR REPLACE INTO trade_journal ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
    return row


def sync_closed(mt5: object, bar_seconds: int) -> list[dict[str, object]]:
    """Close journal rows whose MetaTrader position is gone. Returns the rows closed now."""
    with _connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM trade_journal WHERE status = 'open'")]
    closed: list[dict[str, object]] = []
    for row in rows:
        position = int(row["position"])
        if mt5.positions_get(ticket=position):
            continue
        deals = mt5.history_deals_get(position=position) or []
        exits = [deal for deal in deals if int(getattr(deal, "entry", -1)) in {1, 3}]
        if not exits:
            continue
        last = max(exits, key=lambda deal: int(deal.time))
        profit = sum(float(deal.profit) for deal in deals)
        commission = sum(float(getattr(deal, "commission", 0) or 0) + float(getattr(deal, "fee", 0) or 0) for deal in deals)
        swap = sum(float(deal.swap) for deal in deals)
        net = profit + commission + swap
        risk = float(row["risk_money"] or 0)
        update = {
            "status": "closed",
            "closed_at": int(last.time),
            "exit_price": float(last.price),
            "profit": round(profit, 2),
            "commission": round(commission, 2),
            "swap": round(swap, 2),
            "net": round(net, 2),
            "r": round(net / risk, 2) if risk > 0 else None,
            "exit_reason": "Cắt lỗ bám" if _reason(last) == "Cắt lỗ" and net > 0 else _reason(last),
            "bars_held": max(0, (int(last.time) - int(row["opened_at"])) // max(1800 if str(row["strategy"] or "").endswith(" M30") else 900 if str(row["strategy"] or "").endswith(" M15") else bar_seconds, 1)),
        }
        with _connect() as connection:
            connection.execute(
                f"UPDATE trade_journal SET {', '.join(key + ' = ?' for key in update)} WHERE position = ?",
                (*update.values(), position),
            )
        row.update(update)
        closed.append(row)
    return closed


def _reason(deal: object) -> str:
    reason = int(getattr(deal, "reason", -1))
    comment = str(getattr(deal, "comment", "") or "").lower()
    if reason == 4 or "sl" in comment.split():
        return "Cắt lỗ"
    if reason == 5 or "tp" in comment.split():
        return "Chốt lời"
    if "het gio" in comment:
        return "Hết giờ giữ lệnh"
    if reason == 6:
        return "Bị dừng do ký quỹ"
    if reason in {0, 1, 2}:
        return "Đóng tay"
    return "Đóng tự động"


def summary(limit: int = 60) -> dict[str, object]:
    with _connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM trade_journal ORDER BY opened_at DESC LIMIT ?", (limit,))]
        closed = [dict(row) for row in connection.execute("SELECT * FROM trade_journal WHERE status = 'closed'")]
    wins = [row for row in closed if float(row["net"] or 0) > 0]
    gains = sum(float(row["net"] or 0) for row in wins)
    losses = -sum(float(row["net"] or 0) for row in closed if float(row["net"] or 0) < 0)
    r_values = [float(row["r"]) for row in closed if row["r"] is not None]
    slips = [float(row["slippage"]) for row in closed + [row for row in rows if row["status"] == "open"] if row["slippage"] is not None]
    count = len(closed)
    stats = {
        "closed": count,
        "open": sum(1 for row in rows if row["status"] == "open"),
        "net": round(sum(float(row["net"] or 0) for row in closed), 2),
        "winRate": round(len(wins) / count, 3) if count else None,
        "profitFactor": round(gains / losses, 2) if losses > 0 else None,
        "averageR": round(sum(r_values) / len(r_values), 3) if r_values else None,
        "totalR": round(sum(r_values), 2) if r_values else 0.0,
        "averageSlippage": round(sum(slips) / len(slips), 3) if slips else None,
        "expected": EXPECTED,
        "verdict": _verdict(count, r_values),
        "llm": {**_llm_table(closed), "costs": llm_costs()},
    }
    return {"ok": True, "stats": stats, "rows": [_display(row) for row in rows]}


def _verdict(count: int, r_values: list[float]) -> str:
    if count < 40:
        return f"Mới {count} lệnh đóng. Cần khoảng 40 lệnh trước khi so với kiểm thử có ý nghĩa."
    average = sum(r_values) / len(r_values) if r_values else 0.0
    if average >= EXPECTED["averageR"] * 0.5:
        return f"Trung bình {average:+.2f}R mỗi lệnh, phù hợp với kiểm thử (+{EXPECTED['averageR']:.2f}R)."
    if average > 0:
        return f"Trung bình {average:+.2f}R mỗi lệnh, dương nhưng thấp hơn kiểm thử. Xem lại trượt giá và giờ vào lệnh."
    return f"Trung bình {average:+.2f}R mỗi lệnh, âm trong khi kiểm thử dương. Nên dừng và xem lại trước khi chạy tiếp."


def _display(row: dict[str, object]) -> dict[str, object]:
    def stamp(value: object) -> str:
        return datetime.fromtimestamp(int(value), VN_TZ).strftime("%d/%m %H:%M") if value else ""

    return {
        "position": row["position"],
        "opened": stamp(row["opened_at"]),
        "closed": stamp(row["closed_at"]),
        "strategy": row["strategy"],
        "side": "Mua" if row["side"] == "buy" else "Bán",
        "fill": row["fill"],
        "slippage": row["slippage"],
        "sl": row["sl"],
        "tp": row["tp"],
        "volume": row["volume"],
        "riskMoney": row["risk_money"],
        "status": "Đang mở" if row["status"] == "open" else "Đã đóng",
        "exit": row["exit_price"],
        "net": row["net"],
        "r": row["r"],
        "reason": row["exit_reason"] or "",
        "bars": row["bars_held"],
        "score": row.get("score"),
        "sizeFactor": row.get("size_factor"),
        "agent": _agent_label(row),
        "llmVerdict": row.get("llm_verdict") or "",
        "llmReason": row.get("llm_reason") or "",
        "llmCost": row.get("llm_cost"),
        "llmSeconds": None if not row.get("llm_ms") else round(int(row["llm_ms"]) / 1000, 1),
    }


# Rows written before the multi-agent change carry no agent id: map them by strategy name.
LEGACY_AGENT = {"Theo xu hướng": "trend-M15", "Hồi giá": "pullback-M15", "Theo xu hướng M30": "trend-M30"}


def agent_stats() -> dict[str, dict[str, object]]:
    """Closed-trade results per agent."""
    with _connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM trade_journal")]
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        name = str(row.get("agent") or "") or LEGACY_AGENT.get(str(row.get("strategy") or ""), "")
        if name:
            groups.setdefault(name, []).append(row)
    result = {}
    for name, items in groups.items():
        closed = [row for row in items if row["status"] == "closed"]
        r_values = [float(row["r"]) for row in closed if row["r"] is not None]
        gains = sum(float(row["net"] or 0) for row in closed if float(row["net"] or 0) > 0)
        losses = -sum(float(row["net"] or 0) for row in closed if float(row["net"] or 0) < 0)
        result[name] = {
            "closed": len(closed),
            "open": sum(1 for row in items if row["status"] == "open"),
            "net": round(sum(float(row["net"] or 0) for row in closed), 2),
            "totalR": round(sum(r_values), 2),
            "averageR": round(sum(r_values) / len(r_values), 3) if r_values else None,
            "winRate": round(sum(1 for value in r_values if value > 0) / len(r_values), 3) if r_values else None,
            "profitFactor": round(gains / losses, 2) if losses > 0 else None,
        }
    return result


def _agent_label(row: dict[str, object]) -> str:
    from services.api.agents import label

    key = str(row.get("agent") or "") or LEGACY_AGENT.get(str(row.get("strategy") or ""), "")
    return label(key) if key else ""


def set_llm(position: int, verdict: str, reason: str, meta: dict[str, object] | None = None, agent: str = "", log: bool = True) -> None:
    meta = meta or {}
    with _connect() as connection:
        connection.execute(
            "UPDATE trade_journal SET llm_verdict = ?, llm_reason = ?, llm_cost = ?, llm_ms = ? WHERE position = ?",
            (verdict, reason, float(meta.get("cost") or 0), int(meta.get("ms") or 0), int(position)),
        )
        if not agent:
            row = connection.execute("SELECT agent, strategy FROM trade_journal WHERE position = ?", (int(position),)).fetchone()
            if row is not None:
                agent = str(row["agent"] or "") or LEGACY_AGENT.get(str(row["strategy"] or ""), "")
    if log:
        log_llm_call(agent, int(position), verdict, meta)


def log_llm_call(agent: str, position: int, verdict: str, meta: dict[str, object] | None) -> None:
    meta = meta or {}
    with _connect() as connection:
        connection.execute(
            "INSERT INTO llm_calls (at, agent, position, verdict, cost, ms, input_tokens, output_tokens, model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(time.time()), agent, int(position), verdict, float(meta.get("cost") or 0), int(meta.get("ms") or 0),
             int(meta.get("inputTokens") or 0), int(meta.get("outputTokens") or 0), str(meta.get("model") or "")),
        )


def record_veto(agent: str, signal_bar: int, timeframe: str, side: str, entry: float, stop: float, take: float | None, reason: str, meta: dict[str, object] | None) -> None:
    """A signal Claude decided to skip: kept with its plan so the skips can be judged later."""
    with _connect() as connection:
        connection.execute(
            "INSERT INTO llm_vetoes (at, agent, signal_bar, timeframe, side, entry, stop, take, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(time.time()), agent, int(signal_bar), timeframe, side, float(entry), float(stop), None if not take else float(take), reason),
        )  # the call itself is logged by llm_judge.decide


def vetoes(limit: int = 30) -> list[dict[str, object]]:
    with _connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM llm_vetoes ORDER BY at DESC LIMIT ?", (limit,))]
    from services.api.agents import label

    return [
        {**row, "agentLabel": label(str(row["agent"] or "")), "when": datetime.fromtimestamp(int(row["at"]), VN_TZ).strftime("%d/%m %H:%M")}
        for row in rows
    ]


def llm_costs() -> dict[str, object]:
    """What the Claude second opinion has cost: today (VN day), last 30 days, all time, per agent."""
    now = int(time.time())
    day_start = int(datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    with _connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT at, agent, verdict, cost, ms, input_tokens, output_tokens FROM llm_calls ORDER BY at")]

    def total(items: list[dict[str, object]]) -> dict[str, object]:
        cost = sum(float(item["cost"] or 0) for item in items)
        return {
            "calls": len(items),
            "cost": round(cost, 4),
            "averageCost": round(cost / len(items), 4) if items else None,
            "averageSeconds": round(sum(int(item["ms"] or 0) for item in items) / len(items) / 1000, 1) if items else None,
        }

    def per_agent(items: list[dict[str, object]]) -> dict[str, object]:
        last = items[-1]
        decisions: dict[str, int] = {}
        for item in items:
            decisions[str(item["verdict"] or "")] = decisions.get(str(item["verdict"] or ""), 0) + 1
        return {
            **total(items),
            "today": total([item for item in items if int(item["at"]) >= day_start]),
            "month": total([item for item in items if int(item["at"]) >= now - 30 * 86400]),
            "inputTokens": sum(int(item["input_tokens"] or 0) for item in items),
            "outputTokens": sum(int(item["output_tokens"] or 0) for item in items),
            "decisions": decisions,
            "last": {"at": datetime.fromtimestamp(int(last["at"]), VN_TZ).strftime("%d/%m %H:%M"), "verdict": last["verdict"],
                     "cost": round(float(last["cost"] or 0), 4), "seconds": round(int(last["ms"] or 0) / 1000, 1)},
        }

    agents: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        agents.setdefault(str(row["agent"] or ""), []).append(row)
    return {
        "today": total([row for row in rows if int(row["at"]) >= day_start]),
        "month": total([row for row in rows if int(row["at"]) >= now - 30 * 86400]),
        "all": total(rows),
        "agents": {name: per_agent(items) for name, items in agents.items() if name},
        "note": "Chi phí quy đổi theo giá API do Claude CLI báo (total_cost_usd). Dùng gói Claude thì trừ vào lượt dùng của gói, không tính tiền riêng.",
    }


LLM_MIN_TRADES = 40


def _llm_table(closed: list[dict[str, object]]) -> dict[str, object]:
    """Closed trades grouped by Claude's verdict. A conclusion only once every group that is
    compared has LLM_MIN_TRADES trades."""
    groups: dict[str, list[float]] = {}
    for row in closed:
        if row.get("llm_verdict") and row.get("r") is not None:
            groups.setdefault(str(row["llm_verdict"]), []).append(float(row["r"]))
    rows = [
        {"verdict": name, "trades": len(values), "averageR": round(sum(values) / len(values), 3), "winRate": round(sum(1 for v in values if v > 0) / len(values), 3)}
        for name, values in sorted(groups.items())
    ]
    agree = groups.get("vào", []) + groups.get("đồng ý", [])
    oppose = groups.get("giảm", []) + groups.get("phản đối", []) + groups.get("nghi ngờ", [])
    if len(agree) < LLM_MIN_TRADES or len(oppose) < LLM_MIN_TRADES:
        note = f"Claude đang quyết định vào / giảm / bỏ. Cần mỗi nhóm (vào, giảm) ít nhất {LLM_MIN_TRADES} lệnh đóng để đánh giá."
    else:
        gap = sum(agree) / len(agree) - sum(oppose) / len(oppose)
        note = (
            f"Lệnh Claude cho vào đủ hơn lệnh Claude giảm {gap:+.2f}R mỗi lệnh. "
            + ("Claude đang lọc có ích." if gap >= 0.15 else "Chưa thấy Claude giúp lọc lệnh; cân nhắc trả quyền về quy tắc.")
        )
    return {"rows": rows, "note": note}


def initial_risk(position: int) -> float | None:
    """Price distance between the fill and the stop the position was opened with."""
    with _connect() as connection:
        row = connection.execute("SELECT fill, sl FROM trade_journal WHERE position = ?", (int(position),)).fetchone()
    if row is None or not row["fill"] or not row["sl"]:
        return None
    risk = abs(float(row["fill"]) - float(row["sl"]))
    return risk if risk > 0 else None


# ---------------------------------------------------------------- head of desk log
def _log_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS manager_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at INTEGER NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            detail TEXT
        )"""
    )
    if "meeting" not in {row[1] for row in connection.execute("PRAGMA table_info(manager_log)")}:
        connection.execute("ALTER TABLE manager_log ADD COLUMN meeting TEXT")


def log_manager(kind: str, text: str, detail: object = None, meeting: str = "") -> None:
    """One line of the head of desk's diary: arbitration, meeting, decision, code change, rollback,
    restart. detail keeps everything (CLI answers, diffs) as JSON."""
    import json as _json
    import time as _time

    with _connect() as connection:
        _log_table(connection)
        connection.execute("INSERT INTO manager_log (at, kind, text, detail, meeting) VALUES (?, ?, ?, ?, ?)",
                           (int(_time.time()), kind, text, None if detail is None else _json.dumps(detail, ensure_ascii=False), meeting or None))


def manager_log(limit: int = 200, kind: str = "") -> list[dict[str, object]]:
    import json as _json

    with _connect() as connection:
        _log_table(connection)
        query = "SELECT * FROM manager_log" + (" WHERE kind = ?" if kind else "") + " ORDER BY id DESC LIMIT ?"
        rows = [dict(row) for row in connection.execute(query, ((kind, limit) if kind else (limit,)))]
    for row in rows:
        try:
            row["detail"] = _json.loads(row["detail"]) if row["detail"] else None
        except ValueError:
            pass
    return rows


def meetings_log(limit: int = 20) -> list[dict[str, object]]:
    """The diary grouped by meeting, newest meeting first, each with its entries in order."""
    rows = manager_log(5000)
    groups: dict[str, dict[str, object]] = {}
    for row in reversed(rows):
        key = row.get("meeting")
        if not key:
            continue
        group = groups.setdefault(key, {"id": key, "start": row["at"], "end": row["at"], "entries": []})
        group["end"] = row["at"]
        group["entries"].append(row)
    out = sorted(groups.values(), key=lambda group: -int(group["start"]))[:limit]
    for group in out:
        entries = group["entries"]
        summary = next((str(e["text"])[len("Biên bản: "):] for e in entries if e["kind"] == "meeting" and str(e["text"]).startswith("Biên bản")), "")
        group["summary"] = summary
        group["up"] = [e["text"] for e in entries if e["kind"] == "change" and (e.get("detail") or {}).get("real")]
        group["down"] = [e["text"] for e in entries if e["kind"] == "change" and not (e.get("detail") or {}).get("real")]
        group["code"] = sum(1 for e in entries if e["kind"] == "code" and "Đã sửa" in str(e["text"]))
        group["rollback"] = sum(1 for e in entries if e["kind"] == "rollback")
        group["interrupted"] = any("gián đoạn" in str(e["text"]) for e in entries)
        group["failed"] = not summary and any(str(e["text"]).startswith(("Không họp được", "Cuộc họp lỗi")) for e in entries)
    return out
