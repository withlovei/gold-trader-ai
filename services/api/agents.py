"""Strategy agents and the coordinator rules shared by the live bot and the backtest.

Each agent trades one strategy on one timeframe with its own MetaTrader magic, holds at most one
position, and keeps a ledger of its results in R. The coordinator (live.py / backtest.py) gives
real money only to eligible agents, sizes them by a weight earned from long-run results, pauses an
agent that loses too much of its share, and promotes a paper agent once its paper record is good.
"""

# Agents with a validated walk-forward edge start eligible for real money. The others trade on
# paper until their own record earns them money (see promotable()).
# Each agent carries the name of a well-known trader whose style is closest to its rules.
AGENTS: tuple[dict[str, object], ...] = (
    # ADX trend + pullback to EMA20 then resume: Raschke's "Holy Grail" setup
    {"id": "trend-M15", "strategy": "trend", "timeframe": "M15", "magic": 260611, "name": "Theo xu hướng M15", "alias": "Linda Raschke", "core": True},
    # RSI(2) dip while above EMA200: Connors' RSI(2) strategy
    {"id": "pullback-M15", "strategy": "pullback", "timeframe": "M15", "magic": 260613, "name": "Hồi giá M15", "alias": "Larry Connors", "core": True},
    # slower trend follower on the larger frame
    {"id": "trend-M30", "strategy": "trend", "timeframe": "M30", "magic": 260612, "name": "Theo xu hướng M30", "alias": "Ed Seykota", "core": True},
    {"id": "breakout-M15", "strategy": "breakout", "timeframe": "M15", "magic": 260614, "name": "Phá vùng M15", "alias": "Nicolas Darvas", "core": False},
    {"id": "reversal-M15", "strategy": "reversal", "timeframe": "M15", "magic": 260615, "name": "Đảo chiều M15", "alias": "Richard Wyckoff", "core": False},
    {"id": "range-M15", "strategy": "range", "timeframe": "M15", "magic": 260616, "name": "Đi ngang M15", "alias": "John Bollinger", "core": False},
)
# Agents of the live bot that are not part of the backtest crew (live.EXTRA_BOOKS only).
LIVE_ONLY: tuple[dict[str, object], ...] = (
    {"id": "trend-H4", "strategy": "trend", "timeframe": "H4", "magic": 260624, "name": "Theo xu hướng H4", "alias": "John W. Henry", "core": False},
    {"id": "flag-H1", "strategy": "flag", "timeframe": "H1", "magic": 260626, "name": "Cờ tăng H1", "alias": "Thomas Bulkowski", "core": False, "family": "trend"},
)
# The coordinator ("defense first").
COORDINATOR = "Paul Tudor Jones"
COORDINATOR_WHY = "Nổi tiếng với nguyên tắc \"phòng thủ trước\": lo giữ vốn trước rồi mới tính lãi. Hợp vai trưởng phòng giữ rủi ro chung."
# Why each agent carries its name, and its working rules in one line (shown on the dashboard).
PROFILE = {
    "trend-M15": {
        "why": "Mẫu \"Holy Grail\" của Linda Raschke: xu hướng mạnh (ADX), giá hồi về EMA 20 rồi đi tiếp. Đúng luật của agent này.",
        "rule": "Khung M15. EMA xếp chiều, ADX ≥ 15, khung H1 cùng chiều, biến động mở rộng; giá chạm EMA 20 rồi nến xác nhận. Cắt lỗ bám 3 ATR khi lời 1R.",
    },
    "pullback-M15": {
        "why": "Larry Connors là cha đẻ chiến lược RSI(2): mua nhịp giảm ngắn khi giá vẫn trên EMA 200. Đúng luật của agent này.",
        "rule": "Khung M15. Giá và EMA 50 cùng phía EMA 200; RSI(2) nến trước ≤ 20 (≥ 80 để bán), nến bật lại ≥ 1 ATR. Chốt lời 1,5R, tối đa 24 nến.",
    },
    "trend-M30": {
        "why": "Ed Seykota là trader theo xu hướng kinh điển, kiên nhẫn đi theo sóng lớn. Agent này theo xu hướng ở khung lớn hơn.",
        "rule": "Khung M30. Cùng luật theo xu hướng, chốt lời 2R, tối đa 48 nến M30.",
    },
    "breakout-M15": {
        "why": "Nicolas Darvas nổi tiếng với \"hộp Darvas\": chờ giá phá khỏi vùng tích lũy.",
        "rule": "Khung M15. Phá vùng nén 12 nến. Kiểm thử nhiều năm không có lợi thế.",
    },
    "reversal-M15": {
        "why": "Richard Wyckoff mô tả cú \"spring\": giá quét qua đáy rồi quay lại. Agent này săn cú quét thanh khoản.",
        "rule": "Khung M15. Quét qua hỗ trợ/kháng cự rồi nến đảo chiều. Lỗ trong kiểm thử 2022–2026.",
    },
    "trend-H4": {
        "why": "John W. Henry theo xu hướng dài hạn, giữ lệnh theo sóng lớn. Agent này dùng luật theo xu hướng trên nến H4.",
        "rule": "Khung H4. Cùng luật theo xu hướng (EMA, ADX, khung D1 cùng chiều, biến động mở rộng, hồi về EMA 20). Chốt lời 2R, tối đa 48 nến H4. Kiểm thử: 2022–24 +0,13R, 2025–26 +0,26R mỗi lệnh, nhưng chỉ khoảng 1 lệnh/tháng.",
    },
    "flag-H1": {
        "why": "Thomas Bulkowski viết bộ bách khoa mô hình giá, đo thống kê hàng nghìn mô hình. Agent này giao dịch cờ tăng trên khung H1.",
        "rule": "Khung H1. Cờ tăng: nhịp tăng ≥ 4 ATR, nghỉ ≤ 50%, nến đóng phá đỉnh cờ, trong xu hướng dài tăng. ZigZag 1,5 ATR. Kiểm thử trên bộ kiểm thử của hệ thống: 2022–24 +0,10R, 2025–26 +0,08R mỗi lệnh.",
    },
    "range-M15": {
        "why": "John Bollinger, cha đẻ dải Bollinger, gắn với giao dịch trong biên độ.",
        "rule": "Khung M15. Mua đáy, bán đỉnh vùng đi ngang. Kiểm thử nhiều năm không có lợi thế.",
    },
}
# Multi-agent backtest (variant E, $10,000, spread 0.2, saved M15 history 09/2022 - 06/11/2026):
# trades and R of each agent per year. Shown on the "Phương pháp" page next to the live record.
TESTED = {
    "trend-M15": {"period": "09/2022–11/2026", "trades": 767, "totalR": 116.6, "averageR": 0.152,
                  "years": {"2022": 2.7, "2023": 16.3, "2024": 20.9, "2025": 25.9, "2026": 50.8}},
    "pullback-M15": {"period": "09/2022–11/2026", "trades": 442, "totalR": 83.1, "averageR": 0.188,
                     "years": {"2022": 5.2, "2023": 12.3, "2024": 19.9, "2025": 29.3, "2026": 16.4}},
    "trend-M30": {"period": "09/2022–11/2026", "trades": 490, "totalR": 59.8, "averageR": 0.122,
                  "years": {"2022": -4.0, "2023": 20.1, "2024": 8.0, "2025": 29.5, "2026": 6.2}},
}
# How each agent enters and exits, step by step (the page lists them in order).
METHOD = {
    "trend-M15": {
        "entry": ["EMA 20, 50, 200 xếp cùng chiều", "ADX ≥ 15: thị trường có xu hướng", "Khung H1 cùng chiều", "Biến động đang mở rộng (ATR14 so với ATR100)",
                  "Giá hồi chạm EMA 20", "Nến xác nhận đóng theo xu hướng, ngoài giờ cấm"],
        "exit": ["Cắt lỗ ban đầu theo ATR dưới/trên nhịp hồi", "Lời 1R thì bật cắt lỗ bám 3 ATR", "Không chốt lời cố định: để lệnh đúng chạy xa"],
    },
    "pullback-M15": {
        "entry": ["Giá và EMA 50 cùng phía EMA 200 (xu hướng dài)", "Khung H1 cùng chiều", "RSI(2) nến trước ≤ 20 để mua, ≥ 80 để bán",
                  "Nến bật lại đủ mạnh (≥ 1 ATR) vượt đỉnh/thủng đáy nến trước"],
        "exit": ["Chốt lời 1,5R", "Đóng sau tối đa 24 nến M15 nếu chưa chạm", "Cắt lỗ cố định"],
    },
    "trend-M30": {
        "entry": ["Cùng luật theo xu hướng như Raschke nhưng trên nến M30", "Khung H4 cùng chiều", "Giá hồi về EMA 20 rồi nến xác nhận"],
        "exit": ["Chốt lời 2R", "Đóng sau tối đa 48 nến M30", "Cắt lỗ cố định"],
    },
}
FRAME_SECONDS = {"M15": 900, "M30": 1800}

