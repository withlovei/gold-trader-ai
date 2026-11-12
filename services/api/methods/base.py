"""Khung chung cho một phương pháp giao dịch = một agent.

Một phương pháp chỉ cần khai báo thông tin (tên, trader, điều kiện, cách thoát) và viết hàm
scan(m, g). Mọi thứ còn lại (thẻ chiến lược, danh sách điều kiện trên giao diện, bộ lọc chênh lệch
và giờ, kiểm thử, lệnh giấy, agent ở phòng nghiên cứu) do khung này lo.

Vòng đời (status):
  "draft"  chưa viết luật: agent hiện ở phòng nghiên cứu với nhãn "Chưa triển khai".
  "paper"  đã có luật: chấm trên mỗi nến M15 đóng, ghi lệnh giấy, chạy được trên trang Kiểm thử.
  Lên tiền thật KHÔNG làm ở đây: cần kiểm thử tách đôi (chọn 2022–24, kiểm 2025–26) đạt, rồi
  thêm vào live.EXTRA_BOOKS + strategies.LIVE_STRATEGIES, và bạn đồng ý.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from services.api import strategies as S

_LOG = logging.getLogger("goldtrader.methods")
HOUR_GATE = S.HOUR_GATE


class GateFail(Exception):
    """Raised by Gates.need when a condition fails; scan() stops there."""

    def __init__(self, gate: str, text: str) -> None:
        super().__init__(text)
        self.gate = gate
        self.text = text


class Gates:
    """Records the state of each declared condition in order: ok / fail / wait (not reached) / skip."""

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = list(names)
        self.states: dict[str, str] = {}

    def need(self, name: str, condition: object, why: str = "") -> bool:
        if name not in self.names:
            raise KeyError(f"điều kiện '{name}' chưa khai báo trong gates")
        if condition:
            self.states[name] = "ok"
            return True
        self.states[name] = "fail"
        raise GateFail(name, why or name)

    def skip(self, name: str) -> None:
        self.states[name] = "skip"

    def listing(self) -> list[dict[str, str]]:
        return [{"name": name, "state": self.states.get(name, "wait")} for name in self.names]


@dataclass
class Plan:
    """A confirmed signal. take=None for methods managed with a trailing stop."""

    side: str  # "buy" | "sell"
    entry: float
    stop: float
    take: float | None
    summary: str
    explanation: str = ""
    max_bars: int | None = None  # holding limit of this trade (default: the method's max_bars)


class Method:
    # --- danh tính
    id = ""  # khóa chiến lược, ví dụ "reentry" (dùng trong kiểm thử và lệnh giấy)
    name = ""  # tên tiếng Việt, ví dụ "Vào lại theo xu hướng"
    alias = ""  # trader nổi tiếng gắn với phương pháp
    family = ""  # "trend" | "breakout" | "reversal"
    timeframe = "M15"
    magic = 0  # mã sổ MT5 riêng, chỉ dùng khi lên tiền thật
    status = "draft"  # "draft" | "paper"
    # --- mô tả (hiện trên giao diện và đưa cho Claude)
    why = ""  # vì sao gắn tên trader này
    source = ""  # mô tả phương pháp theo lời người dùng
    gates: tuple[str, ...] = ()  # điều kiện vào, theo thứ tự scan() kiểm tra
    entry_rules: tuple[str, ...] = ()
    exit_rules: tuple[str, ...] = ()
    # --- quản lý lệnh (kiểm thử và lệnh giấy dùng đúng các số này)
    manage = "fixed"  # "fixed": chốt lời reward R + đóng sau max_bars; "trail": cắt lỗ bám 3 ATR sau 1R
    reward = 2.0
    max_bars = 48
    min_stop_atr = 0.5
    max_stop_atr = 3.0

    @property
    def agent_id(self) -> str:
        return f"{self.id}-{self.timeframe}"

    @property
    def label(self) -> str:
        return f"{self.name} {self.timeframe}"

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        """Kiểm tra lần lượt từng điều kiện bằng g.need(tên, điều_kiện, lý_do).
        Trả Plan khi đủ điều kiện. m là thị trường trên nến vừa đóng (xem _template.py)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ framework
    def evaluate(self, market: dict[str, object]) -> dict[str, object]:
        gates = Gates(self.gates)
        rules = self._rules(market)
        name = self.label
        if self.status == "draft":
            card = S._card(self.id, name, "rest", "wait", False, "Chưa triển khai: đã có agent và danh sách điều kiện, chưa viết luật.",
                           self.source or "Phương pháp mới, đang chờ viết luật.", None, rules)
            return self._finish_card(card, gates, None)
        try:
            plan = self.scan(market, gates)
        except GateFail as failed:
            card = S._card(self.id, name, "rest", "wait", False, f"Chưa đạt: {failed.text}", f"Dừng ở điều kiện \"{failed.gate}\": {failed.text}", None, rules)
            return self._finish_card(card, gates, None)
        except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError) as error:
            _LOG.warning("method %s: %s", self.id, error)
            card = S._card(self.id, name, "rest", "wait", False, f"Lỗi trong code phương pháp: {error}", "Sửa hàm scan() của phương pháp này.", None, rules)
            return self._finish_card(card, gates, None)
        if plan is None:
            card = S._card(self.id, name, "rest", "wait", False, "Chưa có tín hiệu.", "Các điều kiện chưa tạo thành tín hiệu.", None, rules)
            return self._finish_card(card, gates, None)
        risk = abs(plan.entry - plan.stop)
        atr = float(market["atr"])
        if not (self.min_stop_atr * atr <= risk <= self.max_stop_atr * atr):
            text = f"Cắt lỗ {risk:.2f} nằm ngoài {self.min_stop_atr:g}–{self.max_stop_atr:g} ATR ({atr:.2f})."
            card = S._card(self.id, name, "rest", plan.side, False, text, text, None, rules)
            return self._finish_card(card, gates, None)
        take = None
        if self.manage == "fixed":
            take = plan.take if plan.take is not None else (plan.entry + self.reward * risk if plan.side == "buy" else plan.entry - self.reward * risk)
        prices = (round(plan.entry, 2), round(plan.stop, 2), None if take is None else round(take, 2))
        hold = int(plan.max_bars or self.max_bars)
        card = S._finish(self.id, name, plan.side, True, plan.summary, plan.explanation or plan.summary, prices, rules, market,
                         hold, "trail" if self.manage == "trail" else "fixed")
        card = self._finish_card(card, gates, card["status"])
        card["maxBars"] = hold
        return card

    def _finish_card(self, card: dict[str, object], gates: Gates, status: str | None) -> dict[str, object]:
        listing = gates.listing()
        if status is None:
            listing.append({"name": HOUR_GATE, "state": "wait"})
        else:
            listing.append({"name": HOUR_GATE, "state": "fail" if status == "blocked" else "ok"})
        card["gates"] = listing
        card["live"] = False  # a method never sends real orders from here
        card["method"] = self.id
        card["methodStatus"] = self.status
        card["maxBars"] = self.max_bars
        card["manage"] = "trail" if self.manage == "trail" else "fixed"
        return card

    def _rules(self, market: dict[str, object]) -> list[dict[str, str]]:
        exits = "; ".join(self.exit_rules) or ("Cắt lỗ bám 3 ATR sau khi lời 1R." if self.manage == "trail" else f"Chốt lời {self.reward:g}R, tối đa {self.max_bars} nến.")
        return [
            {"label": "Vào lệnh", "value": "; ".join(self.entry_rules) or "Chưa viết."},
            {"label": "Thoát lệnh", "value": exits},
            {"label": "Khung thời gian", "value": f"Tín hiệu trên {market['timeframe']}."},
            {"label": "Lệnh thật", "value": "Chỉ lệnh giấy (phòng nghiên cứu)."},
        ]

    def describe(self) -> dict[str, object]:
        return {
            "id": self.agent_id, "strategy": self.id, "timeframe": self.timeframe, "magic": self.magic, "name": self.label,
            "alias": self.alias, "core": False, "family": self.family, "status": self.status,
        }


