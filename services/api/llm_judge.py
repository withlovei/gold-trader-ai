"""Claude as a silent second opinion on every real entry.

After an order is sent, a background thread asks the local Claude CLI to judge the setup and
stores the verdict next to the trade in the journal. The verdict never blocks, shrinks or enlarges
an order: it is only recorded, so that after enough closed trades the journal can show whether
trades Claude opposed did worse than the ones it agreed with. Historical bars are not judged:
the model may already know how gold moved in 2022-2026."""
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from services.api import journal
from services.api.settings_store import DATA_DIR, read_flag

_LOG = logging.getLogger("goldtrader.llm")
TIMEOUT_SECONDS = 60
VERDICTS = ("đồng ý", "nghi ngờ", "phản đối")
NO_OPINION = "không có ý kiến"
SYSTEM = (
    "Bạn là chuyên gia giao dịch vàng XAUUSD, đánh giá một tín hiệu vào lệnh mà bot đã gửi theo quy tắc cố định. "
    "Đọc nến, các điều kiện đã đạt và kế hoạch. Đánh giá chất lượng điểm vào: bối cảnh xu hướng, vị trí so với vùng giá gần, "
    "khoảng cắt lỗ, nhịp đã chạy xa hay chưa, rủi ro đảo chiều. Không lặp lại dữ liệu. "
    'Chỉ trả lời DUY NHẤT một dòng JSON: {"verdict": "đồng ý" | "nghi ngờ" | "phản đối", "reason": "<tối đa 2 câu tiếng Việt>"}.'
)


def enabled() -> bool:
    return read_flag("llmJudge", "on") == "on"


def find_cli() -> str | None:
    """CLAUDE_CLI, then PATH, then the newest CLI bundled with the VS Code extension."""
    explicit = os.environ.get("CLAUDE_CLI")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    pattern = str(Path.home() / ".vscode" / "extensions" / "anthropic.claude-code-*" / "resources" / "native-binary" / "claude.exe")
    candidates = sorted(glob.glob(pattern), key=os.path.getmtime)
    return candidates[-1] if candidates else None


def build_prompt(context: dict[str, object]) -> str:
    rows = context.get("bars") or []
    candles = "\n".join(f"{row[0]} O{row[1]:.2f} H{row[2]:.2f} L{row[3]:.2f} C{row[4]:.2f}" for row in rows)
    gates = "\n".join(f"- {gate['name']}: {'đạt' if gate['state'] == 'ok' else gate['state']}" for gate in context.get("gates") or [])
    return (
        f"Agent: {context.get('agent')}\n"
        f"Lệnh: {'MUA' if context.get('side') == 'buy' else 'BÁN'} {context.get('symbol')} khung {context.get('timeframe')}\n"
        f"Điểm vào {context.get('entry')}, cắt lỗ {context.get('stop')}, chốt lời {context.get('take') or 'không cố định (cắt lỗ bám)'}\n"
        f"ATR14 {context.get('atr')}, giờ khớp {context.get('hour')} UTC, khung lớn {context.get('higher')}\n"
        f"Điều kiện của chiến lược:\n{gates}\n"
        f"{len(rows)} nến gần nhất (giờ UTC, cũ đến mới):\n{candles}\n"
    )


def parse(text: str) -> tuple[str, str]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return NO_OPINION, (text or "").strip()[:300]
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return NO_OPINION, match.group(0)[:300]
    verdict = str(data.get("verdict") or "").strip().lower()
    plain = {"dong y": "đồng ý", "nghi ngo": "nghi ngờ", "phan doi": "phản đối"}
    verdict = plain.get(verdict, verdict)
    if verdict not in VERDICTS:
        verdict = NO_OPINION
    return verdict, str(data.get("reason") or "").strip()[:400]


def ask(context: dict[str, object], runner=subprocess.run) -> tuple[str, str]:
    verdict, reason, _meta = ask_full(context, runner)
    return verdict, reason