# Weight = long-run mean R shrunk toward a common prior, so a few trades barely move it
# ("theo phong độ" — following the last few trades — lost to the fixed selector every year).
PRIOR_R = 0.10
PRIOR_TRADES = 100
WEIGHT_MIN = 0.15
WEIGHT_MAX = 0.50
# An agent losing this share of its money goes to paper; it trades real again once its
# drawdown (real and paper results together) is back under the resume share.
PAUSE_SHARE = 0.40
RESUME_SHARE = 0.20
# Pausing an agent after a 40% loss of its share and promoting paper agents both lost money in
# the 2022-2026 tests (the pause benched trend M15 before +27.7R; reversal was promoted by luck and
# lost 26R), so the live configuration (variant E) keeps them off.
ALLOW_PAUSE = False
ALLOW_PROMOTION = False
# A paper agent earns real money after this record.
PROMOTE_TRADES = 40
# Coordinator policy for a new entry while another real agent holds a position in the same
# direction: "allow" (full size), "half" (half size) or "skip".
SAME_SIDE = "allow"
# New entry against a real position of another agent: "allow", or "losing" = only while every
# opposite position is losing (a winning position is never fought).
OPPOSITE = "losing"
# When an opposite entry is accepted against a losing position, move that position's stop half
# way toward the price (its remaining risk halves; it is not closed).
TIGHTEN_ON_OPPOSITE = False
# Equal fixed shares instead of shares earned from long-run results.
FIXED_WEIGHTS = True
# Multiplier on every agent's risk (1.0 = the user's per-trade %).
RISK_SCALE = 1.0
PROMOTE_PROFIT_FACTOR = 1.15