# ---------------------------------------------------------------------- helpers for scan()
def closes(m: dict[str, object]) -> list[float]:
    return [bar[3] for bar in m["bars"]]


def series(m: dict[str, object], kind: str, period: int) -> list[float | None]:
    """EMA / RSI / ATR series on the method's bars, computed once per bar and shared."""
    cache = m.setdefault("_series", {})
    key = (kind, period)
    if key not in cache:
        if kind == "ema":
            cache[key] = S._ema(closes(m), period)
        elif kind == "rsi":
            cache[key] = S._rsi(closes(m), period)
        elif kind == "atr":
            cache[key] = S._atr(m["bars"], period)
        else:
            raise KeyError(kind)
    return cache[key]


def box(m: dict[str, object], length: int, end: int = 1) -> tuple[float, float]:
    """(high, low) of `length` bars ending `end` bars before the last closed bar (end=1: the bars
    just before the signal bar)."""
    bars = m["bars"]
    chunk = bars[-(length + end): len(bars) - end]
    return max(bar[1] for bar in chunk), min(bar[2] for bar in chunk)


def trend_side(m: dict[str, object]) -> str | None:
    """"buy" when EMA20 > EMA50 and price above EMA200, "sell" the mirror, else None."""
    ema20, ema50, ema200 = m["ema20"], m["ema50"], m["ema200"]
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    price = float(m["price"])
    if float(ema20) > float(ema50) and price > float(ema200):
        return "buy"
    if float(ema20) < float(ema50) and price < float(ema200):
        return "sell"
    return None


