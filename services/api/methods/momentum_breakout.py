"""Momentum Breakout: phá vùng có động lượng mạnh, để lệnh chạy bằng cắt lỗ bám."""
from services.api.methods.base import Gates, Method, Plan, box, close_position, side_word


class MomentumBreakout(Method):
    id = "momentum"
    name = "Phá vùng động lượng"
    alias = "Richard Dennis"
    family = "breakout"
    magic = 260621
    status = "paper"
    why = "Richard Dennis và nhóm Turtle mua khi giá vượt đỉnh 20 phiên và để lãi chạy theo động lượng."
    source = "Momentum Breakout: yêu cầu động lượng mạnh."
    gates = (
        "Đóng vượt đỉnh/đáy 20 nến",
        "Thân nến ≥ 0,8 ATR, đóng ở phần tư ngoài cùng",
        "ADX ≥ 20",
        "RSI 14 ≥ 60 (mua) / ≤ 40 (bán)",
    )
    entry_rules = ("Nến tín hiệu đóng trên đỉnh 20 nến trước (mua)", "Thân nến từ 0,8 ATR, đóng ở 25% trên cùng của nến", "ADX 14 từ 20", "RSI 14 từ 60")
    exit_rules = ("Cắt lỗ dưới đáy nến tín hiệu 0,2 ATR", "Lời 1R thì bật cắt lỗ bám 3 ATR", "Không chốt lời cố định")
    manage = "trail"
    max_bars = 400

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        high, low = box(m, 20)
        last = m["bars"][-1]
        atr = float(m["atr"])
        up, down = last[3] > high, last[3] < low
        g.need(self.gates[0], up or down, "giá chưa đóng ra ngoài đỉnh/đáy 20 nến")
        buy = up
        place = close_position(last)
        g.need(self.gates[1], abs(last[3] - last[0]) >= 0.8 * atr and (place >= 0.75 if buy else place <= 0.25), "nến phá yếu (thân nhỏ hoặc đóng xa đỉnh/đáy)")
        g.need(self.gates[2], (m["adx"] or 0) >= 20, f"ADX {float(m['adx'] or 0):.0f} dưới 20")
        rsi = float(m["rsi"] or 50)
        g.need(self.gates[3], rsi >= 60 if buy else rsi <= 40, f"RSI {rsi:.0f} chưa đủ mạnh")
        side = "buy" if buy else "sell"
        stop = (last[2] - 0.2 * atr) if buy else (last[1] + 0.2 * atr)
        return Plan(side, float(last[3]), stop, None, f"Phá {side_word(side)} khỏi đỉnh/đáy 20 nến với động lượng mạnh (ADX, RSI, thân nến).")


METHOD = MomentumBreakout()