def agent(agent_id: str) -> dict[str, object]:
    return next(item for item in AGENTS if item["id"] == agent_id)


def method_agents() -> tuple[dict[str, object], ...]:
    """Agents of the research methods (services/api/methods): paper only, never in the backtest crew."""
    from services.api.methods import METHODS

    return tuple(method.describe() for method in METHODS)


def lab_agents() -> tuple[dict[str, object], ...]:
    """Every agent without real money: the old paper agents, then the research methods."""
    return tuple(item for item in AGENTS if not item["core"]) + method_agents()


def _known(agent_id: str) -> dict[str, object] | None:
    return next((item for item in AGENTS + LIVE_ONLY + method_agents() if item["id"] == agent_id), None)


def profile(agent_id: str) -> dict[str, str]:
    if agent_id in PROFILE:
        return PROFILE[agent_id]
    from services.api.methods import BY_AGENT

    method = BY_AGENT.get(agent_id)
    if method is None:
        return {}
    exits = "; ".join(method.exit_rules)
    return {"why": method.why, "rule": f"Khung {method.timeframe}. {method.source} {exits}."}


def method_rules(agent_id: str) -> dict[str, list[str]] | None:
    if agent_id in METHOD:
        return METHOD[agent_id]
    from services.api.methods import BY_AGENT

    method = BY_AGENT.get(agent_id)
    if method is None:  # same method on another frame (for example flag-H1)
        from services.api.methods import BY_ID

        known = _known(agent_id) or {}
        method = BY_ID.get(str(known.get("strategy") or ""))
    return None if method is None else {"entry": list(method.entry_rules), "exit": list(method.exit_rules)}


def alias(agent_id: str) -> str:
    """Trader name of an agent id ("" when unknown)."""
    found = _known(agent_id)
    return "" if found is None else str(found["alias"])


def label(agent_id: str) -> str:
    """"Linda Raschke (Theo xu hướng M15)"."""
    found = _known(agent_id)
    return agent_id if found is None else f"{found['alias']} ({found['name']})"


def new_ledger() -> dict[str, object]:
    return {"rs": [], "cum": 0.0, "peak": 0.0, "paused": False, "promoted": False}


