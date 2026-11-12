"""Breakout Confirmation: chờ nến đóng ngoài vùng, chỉ khi thị trường đang có xu hướng.

Bản gốc chỉ có điều kiện "đóng ngoài vùng" và thua trong giai đoạn đi ngang 2022-24 (nhiều phá vùng
giả). Bộ lọc chế độ thị trường loại các giai đoạn đó:
  - ATR 14 ≥ ATR 100 (biến động đang mở rộng, không phải thị trường ngủ);
  - EMA 21 của khung H4 (ghép từ nến đã đóng) dốc theo hướng phá, độ dốc 3 nến H4 ≥ 0,2 ATR H4.
Chỉ dùng nến đã đóng; nến H4 cuối có thể đang hình thành nhưng chỉ chứa các nến nhỏ đã đóng."""
from datetime import datetime, timezone

from services.api import strategies as S
from services.api.methods.base import Gates, Method, Plan, box, close_position, side_word

FRAME_SECONDS = 900
ASIA_START, ASIA_END = 0, 6
H4_SECONDS = 14400
H4_EMA = 21
H4_SLOPE_BARS = 3
H4_MIN_SLOPE_ATR = 0.2


def _h4_slope(m: dict[str, object]) -> tuple[float, float] | None:
    """(độ dốc EMA21 H4 qua 3 nến H4, ATR14 H4) hoặc None khi chưa đủ dữ liệu."""
    cache = m.setdefault("_series", {})
    key = ("brkconfirm_h4", H4_EMA, H4_SLOPE_BARS)
    if key in cache:
        return cache[key]
    result = None
    times = m.get("times")
    bars = m["bars"]
    if times and len(times) == len(bars):
        big = S._aggregate_clock(bars, times, H4_SECONDS)
        if len(big) >= H4_EMA + H4_SLOPE_BARS + 2:
            ema = S._ema([bar[3] for bar in big], H4_EMA)
            atr = S._atr(big, 14)
            now, before, size = ema[-1], ema[-1 - H4_SLOPE_BARS], atr[-1]
            if now is not None and before is not None and size:
                result = (float(now) - float(before), float(size))
    cache[key] = result
    return result


class BreakoutConfirmation(Method):
    id = "brkconfirm"
    name = "Phá vùng có xác nhận"
    alias = "William O'Neil"
    family = "breakout"
    magic = 260619
    status = "paper"
    why = "William O'Neil (CAN SLIM) chỉ mua khi giá đóng cửa vượt điểm phá (pivot) của vùng tích lũy, không mua khi giá mới chạm."
    source = "Breakout Confirmation: chờ nến đóng ngoài vùng, lọc chế độ thị trường (ATR mở rộng, EMA H4 dốc theo hướng phá)."
    gates = (
        "Có vùng giá 20 nến (biên ≤ 4 ATR)",
        "Nến đóng ngoài vùng ≥ 0,2 ATR",
        "Nến trước còn trong vùng (lần phá đầu)",
        "Biến động mở rộng (ATR 14 ≥ ATR 100)",
        "EMA 21 H4 dốc theo hướng phá (≥ 0,2 ATR H4 / 3 nến)",
        "Nến phá mạnh và không quá đà (thân ≥ 50% biên, đóng ở 30% cuối, biên ≤ 2,5 ATR)",
        "Không vào lúc phiên Á mỏng (00–06 UTC)",
    )
    entry_rules = (
        "Vùng 20 nến trước nến tín hiệu, biên độ không quá 4 ATR",
        "Nến tín hiệu đóng ngoài biên ít nhất 0,2 ATR",
        "Nến trước đó còn đóng trong vùng",
        "ATR 14 không nhỏ hơn ATR 100 (bỏ giai đoạn đi ngang, biến động thấp)",
        "EMA 21 khung H4 (ghép từ nến đã đóng) tăng (mua) / giảm (bán) ít nhất 0,2 ATR H4 trong 3 nến H4",
        "Nến phá có thân ≥ 50% biên, đóng ở 30% cuối theo hướng phá, biên nến ≤ 2,5 ATR (loại râu dài và nến đã chạy quá đà)",
        "Không vào khi lệnh khớp trong 00–06 UTC (phiên Á thanh khoản mỏng, hay phá vỡ giả)",
    )
    exit_rules = ("Cắt lỗ tại giữa vùng", "Chốt lời 2R", "Đóng sau tối đa 48 nến")
    manage = "fixed"
    reward = 2.0
    max_bars = 48

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        high, low = box(m, 20)
        atr = float(m["atr"])
        g.need(self.gates[0], high - low <= 4 * atr, f"biên 20 nến {high - low:.2f} rộng hơn 4 ATR")
        last, prev = m["bars"][-1], m["bars"][-2]
        up, down = last[3] >= high + 0.2 * atr, last[3] <= low - 0.2 * atr
        g.need(self.gates[1], up or down, "nến vừa đóng chưa ra khỏi vùng đủ xa")
        g.need(self.gates[2], low <= prev[3] <= high, "nến trước đã ở ngoài vùng, không phải lần phá đầu")
        side = "buy" if up else "sell"
        g.need(self.gates[3], bool(m.get("expanding")), "ATR 14 thấp hơn ATR 100, thị trường đang đi ngang")
        slope = _h4_slope(m)
        g.need(self.gates[4], slope is not None, "chưa đủ nến để tính EMA 21 khung H4")
        move, h4_atr = slope
        aligned = move >= H4_MIN_SLOPE_ATR * h4_atr if side == "buy" else move <= -H4_MIN_SLOPE_ATR * h4_atr
        g.need(self.gates[4], aligned, f"EMA 21 H4 dốc {move:+.2f} (cần {'≥' if side == 'buy' else '≤'} {'' if side == 'buy' else '-'}{H4_MIN_SLOPE_ATR * h4_atr:.2f}), không ủng hộ phá {side_word(side)}")
        span = float(last[1]) - float(last[2])
        pos = close_position(last)
        body_ok = span > 0 and abs(float(last[3]) - float(last[0])) >= 0.5 * span
        strong = (pos >= 0.7 if side == "buy" else pos <= 0.3) and body_ok and span <= 2.5 * atr
        g.need(self.gates[5], strong, f"nến phá yếu hoặc quá đà (biên {span / atr:.1f} ATR, vị trí đóng {pos:.2f}, thân {'đủ' if body_ok else 'nhỏ'})")
        times = m.get("times")
        if times and len(times) == len(m["bars"]):
            fill_hour = datetime.fromtimestamp(int(times[-1]) + FRAME_SECONDS, timezone.utc).hour
        else:
            fill_hour = int(m["hour"]) if m.get("hour") is not None else 12
        g.need(self.gates[6], not (ASIA_START <= fill_hour < ASIA_END), f"lệnh khớp lúc {fill_hour:02d}h UTC, phiên Á mỏng")
        return Plan(side, float(last[3]), (high + low) / 2, None,
                    f"Nến đóng ngoài vùng {low:.2f}–{high:.2f}, phá {side_word(side)} có xác nhận; ATR mở rộng và EMA H4 dốc cùng chiều.")


METHOD = BreakoutConfirmation()
