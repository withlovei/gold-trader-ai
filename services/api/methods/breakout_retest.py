"""Breakout Retest: chờ giá quay lại kiểm tra vùng vừa phá rồi mới vào."""
from services.api.methods.base import Gates, Method, Plan, side_word


class BreakoutRetest(Method):
    id = "retest"
    name = "Phá vùng rồi kiểm tra lại"
    alias = "Al Brooks"
    family = "breakout"
    magic = 260620
    status = "paper"
    why = "Al Brooks (price action) mô tả kỹ \"breakout pullback\": sau cú phá, giá thường quay lại kiểm tra cạnh vùng; vào ở đó rủi ro ngắn hơn."
    source = "Breakout Retest: chờ giá quay lại kiểm tra vùng vừa phá."
    gates = (
        "Có phá vùng 20 nến trong 2–12 nến trước",
        "Giá quay lại chạm cạnh vùng vừa phá",
        "Không đóng sâu trở lại vùng (quá 0,3 ATR)",
        "Nến xác nhận bật đi theo chiều phá",
    )
    entry_rules = (
        "Trong 2–12 nến trước có một nến đóng ra ngoài vùng 20 nến (biên ≤ 4 ATR)",
        "Sau đó giá quay lại chạm cạnh vùng (± 0,3 ATR)",
        "Không nến nào đóng sâu trở lại trong vùng quá 0,3 ATR",
        "Nến tín hiệu đóng theo chiều phá, vượt đỉnh/thủng đáy nến trước",
    )
    exit_rules = ("Cắt lỗ qua đáy/đỉnh nhịp kiểm tra 0,3 ATR", "Chốt lời 2R", "Đóng sau tối đa 48 nến")
    manage = "fixed"
    reward = 2.0
    max_bars = 48

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        bars, atr = m["bars"], float(m["atr"])
        n = len(bars)
        found = None
        for back in range(2, 13):
            at = n - 1 - back
            if at - 20 < 0:
                break
            chunk = bars[at - 20: at]
            high, low = max(bar[1] for bar in chunk), min(bar[2] for bar in chunk)
            if high - low > 4 * atr:
                continue
            if bars[at][3] > high:
                found = ("buy", high, at)
                break
            if bars[at][3] < low:
                found = ("sell", low, at)
                break
        g.need(self.gates[0], found, "chưa có cú phá vùng nào gần đây")
        side, edge, at = found
        buy = side == "buy"
        after = bars[at + 1: n]
        touched = any(bar[2] <= edge + 0.3 * atr for bar in after) if buy else any(bar[1] >= edge - 0.3 * atr for bar in after)
        g.need(self.gates[1], touched, f"giá chưa quay lại cạnh vùng {edge:.2f}")
        deep = any(bar[3] < edge - 0.3 * atr for bar in after) if buy else any(bar[3] > edge + 0.3 * atr for bar in after)
        g.need(self.gates[2], not deep, "giá đã đóng sâu trở lại vùng: cú phá thất bại")
        last, prev = bars[-1], bars[-2]
        confirmed = (last[3] > prev[1] and last[3] > last[0] and last[3] > edge) if buy else (last[3] < prev[2] and last[3] < last[0] and last[3] < edge)
        g.need(self.gates[3], confirmed, "chưa có nến bật lại theo chiều phá")
        stop = (min(bar[2] for bar in after) - 0.3 * atr) if buy else (max(bar[1] for bar in after) + 0.3 * atr)
        return Plan(side, float(last[3]), stop, None, f"Phá vùng rồi kiểm tra lại cạnh {edge:.2f}, bật {side_word(side)}.")


METHOD = BreakoutRetest()
