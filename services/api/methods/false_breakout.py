"""False Breakout: giao dịch ngược hướng khi phá vỡ thất bại."""
from services.api.methods.base import Gates, Method, Plan, box, side_word


class FalseBreakout(Method):
    id = "fakeout"
    name = "Phá vỡ thất bại"
    alias = "Larry Williams"
    family = "reversal"
    magic = 260623
    status = "paper"
    why = "Larry Williams nổi tiếng với mẫu \"Oops!\": giá vượt mức quan trọng rồi quay ngược lại, bẫy người đuổi theo cú phá."
    source = "False Breakout: giao dịch ngược hướng khi phá vỡ thất bại."
    gates = (
        "Có vùng giá 20 nến (biên ≤ 4 ATR)",
        "Giá vừa chọc ra ngoài vùng (4 nến gần nhất)",
        "Không nến nào đóng xa ngoài vùng (> 0,3 ATR)",
        "Nến vừa đóng quay lại trong vùng, ngược chiều phá",
    )
    entry_rules = (
        "Vùng 20 nến tính đến trước 4 nến gần nhất, biên độ không quá 4 ATR",
        "Trong 4 nến gần nhất giá chọc qua một cạnh (chỉ một cạnh)",
        "Không nến nào đóng ngoài cạnh đó quá 0,3 ATR",
        "Nến tín hiệu đóng trở lại trong vùng, thân ngược chiều cú phá",
    )
    exit_rules = ("Cắt lỗ qua điểm chọc xa nhất 0,2 ATR", "Chốt lời 1,5R", "Đóng sau tối đa 24 nến")
    manage = "fixed"
    reward = 1.5
    max_bars = 24

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        atr = float(m["atr"])
        high, low = box(m, 20, end=4)
        g.need(self.gates[0], high - low <= 4 * atr, f"biên 20 nến {high - low:.2f} rộng hơn 4 ATR")
        recent = m["bars"][-4:]
        poked_up, poked_down = any(bar[1] > high for bar in recent), any(bar[2] < low for bar in recent)
        g.need(self.gates[1], poked_up != poked_down, "giá chưa chọc ra ngoài vùng (hoặc chọc cả hai phía)")
        side = "sell" if poked_up else "buy"
        far = any(bar[3] > high + 0.3 * atr for bar in recent[:-1]) if poked_up else any(bar[3] < low - 0.3 * atr for bar in recent[:-1])
        g.need(self.gates[2], not far, "đã có nến đóng xa ngoài vùng: cú phá có thể là thật")
        last = recent[-1]
        back = (last[3] < high and last[3] < last[0]) if side == "sell" else (last[3] > low and last[3] > last[0])
        g.need(self.gates[3], back, "nến vừa đóng chưa quay lại trong vùng")
        stop = (max(bar[1] for bar in recent) + 0.2 * atr) if side == "sell" else (min(bar[2] for bar in recent) - 0.2 * atr)
        return Plan(side, float(last[3]), stop, None, f"Cú phá {'lên' if poked_up else 'xuống'} thất bại, quay lại trong vùng: vào {side_word(side)} ngược cú phá.")


METHOD = FalseBreakout()
