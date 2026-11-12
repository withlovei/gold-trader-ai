"""Daily desk meeting (user, 2026-11-11): once a trading day at 22:10 UTC (5:10 Vietnam time,
right after gold's daily close) the head of desk asks the Claude CLI to review every agent and
decide, with full authority, who trades real money and who goes back to paper. Agents the CLI
wants improved get a second CLI run that edits their source directly (the user chose no backtest
gate). The only safety kept: the code is backed up before every edit, a smoke test (import +
one evaluation) runs after it, and a broken edit or a server that fails to restart is rolled
back. Minutes are saved in data/meetings/ and sent to Telegram."""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import random
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.api.settings_store import DATA_DIR, read_flag, write_flag

_LOG = logging.getLogger("goldtrader.meeting")
ROOT = Path(__file__).resolve().parents[2]
MEETING_DIR = DATA_DIR / "meetings"
BACKUP_DIR = DATA_DIR / "backups"
MEETING_HOUR_UTC, MEETING_MINUTE_UTC = 22, 10
DECIDE_TIMEOUT = 600
IMPROVE_TIMEOUT = 1800
MAX_IMPROVE = 2  # CLI code runs per meeting (each can take many minutes)
_RUNNING = threading.Lock()
_STATUS: dict[str, object] = {"running": False, "step": "", "startedAt": "", "events": [], "result": None}


def _event(text: str, kind: str = "step") -> None:
    """One line of the running meeting's progress (shown live in the dashboard dialog)."""
    events = _STATUS.setdefault("events", [])
    events.append({"at": datetime.now(VN_TZ).strftime("%H:%M:%S"), "kind": kind, "text": text})
    del events[:-200]


def _step(text: str) -> None:
    _STATUS["step"] = text
    _event(text)
VN_TZ = timezone(timedelta(hours=7))

DECIDE_SYSTEM = (
    "Bạn là trưởng phòng giao dịch vàng XAUUSD (theo phương pháp quản trị rủi ro 'phòng thủ trước'). "
    "Mỗi ngày bạn họp với các agent, mỗi agent chạy một chiến lược. Bạn có toàn quyền quyết định agent nào được giao dịch "
    "tiền thật và agent nào xuống bàn giấy (chỉ ghi lệnh giấy), và chỉ định agent nào cần cải tiến mã nguồn. "
    "Cân nhắc: kiểm thử dài hạn 2022-2026 đáng tin hơn vài lệnh thật; một ngày lỗ không chứng minh chiến lược hỏng; "
    "lệnh giấy là bằng chứng thật về tín hiệu; mục tiêu là lãi nhiều nhất, lỗ ít nhất cho cả phòng. "
    "Chỉ trả lời DUY NHẤT một khối JSON, không kèm chữ nào khác: "
    '{"summary": "<biên bản 3-6 câu tiếng Việt>", '
    '"decisions": [{"id": "<agent id>", "real": true|false, "reason": "<1 câu>"}], '
    '"improve": [{"id": "<agent id>", "goal": "<cần cải tiến gì, cụ thể, tiếng Việt>"}]}. '
    "decisions liệt kê mọi agent (giữ nguyên cũng ghi). improve tối đa 2 agent, có thể rỗng."
)

IMPROVE_SYSTEM = (
    "Bạn là lập trình viên của hệ thống GoldTrader (Python, FastAPI, MetaTrader 5). Trưởng phòng giao cho bạn cải tiến "
    "chiến lược của một agent. Sửa trực tiếp mã nguồn của chiến lược đó. Quy tắc: chỉ sửa logic của chiến lược này "
    "(điều kiện vào, cắt lỗ, chốt lời, thời gian giữ lệnh); giữ nguyên tên lớp, id, magic, chữ ký hàm và định dạng thẻ trả về; "
    "không sửa services/api/meeting.py, services/api/restart.py, live.py, journal.py, settings_store.py, main.py; "
    "không thêm thư viện mới; không nhìn trước tương lai (chỉ dùng nến đã đóng). Nếu chiến lược nằm trong strategies.py thì "
    "nhớ nó có thể dùng chung cho nhiều agent khác khung thời gian. Khi xong, dòng cuối cùng trả lời DUY NHẤT một JSON: "
    '{"summary": "<đã sửa gì, tiếng Việt, 2-4 câu>", "files": ["<đường dẫn đã sửa>"]}.'
)