def eligible(config: dict[str, object], ledger: dict[str, object]) -> bool:
    return bool(config["core"]) or bool(ledger.get("promoted"))


def is_real(config: dict[str, object], ledger: dict[str, object]) -> bool:
    return eligible(config, ledger) and not ledger.get("paused")


def pause_r(per_trade: float, agents_real: int) -> float:
    """Drawdown in R that equals PAUSE_SHARE of an agent's money: an average agent risks
    per_trade x N of total equity per trade and owns 1/N of it."""
    return PAUSE_SHARE / max(per_trade * max(agents_real, 1), 1e-9)


def record(config: dict[str, object], ledger: dict[str, object], r: float, per_trade: float, agents_real: int) -> str | None:
    """Add one closed trade (real or paper) to the agent's ledger. Returns a note when the
    coordinator changes the agent's status."""
    ledger["rs"].append(round(float(r), 3))
    ledger["cum"] = float(ledger["cum"]) + float(r)
    ledger["peak"] = max(float(ledger["peak"]), float(ledger["cum"]))
    drawdown = float(ledger["peak"]) - float(ledger["cum"])
    limit = pause_r(per_trade, agents_real)
    note = None
    if ALLOW_PAUSE and eligible(config, ledger) and not ledger["paused"] and drawdown >= limit:
        ledger["paused"] = True
        note = f"{config['name']} mất {drawdown:.1f}R (≥ {PAUSE_SHARE:.0%} phần vốn), chuyển sang lệnh giấy."
    elif ledger["paused"] and drawdown <= limit * RESUME_SHARE / PAUSE_SHARE:
        ledger["paused"] = False
        note = f"{config['name']} hồi lại trên lệnh giấy, được giao tiền thật trở lại."
    if ALLOW_PROMOTION and not config["core"] and not ledger.get("promoted") and promotable(ledger):
        ledger["promoted"] = True
        ledger["peak"] = ledger["cum"]
        note = f"{config['name']} đạt chuẩn trên lệnh giấy ({len(ledger['rs'])} lệnh), được giao tiền thật."
    return note


def promotable(ledger: dict[str, object]) -> bool:
    rs = [float(value) for value in ledger["rs"]]
    if len(rs) < PROMOTE_TRADES:
        return False
    gains = sum(value for value in rs if value > 0)
    losses = -sum(value for value in rs if value < 0)
    return sum(rs) > 0 and (losses == 0 or gains / losses >= PROMOTE_PROFIT_FACTOR)


def shrunk_r(ledger: dict[str, object]) -> float:
    rs = ledger["rs"]
    return (PRIOR_R * PRIOR_TRADES + sum(float(value) for value in rs)) / (PRIOR_TRADES + len(rs))


def weights(ledgers: dict[str, dict[str, object]]) -> dict[str, float]:
    """Capital share of every real agent: proportional to its shrunk mean R (floored at a
    small positive value), clamped to [WEIGHT_MIN, WEIGHT_MAX], summing to 1."""
    real = [config for config in AGENTS if is_real(config, ledgers[str(config["id"])])]
    if not real:
        return {}
    if FIXED_WEIGHTS:
        return {str(config["id"]): round(1 / len(real), 4) for config in real}
    raw = {str(config["id"]): max(shrunk_r(ledgers[str(config["id"])]), 0.01) for config in real}
    low = WEIGHT_MIN if WEIGHT_MIN * len(raw) <= 1 else 1 / len(raw)
    high = WEIGHT_MAX if WEIGHT_MAX * len(raw) >= 1 else 1 / len(raw)
    fixed: dict[str, float] = {}
    for _ in range(len(raw) + 1):
        free = {name: value for name, value in raw.items() if name not in fixed}
        if not free:
            break
        room = 1 - sum(fixed.values())
        total = sum(free.values())
        trial = {name: room * value / total for name, value in free.items()}
        clipped = {name: (low if share < low else high) for name, share in trial.items() if share < low or share > high}
        if not clipped:
            fixed.update(trial)
            break
        fixed.update(clipped)
    return {name: round(share, 4) for name, share in fixed.items()}


def size_factor(share: float, agents_real: int) -> float:
    """Multiplier on the per-trade risk: 1.0 for an agent with an equal share."""
    return share * max(agents_real, 1) * RISK_SCALE