def frame_bias(m: dict[str, object], seconds: int, fast: int = 9, slow: int = 21) -> str:
    """Direction of a larger frame built on clock boundaries from the method's bars: "up" when
    EMA fast > EMA slow and price above EMA fast, "down" the mirror, else "flat"/"unknown"."""
    times = m.get("times")
    if not times or len(times) != len(m["bars"]):
        return "unknown"
    big = S._aggregate_clock(m["bars"], times, seconds)
    if len(big) < slow + 2:
        return "unknown"
    values = [bar[3] for bar in big]
    quick, steady = S._last(S._ema(values, fast)), S._last(S._ema(values, slow))
    if quick is None or steady is None:
        return "unknown"
    if quick > steady and values[-1] > quick:
        return "up"
    if quick < steady and values[-1] < quick:
        return "down"
    return "flat"


def swings(m: dict[str, object], k: float) -> list[tuple[int, float, int]]:
    """Causal ATR zigzag on the method's bars: [(index, price, +1 high / -1 low), ...] ending with a
    low. A high counts only once price has fallen k x ATR(14) from it (and the mirror for lows), so
    nothing is seen before it happened; when the last confirmed pivot is a high, the final low is
    the lowest low since it (up to the signal bar)."""
    cache = m.setdefault("_series", {})
    key = ("swings", k)
    if key in cache:
        return cache[key]
    bars = m["bars"]
    atr = series(m, "atr", 14)
    piv: list[tuple[int, float, int]] = []
    direction = 0
    hi = lo = ext = 0.0
    hii = loi = exti = 0
    started = False
    for i, bar in enumerate(bars):
        a = atr[i]
        if a is None:
            continue
        high, low = bar[1], bar[2]
        if direction == 0:
            if not started:
                hi, hii, lo, loi, started = high, i, low, i, True
                continue
            if high > hi:
                hi, hii = high, i
            if low < lo:
                lo, loi = low, i
            if hi - low >= k * a and hii < i:
                piv.append((hii, hi, 1)); direction, ext, exti = -1, low, i
            elif high - lo >= k * a and loi < i:
                piv.append((loi, lo, -1)); direction, ext, exti = 1, high, i
            continue
        if direction == 1:
            if high > ext:
                ext, exti = high, i
            elif ext - low >= k * a:
                piv.append((exti, ext, 1)); direction, ext, exti = -1, low, i
        else:
            if low < ext:
                ext, exti = low, i
            elif high - ext >= k * a:
                piv.append((exti, ext, -1)); direction, ext, exti = 1, high, i
    if piv and piv[-1][2] == 1 and piv[-1][0] + 1 < len(bars):
        start = piv[-1][0] + 1
        j = min(range(start, len(bars)), key=lambda index: bars[index][2])
        piv.append((j, bars[j][2], -1))
    cache[key] = piv
    return piv


def close_position(bar: tuple[float, float, float, float]) -> float:
    """Where the bar closed inside its own range: 0 = at the low, 1 = at the high."""
    span = max(bar[1] - bar[2], 1e-9)
    return (bar[3] - bar[2]) / span


def side_word(side: str) -> str:
    return "mua" if side == "buy" else "bán"