def _meta(payload: dict[str, object], seconds: float) -> dict[str, object]:
    """Cost and size of one CLI call as the CLI reports it (total_cost_usd is the API list-price
    equivalent; on a Claude plan it counts against the plan's usage instead of being billed)."""
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    models = payload.get("modelUsage") if isinstance(payload.get("modelUsage"), dict) else {}
    main = max(models.items(), key=lambda item: float((item[1] or {}).get("costUSD") or 0))[0] if models else ""
    return {
        "cost": float(payload.get("total_cost_usd") or 0),
        "ms": int(payload.get("duration_ms") or seconds * 1000),
        "inputTokens": int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0),
        "outputTokens": int(usage.get("output_tokens") or 0),
        "model": str(main),
    }


def ask_full(context: dict[str, object], runner=subprocess.run) -> tuple[str, str, dict[str, object]]:
    import time as _time

    started = _time.monotonic()
    empty = {"cost": 0.0, "ms": 0, "inputTokens": 0, "outputTokens": 0, "model": ""}
    cli = find_cli()
    if not cli:
        return NO_OPINION, "Không tìm thấy Claude CLI trên máy.", empty
    workdir = DATA_DIR / "llm"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        done = runner(
            [cli, "-p", "Đánh giá tín hiệu trong dữ liệu đầu vào.", "--output-format", "json", "--tools", "",
             "--no-session-persistence", "--system-prompt", SYSTEM],
            input=build_prompt(context), capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SECONDS, cwd=str(workdir),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return NO_OPINION, f"Claude không trả lời trong {TIMEOUT_SECONDS} giây.", {**empty, "ms": TIMEOUT_SECONDS * 1000}
    except OSError as error:
        return NO_OPINION, f"Không chạy được Claude CLI: {error}", empty
    try:
        payload = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        return NO_OPINION, (done.stdout or done.stderr or "")[:300], {**empty, "ms": int((_time.monotonic() - started) * 1000)}
    meta = _meta(payload, _time.monotonic() - started)
    if payload.get("is_error"):
        return NO_OPINION, str(payload.get("result") or "Claude báo lỗi.")[:300], meta
    verdict, reason = parse(str(payload.get("result") or ""))
    return verdict, reason, meta


def submit(position: int, context: dict[str, object]) -> threading.Thread | None:
    """Judge in the background; the order is already sent and nothing waits for this."""
    if not enabled():
        return None

    def work() -> None:
        try:
            verdict, reason, meta = ask_full(context)
            journal.set_llm(position, verdict, reason, meta, str(context.get("agentId") or ""))
        except Exception as error:  # never let the judge disturb trading
            _LOG.warning("llm judge %s: %s", position, error)

    thread = threading.Thread(target=work, name=f"llm-judge-{position}", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------------------------
# Pre-trade decision (user's choice 2026-11-09: Claude has the final say on every real entry).
# Each agent is judged by an expert in that agent's own trading method. The answer is
# "vào" (full size), "giảm" (half size) or "bỏ" (skip). Any failure or timeout returns None and
# the bot follows its tested rules, so a broken CLI never costs a trade.

GATE_TIMEOUT_SECONDS = 40
DECISIONS = ("vào", "giảm", "bỏ")
_COMMON = (
    "Bạn ngồi ở bàn giao dịch vàng XAUUSD của một phòng nhiều agent. Bot đã kiểm tra đủ các điều kiện cứng của phương pháp "
    "(đã kiểm thử 2022–2026, có lợi thế dương) và cổng rủi ro của tài khoản; tín hiệu này hợp lệ theo quy tắc. Việc của bạn là "
    "quyết định cuối cùng: vào đủ khối lượng, giảm nửa khối lượng, hay bỏ. "
    "Nguyên tắc ra quyết định: mặc định là VÀO khi tín hiệu đúng phương pháp. Chỉ GIẢM khi có rủi ro cụ thể nhìn thấy trên dữ liệu "
    "(ví dụ: điểm vào sát vùng cản rõ ràng ngay trước mặt, biến động bất thường, xung đột với lệnh đang mở của phòng). "
    "Chỉ BỎ khi có lý do rõ ràng và mạnh rằng tín hiệu sai bản chất của phương pháp. "
    "Không bỏ chỉ vì giá đã chạy hoặc nến xác nhận dài: kiểm thử cho thấy lọc kiểu \"không đuổi giá\" làm giảm lợi nhuận, "
    "và phần lớn lãi của năm đến từ vài lệnh xu hướng lớn trông như vào muộn. "
    "Trả lời DUY NHẤT một dòng JSON: {\"decision\": \"vào\" | \"giảm\" | \"bỏ\", \"reason\": \"<tối đa 2 câu tiếng Việt, nêu bằng chứng cụ thể>\"}."
)
PERSONAS = {
    "trend-M15": (
        "Bạn là chuyên gia giao dịch theo phương pháp của Linda Raschke, đặc biệt mẫu \"Holy Grail\": thị trường có xu hướng mạnh "
        "(ADX cao, EMA xếp tầng), giá hồi về EMA 20 rồi nến xác nhận quay lại theo xu hướng. Bạn đánh giá: xu hướng còn lực hay đang "
        "suy yếu (ADX, độ dốc EMA, đỉnh/đáy mới), nhịp hồi là hồi lành mạnh hay là dấu hiệu đảo chiều (hồi sâu, nến mạnh ngược chiều), "
        "nến xác nhận có thật sự đóng theo xu hướng. Lệnh này dùng cắt lỗ bám 3 ATR sau khi lời 1R, không chốt lời cố định: một lệnh "
        "đúng có thể chạy rất xa, nên đừng bỏ lỡ xu hướng đang mạnh. "
    ),
    "pullback-M15": (
        "Bạn là chuyên gia giao dịch hồi quy ngắn hạn theo phương pháp RSI(2) của Larry Connors: chỉ giao dịch theo xu hướng dài "
        "(giá và EMA 50 cùng phía EMA 200), mua khi RSI(2) xuống quá bán (≤ 20) hoặc bán khi quá mua (≥ 80), vào khi nến bật lại vượt "
        "đỉnh/thủng đáy nến trước, chốt lời nhanh 1,5R hoặc thoát sau 24 nến. Bạn đánh giá: nhịp giảm là quá bán ngắn hạn trong xu hướng "
        "còn nguyên, hay là bắt đầu phá vỡ xu hướng dài (giá thủng EMA 200, chuỗi nến giảm mạnh có lực); khoảng tới mục tiêu 1,5R có "
        "bị vùng cản chặn ngay không. Phương pháp này thắng nhờ tỷ lệ thắng cao và giữ lệnh ngắn. "
    ),
    "trend-M30": (
        "Bạn là chuyên gia theo xu hướng khung lớn theo tinh thần của Ed Seykota: đi theo xu hướng, cắt lỗ ngắn, để lợi nhuận chạy, "
        "không đoán đỉnh đáy. Agent này vào lệnh khi giá M30 hồi về EMA 20 trong xu hướng có ADX và khung H4 cùng chiều, chốt lời 2R "
        "hoặc thoát sau 48 nến M30. Bạn đánh giá: xu hướng M30 còn rõ ràng không, cấu trúc đỉnh/đáy có ủng hộ, có xung đột với lệnh "
        "khung nhỏ hơn của phòng không. "
    ),
}


def decide(context: dict[str, object], runner=subprocess.run) -> dict[str, object] | None:
    """Claude's final call on one entry, by the expert of the agent's method. None = no answer
    (disabled, CLI missing, error, timeout or unreadable): the caller follows its rules."""
    if not enabled():
        return None
    import time as _time

    agent_id = str(context.get("agentId") or "")
    system = (PERSONAS.get(agent_id) or str(context.get("persona") or "") or "Bạn là chuyên gia giao dịch vàng theo xu hướng. ") + _COMMON
    cli = find_cli()
    if not cli:
        return None
    workdir = DATA_DIR / "llm"
    workdir.mkdir(parents=True, exist_ok=True)
    started = _time.monotonic()
    try:
        done = runner(
            [cli, "-p", "Ra quyết định cho tín hiệu trong dữ liệu đầu vào.", "--output-format", "json", "--tools", "",
             "--no-session-persistence", "--system-prompt", system],
            input=build_gate_prompt(context), capture_output=True, text=True, encoding="utf-8", timeout=GATE_TIMEOUT_SECONDS,
            cwd=str(workdir), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        payload = json.loads(done.stdout or "{}")
    except subprocess.TimeoutExpired as error:
        _LOG.warning("llm gate %s: %s", agent_id, error)
        _log_gate(agent_id, "quá giờ", {"cost": 0.0, "ms": int((_time.monotonic() - started) * 1000)})
        return None
    except json.JSONDecodeError as error:
        _LOG.warning("llm gate %s: %s", agent_id, error)
        _log_gate(agent_id, "lỗi", {"cost": 0.0, "ms": int((_time.monotonic() - started) * 1000)})
        return None
    except OSError as error:  # the CLI did not start: no call, nothing to log
        _LOG.warning("llm gate %s: %s", agent_id, error)
        return None
    meta = _meta(payload, _time.monotonic() - started)
    if payload.get("is_error"):
        _log_gate(agent_id, "lỗi", meta)
        return None
    match = re.search(r"\{.*\}", str(payload.get("result") or ""), re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    decision = str(data.get("decision") or "").strip().lower()
    decision = {"vao": "vào", "giam": "giảm", "bo": "bỏ"}.get(decision, decision)
    if decision not in DECISIONS:
        _log_gate(agent_id, "lỗi", meta)
        return None
    _log_gate(agent_id, decision, meta)
    return {"decision": decision, "reason": str(data.get("reason") or "").strip()[:400], "meta": meta,
            "factor": 1.0 if decision == "vào" else 0.5 if decision == "giảm" else 0.0}


def _log_gate(agent_id: str, verdict: str, meta: dict[str, object]) -> None:
    """Every gate call is logged here, once, whatever happens to the order afterwards."""
    try:
        journal.log_llm_call(agent_id, 0, verdict, meta)
    except (OSError, ValueError) as error:
        _LOG.warning("llm gate log: %s", error)


def build_gate_prompt(context: dict[str, object]) -> str:
    rows = context.get("bars") or []
    candles = "\n".join(f"{row[0]} O{row[1]:.2f} H{row[2]:.2f} L{row[3]:.2f} C{row[4]:.2f}" for row in rows)
    gates = "\n".join(f"- {gate['name']}: {'đạt' if gate['state'] == 'ok' else 'không áp dụng' if gate['state'] == 'skip' else gate['state']}" for gate in context.get("gates") or [])
    office = "\n".join(f"- {line}" for line in context.get("office") or []) or "- (không có)"
    risk = abs(float(context.get("entry") or 0) - float(context.get("stop") or 0))
    take = context.get("take")
    return (
        f"TÍN HIỆU CỦA BẠN — agent {context.get('agent')}\n"
        f"{'MUA' if context.get('side') == 'buy' else 'BÁN'} {context.get('symbol')} khung {context.get('timeframe')}, "
        f"điểm vào ~{context.get('entry')}, cắt lỗ {context.get('stop')} (cách {risk:.2f}, {risk / max(float(context.get('atr') or 1), 1e-9):.1f} ATR), "
        f"chốt lời {take if take else 'không cố định, cắt lỗ bám'}\n"
        f"ATR14 {context.get('atr')}, giờ khớp {context.get('hour')}:00 UTC, khung lớn: {context.get('higher')}\n"
        f"Điều kiện của phương pháp (theo thứ tự bot kiểm tra):\n{gates}\n\n"
        f"TÌNH HÌNH PHÒNG GIAO DỊCH\n{office}\n\n"
        f"{len(rows)} NẾN {context.get('timeframe')} GẦN NHẤT (giờ UTC, cũ đến mới)\n{candles}\n"
    )