# ---------------------------------------------------------------- schedule
def _log(kind: str, text: str, detail: object = None) -> None:
    try:
        from services.api import journal

        journal.log_manager(kind, text, detail, str(_STATUS.get("meetingId") or "") if _STATUS.get("running") else "")
        if _STATUS.get("running"):
            _event(text, kind)
    except Exception as error:  # noqa: BLE001  the diary must never stop the meeting
        _LOG.warning("manager log: %s", error)


def status() -> dict[str, object]:
    return {**_STATUS, "events": list(_STATUS.get("events") or [])}


def due(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Saturday / Sunday UTC: no trading day closed
        return False
    if (now.hour, now.minute) < (MEETING_HOUR_UTC, MEETING_MINUTE_UTC):
        return False
    return read_flag("meetingDate", "") != now.strftime("%Y-%m-%d")


_INTERRUPT_CHECKED = False


def _check_interrupted() -> None:
    """Once per server start: a meeting flagged as running but not running in this process was cut
    off by a restart; say so in the diary (its CLI edit may still be finishing on its own)."""
    global _INTERRUPT_CHECKED
    if _INTERRUPT_CHECKED:
        return
    _INTERRUPT_CHECKED = True
    started = read_flag("meetingRunning", "")
    if started and not _RUNNING.locked():
        write_flag("meetingRunning", "")
        _STATUS["meetingId"] = started
        _STATUS["running"] = True  # tag the note with that meeting
        _log("meeting", f"Cuộc họp bắt đầu lúc {started} bị gián đoạn do server khởi động lại. Các quyết định đã ghi phía trên vẫn có hiệu lực; "
             "bước chưa xong (sửa mã, khởi động lại) không được hoàn tất tự động.")
        _STATUS["running"] = False


def maybe_start(snapshot: dict[str, object] | None = None) -> bool:
    """Called by the autopilot loop: start today's meeting on its own thread when it is due."""
    _check_interrupted()
    if not due() or _RUNNING.locked():
        return False
    write_flag("meetingDate", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return start(snapshot)


def start(snapshot: dict[str, object] | None = None) -> bool:
    if _RUNNING.locked():
        return False
    threading.Thread(target=run, args=(snapshot,), name="meeting", daemon=True).start()
    return True


# ---------------------------------------------------------------- the meeting
def run(snapshot: dict[str, object] | None = None, runner=subprocess.run, restart: bool = True) -> dict[str, object]:
    if not _RUNNING.acquire(blocking=False):
        return {"ok": False, "message": "Đang họp."}
    started = datetime.now(timezone.utc)
    meeting_id = started.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M")
    _STATUS["meetingId"] = meeting_id
    write_flag("meetingRunning", meeting_id)
    _STATUS.update(running=True, step="", startedAt=started.astimezone(VN_TZ).strftime("%d/%m %H:%M"), events=[], result=None)
    _step("Chuẩn bị số liệu: kiểm thử, lệnh thật, lệnh giấy, lệnh 26 giờ qua của từng agent")
    minutes: dict[str, object] = {"id": meeting_id, "date": started.strftime("%Y-%m-%d"), "startedAt": started.isoformat(), "changes": [], "improvements": []}
    try:
        context = gather(snapshot)
        minutes["context"] = context
        _log("meeting", f"Bắt đầu họp ngày {context['date']}: {len(context['agents'])} agent, "
             f"{sum(1 for agent in context['agents'] if agent['realMoney'])} đang giao dịch tiền thật.", {"context": context})
        _step("Trưởng phòng đang đánh giá các agent (Claude CLI, thường 1–3 phút)…")
        answer, meta = _ask_json(DECIDE_SYSTEM, json.dumps(context, ensure_ascii=False, indent=1), DECIDE_TIMEOUT, runner)
        minutes["llm"] = meta
        minutes["answer"] = answer
        if answer is None:
            minutes["summary"] = "Không họp được: " + str(meta.get("error") or "Claude không trả lời.")
            _log("meeting", minutes["summary"], {"llm": meta})
            return _finish(minutes)
        minutes["summary"] = str(answer.get("summary") or "")
        _log("meeting", "Biên bản: " + minutes["summary"], {"answer": answer, "llm": meta})
        names = {agent["id"]: agent["name"] for agent in context["agents"]}
        for item in answer.get("decisions") or []:
            if isinstance(item, dict) and item.get("id") in names:
                where = "tiền thật" if item.get("real") else "bàn giấy"
                _log("decision", f"{names[item['id']]} → {where}: {item.get('reason') or ''}", item)
        minutes["changes"] = apply_decisions(answer.get("decisions") or [])
        for change in minutes["changes"]:
            _log("change", ("Cho lên tiền thật: " if change["real"] else "Cho xuống bàn giấy: ") + f"{change['name']}. {change['reason']}", change)
        for item in answer.get("improve") or []:
            if isinstance(item, dict) and item.get("id") in names:
                _log("improve", f"Giao cải tiến {names[item['id']]}: {item.get('goal') or ''}", item)
        wanted = [item for item in (answer.get("improve") or []) if isinstance(item, dict) and item.get("id") in context["agentIds"]][:MAX_IMPROVE]
        changed_any = False
        for item in wanted:
            _step(f"Claude CLI đang sửa mã nguồn của {item['id']} (có thể 5–20 phút)…")
            result = improve(str(item["id"]), str(item.get("goal") or ""), context, runner)
            minutes["improvements"].append(result)
            changed_any = changed_any or result.get("status") == "applied"
        if not wanted:
            _event("Không có agent nào cần sửa mã hôm nay.")
        if changed_any and restart:
            # roll back to the state before the FIRST applied edit if the new server fails
            backup = next((item.get("backup") for item in minutes["improvements"] if item.get("status") == "applied"), None)
            minutes["restart"] = request_restart(str(backup or ""))
            _log("restart", minutes["restart"], {"backup": backup})
        return _finish(minutes)
    except Exception as error:  # the meeting must never take the autopilot down
        _LOG.exception("meeting")
        minutes["summary"] = f"Cuộc họp lỗi: {error}"
        _log("meeting", minutes["summary"])
        return _finish(minutes)
    finally:
        _STATUS.update(running=False, step="")
        write_flag("meetingRunning", "")
        _RUNNING.release()


def _finish(minutes: dict[str, object]) -> dict[str, object]:
    minutes["finishedAt"] = datetime.now(timezone.utc).isoformat()
    _STATUS["result"] = {key: value for key, value in minutes.items() if key not in ("context", "answer")}
    _event("Kết thúc họp.", "done")
    MEETING_DIR.mkdir(parents=True, exist_ok=True)
    path = MEETING_DIR / f"{minutes['date']}.json"
    path.write_text(json.dumps(minutes, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        from services.api import notify

        notify.send(telegram_text(minutes))
    except Exception as error:  # noqa: BLE001
        _LOG.warning("meeting notify: %s", error)
    return {"ok": True, **{key: value for key, value in minutes.items() if key != "context"}}


def telegram_text(minutes: dict[str, object]) -> str:
    lines = ["🧑‍💼 <b>Họp trưởng phòng " + str(minutes.get("date")) + "</b>", str(minutes.get("summary") or "")]
    for change in minutes.get("changes") or []:
        lines.append(("⬆️ " if change["real"] else "⬇️ ") + f"{change['name']}: {change['reason']}")
    for item in minutes.get("improvements") or []:
        lines.append(f"🛠 {item.get('name')}: {item.get('statusText')}")
    return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------- data for the CLI
def gather(snapshot: dict[str, object] | None = None) -> dict[str, object]:
    from services.api import journal, live, methods, shadow

    records = journal.agent_stats()
    paper = _paper_stats(shadow)
    since = int(time.time()) - 26 * 3600
    with journal._connect() as connection:
        today = [dict(row) for row in connection.execute(
            "SELECT agent, side, opened_at, closed_at, r, net, exit_reason FROM trade_journal WHERE opened_at >= ? OR closed_at >= ? ORDER BY opened_at", (since, since))]
    agents = []
    for key, config in live.all_books().items():
        strategy_id = str((config.get("strategies") or ("",))[0])
        score, edge, closed = live._manager_score(key, config, records)
        tested = live._method_tested(strategy_id, key)
        crew_tested = None
        try:
            from services.api import agents as crew

            crew_tested = crew.TESTED.get(key)
        except ImportError:
            pass
        agents.append({
            "id": key,
            "name": str(config.get("name") or key),
            "realMoney": live.agent_real(key),
            "timeframe": config.get("timeframe"),
            "strategy": strategy_id,
            "source": source_file(strategy_id),
            "testedEdgeR": round(edge, 3),
            "walkForward": (tested or {}).get("periods") or crew_tested,
            "managerScoreR": round(score, 3),
            "real": records.get(key) or {"closed": 0},
            "paper": paper.get((strategy_id, int(config["seconds"]))) or {"closed": 0},
            "last26h": [
                {"side": row["side"], "opened": _vn(row["opened_at"]), "closed": _vn(row["closed_at"]), "r": row["r"], "net": row["net"], "exit": row["exit_reason"]}
                for row in today if row["agent"] == key
            ],
        })
    account = {}
    if snapshot:
        account = {name: snapshot.get(name) for name in ("balance", "equity", "dailyProfit", "drawdown", "positions")}
    return {
        "date": datetime.now(VN_TZ).strftime("%d/%m/%Y"),
        "account": account,
        "rules": {"perTradeRiskPercent": live.read_risk().get("perTradePercent"), "barForRealInTests": "cả hai giai đoạn ≥ +0.05R và PF ≥ 1.10 (gợi ý, bạn có toàn quyền)"},
        "agents": agents,
        "agentIds": [agent["id"] for agent in agents],
        "previousMeeting": latest_summary(),
    }


def _paper_stats(shadow) -> dict[tuple[str, int], dict[str, object]]:
    with shadow._connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM shadow_trades WHERE status = 'closed'")]
    out: dict[tuple[str, int], list[float]] = {}
    for row in rows:
        if row.get("r") is None:
            continue
        out.setdefault((str(row["strategy"]), shadow._frame(row)), []).append(float(row["r"]))
    stats = {}
    for key, values in out.items():
        losses = -sum(value for value in values if value < 0)
        stats[key] = {"closed": len(values), "averageR": round(sum(values) / len(values), 3), "totalR": round(sum(values), 2),
                      "winRate": round(sum(1 for value in values if value > 0) / len(values), 3),
                      "profitFactor": round(sum(value for value in values if value > 0) / losses, 2) if losses else None,
                      "last10R": [round(value, 2) for value in values[-10:]]}
    return stats


def _vn(stamp: object) -> str:
    return datetime.fromtimestamp(int(stamp), VN_TZ).strftime("%d/%m %H:%M") if stamp else ""


def source_file(strategy_id: str) -> str:
    try:
        from services.api import methods

        method = methods.BY_ID.get(strategy_id)
        if method is not None:
            return str(Path(sys.modules[type(method).__module__].__file__).relative_to(ROOT)).replace("\\", "/")
    except (ImportError, KeyError, ValueError):
        pass
    return "services/api/strategies.py"


# ---------------------------------------------------------------- decisions
def apply_decisions(decisions: list[object]) -> list[dict[str, object]]:
    from services.api import live

    books = live.all_books()
    changes = []
    for item in decisions:
        if not isinstance(item, dict) or item.get("id") not in books or not isinstance(item.get("real"), bool):
            continue
        key, real = str(item["id"]), bool(item["real"])
        if live.agent_real(key) == real:
            continue
        live.set_agent_real(key, real)
        changes.append({"id": key, "name": str(books[key].get("name") or key), "real": real, "reason": str(item.get("reason") or "")})
    return changes


# ---------------------------------------------------------------- code improvement
def improve(agent_id: str, goal: str, context: dict[str, object], runner=subprocess.run) -> dict[str, object]:
    agent = next(item for item in context["agents"] if item["id"] == agent_id)
    result = {"id": agent_id, "name": agent["name"], "goal": goal, "source": agent["source"]}
    backup = backup_code()
    result["backup"] = str(backup)
    before = _fingerprint()
    prompt = (
        f"Agent cần cải tiến: {agent['name']} (id {agent_id}, chiến lược '{agent['strategy']}', khung {agent['timeframe']}).\n"
        f"File mã nguồn chính: {agent['source']}\n"
        f"Yêu cầu của trưởng phòng: {goal}\n\n"
        "Số liệu của agent (kiểm thử, lệnh thật, lệnh giấy, 26 giờ qua):\n"
        + json.dumps(agent, ensure_ascii=False, indent=1)
        + "\n\nĐọc file, sửa trực tiếp để cải tiến theo yêu cầu, rồi trả JSON như hướng dẫn."
    )
    answer, meta = _ask_json(IMPROVE_SYSTEM, prompt, IMPROVE_TIMEOUT, runner, tools="Read,Edit,Write,Grep,Glob", edit=True)
    result["llm"] = meta
    result["summary"] = str((answer or {}).get("summary") or meta.get("error") or "")
    changed = sorted(path for path, digest in _fingerprint().items() if before.get(path) != digest) + sorted(set(before) - set(_fingerprint()))
    result["files"] = changed
    if not changed:
        result.update(status="unchanged", statusText="Claude không sửa file nào. " + result["summary"])
        shutil.rmtree(backup, ignore_errors=True)
        _log("code", f"{agent['name']}: {result['statusText']}", result)
        return result
    result["diff"] = code_diff(backup, changed)
    ok, output = smoke_test()
    if not ok:
        restore_code(backup)
        result.update(status="rolled_back", statusText="Bản sửa làm hỏng mã (chạy thử lỗi), đã khôi phục bản cũ.", smoke=output[-1500:])
        _log("rollback", f"{agent['name']}: {result['statusText']}", result)
        return result
    result.update(status="applied", statusText="Đã sửa " + ", ".join(changed) + ". " + result["summary"])
    _log("code", f"{agent['name']}: {result['statusText']}", result)
    return result


def code_diff(backup: Path | str, files: list[str]) -> str:
    """Unified diff of the edited files against the backup (the diary keeps exactly what changed)."""
    chunks = []
    for name in files:
        old_path, new_path = Path(backup) / name, ROOT / name
        old = old_path.read_text(encoding="utf-8").splitlines(keepends=True) if old_path.exists() else []
        new = new_path.read_text(encoding="utf-8").splitlines(keepends=True) if new_path.exists() else []
        chunks.append("".join(difflib.unified_diff(old, new, "trước/" + name, "sau/" + name)))
    return "\n".join(chunks)


def _code_files() -> list[Path]:
    return [path for path in (ROOT / "services").rglob("*.py") if "__pycache__" not in path.parts]


def _fingerprint() -> dict[str, str]:
    return {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha1(path.read_bytes()).hexdigest() for path in _code_files()}


def backup_code() -> Path:
    target = BACKUP_DIR / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copytree(ROOT / "services", target / "services", ignore=shutil.ignore_patterns("__pycache__"))
    return target


def restore_code(backup: Path | str) -> None:
    source = Path(backup) / "services"
    if not source.exists():
        return
    current = {path.relative_to(ROOT / "services") for path in (ROOT / "services").rglob("*.py") if "__pycache__" not in path.parts}
    saved = {path.relative_to(source) for path in source.rglob("*.py")}
    for extra in current - saved:  # files the CLI created
        (ROOT / "services" / extra).unlink(missing_ok=True)
    shutil.copytree(source, ROOT / "services", dirs_exist_ok=True)


SMOKE = r"""
import random, sys
sys.path.insert(0, r"{root}")
import services.api.main
from services.api import live, methods
from services.api.strategies import evaluate_strategies
random.seed(1)
price, bars, times = 4000.0, [], []
for i in range(700):
    o = price; c = o + random.gauss(0, 6); h = max(o, c) + abs(random.gauss(0, 3)); l = min(o, c) - abs(random.gauss(0, 3))
    bars.append((o, h, l, c)); times.append(1790000000 + i * 900); price = c
from services.api.chart_analysis import _atr, _thresholds
atr = next(value for value in reversed(_atr(bars, 14)) if value is not None)
support, resistance = _thresholds(bars, atr)
for tf in ("M15", "M30", "H1", "H4"):
    out = evaluate_strategies(bars, tf, support, resistance, None, 1.5, times, 10)
    assert isinstance(out.get("selected"), dict)
print("SMOKE OK")
"""


def smoke_test() -> tuple[bool, str]:
    try:
        done = subprocess.run([sys.executable, "-c", SMOKE.replace("{root}", str(ROOT))], capture_output=True, text=True, encoding="utf-8",
                              timeout=300, cwd=str(ROOT), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, "chạy thử quá 300 giây"
    output = (done.stdout or "") + (done.stderr or "")
    return done.returncode == 0 and "SMOKE OK" in output, output


def request_restart(backup: str) -> str:
    """Restart the server with the new code from a detached helper (it outlives this process).
    The helper rolls the code back to `backup` if the new server does not answer."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen([sys.executable, "-m", "services.api.restart", backup or "-", str(_STATUS.get("meetingId") or "")], cwd=str(ROOT), creationflags=flags, close_fds=True)
        return "Đang khởi động lại server với mã mới."
    except OSError as error:
        return f"Không khởi động lại được: {error}. Mã mới sẽ chạy ở lần khởi động sau."


# ---------------------------------------------------------------- CLI
def _ask_json(system: str, prompt: str, timeout: int, runner, tools: str = "", edit: bool = False) -> tuple[dict | None, dict[str, object]]:
    from services.api.llm_judge import find_cli

    cli = find_cli()
    if not cli:
        return None, {"error": "Không tìm thấy Claude CLI trên máy."}
    command = [cli, "-p", "Làm theo hướng dẫn và dữ liệu trong đầu vào.", "--output-format", "json", "--tools", tools,
               "--no-session-persistence", "--append-system-prompt", system]
    if edit:
        command += ["--permission-mode", "acceptEdits"]
    workdir = ROOT if edit else DATA_DIR / "llm"
    Path(workdir).mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        done = runner(command, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout, cwd=str(workdir),
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return None, {"error": f"Claude không xong trong {timeout} giây."}
    except OSError as error:
        return None, {"error": f"Không chạy được Claude CLI: {error}"}
    meta: dict[str, object] = {"seconds": round(time.monotonic() - started, 1)}
    try:
        payload = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        return None, {**meta, "error": (done.stdout or done.stderr or "")[:400]}
    meta["cost"] = payload.get("total_cost_usd")
    meta["raw"] = str(payload.get("result") or "")[:20000]  # the CLI's full answer, for the diary
    if payload.get("is_error"):
        return None, {**meta, "error": str(payload.get("result") or "Claude báo lỗi.")[:400]}
    return _json_block(str(payload.get("result") or "")), meta


def _json_block(text: str) -> dict | None:
    """The last {...} block in the answer that parses as JSON."""
    end = text.rfind("}")
    while end != -1:
        depth = 0
        for start in range(end, -1, -1):
            depth += {"}": 1, "{": -1}.get(text[start], 0)
            if depth == 0:
                try:
                    found = json.loads(text[start:end + 1])
                    if isinstance(found, dict):
                        return found
                except json.JSONDecodeError:
                    pass
                break
        end = text.rfind("}", 0, end)
    return None


# ---------------------------------------------------------------- history for the dashboard
def history(limit: int = 10) -> list[dict[str, object]]:
    if not MEETING_DIR.exists():
        return []
    out = []
    for path in sorted(MEETING_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        item.pop("context", None)
        out.append(item)
    return out


def latest_summary() -> str:
    items = history(1)
    return str(items[0].get("summary") or "") if items else ""
