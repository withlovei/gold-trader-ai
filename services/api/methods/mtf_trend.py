"""Multi-Timeframe Trend: H4/H1 xác định hướng, M15 tìm điểm vào (kiểu "Triple Screen")."""
from services.api.methods.base import Gates, Method, Plan, frame_bias, series, side_word


class MultiTimeframeTrend(Method):
    id = "mtf"
    name = "Xu hướng đa khung"
    alias = "Alexander Elder"
    family = "trend"
    magic = 260618
    status = "paper"
    why = "Alexander Elder tạo ra hệ \"Triple Screen\": khung lớn chọn hướng, khung giữa chờ nhịp ngược, khung nhỏ tìm điểm vào."
    source = "Multi-Timeframe Trend: dùng H1/H4 xác định hướng, M5/M15 tìm điểm vào."
    gates = (
        "Khung H4 có xu hướng (EMA 9/21)",
        "Khung H1 cùng chiều H4",
        "M15 hồi ngược: RSI 14 ≤ 40 (mua) / ≥ 60 (bán) trong 6 nến",
        "Nến M15 quay lại theo hướng chính",
    )
    entry_rules = (
        "H4 (ghép từ nến M15): EMA 9 trên EMA 21 và giá trên EMA 9 (mua)",
        "H1 cùng chiều H4",
        "Trong 6 nến M15 trước, RSI 14 xuống ≤ 40 (nhịp hồi ngược hướng chính)",
        "Nến tín hiệu đóng tăng, vượt đỉnh nến trước",
    )
    exit_rules = ("Cắt lỗ dưới đáy 6 nến gần nhất 0,2 ATR", "Chốt lời 2R", "Đóng sau tối đa 48 nến")
    manage = "fixed"
    reward = 2.0
    max_bars = 48

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        h4 = frame_bias(m, 14400)
        g.need(self.gates[0], h4 in {"up", "down"}, f"H4 đang {h4}")
        buy = h4 == "up"
        side = "buy" if buy else "sell"
        g.need(self.gates[1], m["higherBias"] == h4, f"H1 đang {m['higherBias']}")
        rsi = [value for value in series(m, "rsi", 14)[-7:-1] if value is not None]
        g.need(self.gates[2], rsi and (min(rsi) <= 40 if buy else max(rsi) >= 60), "chưa có nhịp hồi ngược trên M15")
        bars, atr = m["bars"], float(m["atr"])
        last, prev = bars[-1], bars[-2]
        confirmed = (last[3] > prev[1] and last[3] > last[0]) if buy else (last[3] < prev[2] and last[3] < last[0])
        g.need(self.gates[3], confirmed, "nến vừa đóng chưa quay lại theo hướng chính")
        recent = bars[-6:]
        stop = (min(bar[2] for bar in recent) - 0.2 * atr) if buy else (max(bar[1] for bar in recent) + 0.2 * atr)
        return Plan(side, float(last[3]), stop, None, f"H4 và H1 cùng chiều {side_word(side)}, M15 vừa hồi xong và quay lại.")


METHOD = MultiTimeframeTrend()
