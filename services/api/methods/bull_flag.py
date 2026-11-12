"""Cờ tăng (bull flag): nhịp tăng mạnh, nghỉ nông, rồi nến đóng phá đỉnh cờ, trong xu hướng dài tăng.

Nhận diện bằng đỉnh/đáy ZigZag theo ATR (base.swings), không nhìn trước: một đỉnh chỉ được tính
khi giá đã rơi k x ATR khỏi nó; đáy cuối cùng là đáy thấp nhất kể từ đỉnh đó.
Kiểm thử 10/11/2026 (scratchpad chart_patterns.py, chọn 2022–24, kiểm 2025–26):
  M30 k=2.5 có lọc xu hướng: +0,43R (PF 2,05, 38 lệnh) → +0,36R (PF 1,79, 40 lệnh), dương cả 5 năm.
  H1  k=1.5 có lọc xu hướng: +0,33R (PF 1,76, 37 lệnh) → +0,17R (PF 1,35, 52 lệnh).
  Cờ giảm (bán) và cờ trên M15 không có lợi thế, nên chỉ có chiều mua."""
from services.api.methods.base import Gates, Method, Plan, swings

# Độ nhạy ZigZag theo khung (chọn trên 2022–24).
K_BY_FRAME = {"M30": 2.5, "H1": 1.5}
IMPULSE_ATR = 4.0
IMPULSE_BARS = 40
MAX_RETRACE = 0.5
PAUSE_MIN, PAUSE_MAX = 3, 30


class BullFlag(Method):
    id = "flag"
    name = "Cờ tăng"
    alias = "Dan Zanger"
    family = "trend"
    timeframe = "M30"
    magic = 260625
    status = "paper"
    why = "Dan Zanger nổi tiếng giao dịch mô hình giá, đặc biệt cờ tăng: mua khi giá phá đỉnh cờ sau một nhịp tăng mạnh."
    source = "Mô hình giá cờ tăng (bull flag), nhận diện bằng ZigZag theo ATR."
    gates = (
        "Xu hướng dài tăng (giá và EMA 50 trên EMA 200)",
        f"Có đỉnh/đáy ZigZag (độ nhạy theo khung)",
        f"Nhịp tăng ≥ {IMPULSE_ATR:g} ATR trong ≤ {IMPULSE_BARS} nến",
        f"Nhịp nghỉ nông (≤ {MAX_RETRACE:.0%} nhịp tăng)",
        f"Nhịp nghỉ {PAUSE_MIN}–{PAUSE_MAX} nến",
        "Nến đóng phá đỉnh cờ",
    )
    entry_rules = (
        "Giá trên EMA 200 và EMA 50 trên EMA 200",
        "ZigZag theo ATR: M30 độ nhạy 2,5 ATR, H1 1,5 ATR",
        f"Nhịp tăng từ đáy ZigZag lên đỉnh ≥ {IMPULSE_ATR:g} ATR, dài ≤ {IMPULSE_BARS} nến",
        f"Sau đỉnh, giá nghỉ không sâu quá {MAX_RETRACE:.0%} nhịp tăng, trong {PAUSE_MIN}–{PAUSE_MAX} nến",
        "Nến tín hiệu đóng trên đỉnh cờ, nến trước còn dưới",
    )
    exit_rules = (
        "Cắt lỗ dưới đáy cờ 0,2 ATR (0,5–4 ATR)",
        "Chốt lời bằng chiều dài nhịp tăng cộng từ đỉnh cờ, trong khoảng 1–4R",
        "Đóng sau 2 lần độ dài mô hình (24–200 nến)",
    )
    manage = "fixed"
    max_bars = 48
    max_stop_atr = 4.0

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        bars = m["bars"]
        price, ema50, ema200 = float(m["price"]), m["ema50"], m["ema200"]
        g.need(self.gates[0], ema50 is not None and ema200 is not None and price > float(ema200) and float(ema50) > float(ema200),
               "giá hoặc EMA 50 chưa nằm trên EMA 200")
        k = K_BY_FRAME.get(str(m["timeframe"]), 2.5)
        seq = swings(m, k)
        g.need(self.gates[1], len(seq) >= 3, "chưa đủ đỉnh/đáy ZigZag trong cửa sổ nến")
        i = len(bars) - 1
        atr = float(m["atr"])
        low0, top, flag_low = seq[-3], seq[-2], seq[-1]
        impulse = top[1] - low0[1]
        g.need(self.gates[2], impulse >= IMPULSE_ATR * atr and top[0] - low0[0] <= IMPULSE_BARS,
               f"nhịp tăng gần nhất {impulse:.2f} ({impulse / atr:.1f} ATR) trong {top[0] - low0[0]} nến")
        g.need(self.gates[3], top[1] - flag_low[1] <= MAX_RETRACE * impulse,
               f"nhịp nghỉ sâu {(top[1] - flag_low[1]) / impulse:.0%} nhịp tăng")
        pause = i - top[0]
        g.need(self.gates[4], PAUSE_MIN <= pause <= PAUSE_MAX, f"nhịp nghỉ đã {pause} nến")
        g.need(self.gates[5], bars[i][3] > top[1] >= bars[i - 1][3], f"chưa có nến đóng phá đỉnh cờ {top[1]:.2f}")
        entry = float(bars[i][3])
        stop = flag_low[1] - 0.2 * atr
        risk = entry - stop
        reward = min(max(top[1] + impulse - entry, risk), 4 * risk)
        hold = int(min(max(2 * (i - low0[0]), 24), 200))
        return Plan("buy", entry, stop, entry + reward,
                    f"Cờ tăng: nhịp tăng {impulse / atr:.1f} ATR, nghỉ {pause} nến, nến đóng phá đỉnh cờ {top[1]:.2f}.",
                    f"Nhịp tăng từ {low0[1]:.2f} lên {top[1]:.2f} ({impulse / atr:.1f} ATR, {top[0] - low0[0]} nến), nghỉ {pause} nến, "
                    f"đáy cờ {flag_low[1]:.2f} ({(top[1] - flag_low[1]) / impulse:.0%} nhịp tăng). Vào {entry:.2f}, cắt lỗ {stop:.2f}, "
                    f"chốt lời {entry + reward:.2f} ({reward / risk:.1f}R), tối đa {hold} nến.",
                    max_bars=hold)


METHOD = BullFlag()
