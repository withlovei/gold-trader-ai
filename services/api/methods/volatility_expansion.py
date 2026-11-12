"""Volatility Expansion: vào theo nến bùng nổ ngay sau giai đoạn biến động co lại."""
from services.api.methods.base import Gates, Method, Plan, close_position, side_word


class VolatilityExpansion(Method):
    id = "volexp"
    name = "Bùng nổ biến động"
    alias = "Toby Crabel"
    family = "breakout"
    magic = 260622
    status = "paper"
    why = "Toby Crabel nghiên cứu mẫu NR7 và \"volatility expansion\": sau một nến hẹp nhất, nến bùng nổ kế tiếp hay đi tiếp."
    source = "Volatility Expansion: yêu cầu biến động tăng."
    gates = (
        "Nến trước hẹp nhất 7 nến (NR7)",
        "Nến vừa đóng dài ≥ 1,5 ATR",
        "Đóng ở phần ba ngoài cùng của nến",
        "Khung lớn không ngược chiều",
    )
    entry_rules = ("Nến trước có biên độ nhỏ nhất trong 7 nến (NR7)", "Nến tín hiệu dài từ 1,5 ATR", "Đóng ở 1/3 trên cùng (mua) hoặc dưới cùng (bán)", "Khung H1 không ngược chiều")
    exit_rules = ("Cắt lỗ ở giữa nến tín hiệu", "Chốt lời 2R", "Đóng sau tối đa 32 nến")
    manage = "fixed"
    reward = 2.0
    max_bars = 32

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        bars, atr = m["bars"], float(m["atr"])
        prev = bars[-2]
        others = bars[-8:-2]
        g.need(self.gates[0], prev[1] - prev[2] <= min(bar[1] - bar[2] for bar in others), "nến trước không phải nến hẹp nhất 7 nến")
        last = bars[-1]
        g.need(self.gates[1], last[1] - last[2] >= 1.5 * atr, "nến vừa đóng chưa đủ dài")
        place = close_position(last)
        g.need(self.gates[2], place >= 2 / 3 or place <= 1 / 3, "nến đóng ở giữa thân, chưa rõ chiều")
        side = "buy" if place >= 2 / 3 else "sell"
        g.need(self.gates[3], m["higherBias"] != ("down" if side == "buy" else "up"), f"khung lớn đang {m['higherBias']}")
        return Plan(side, float(last[3]), (last[1] + last[2]) / 2, None, f"Nến bùng nổ {side_word(side)} ngay sau nến hẹp nhất 7 nến.")


METHOD = VolatilityExpansion()
