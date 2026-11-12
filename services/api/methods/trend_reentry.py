"""Trend Re-entry: vào lại sau khi vị thế trước đã đóng.

Bản không trạng thái (chạy giống nhau ở live, lệnh giấy và kiểm thử): sóng đẩy trước đã tạo
đỉnh/đáy mới (lệnh theo xu hướng trước đó đã có lãi và thường đã chốt / bị cắt lỗ bám), giá hồi lại
EMA 20 mà vẫn giữ EMA 50, rồi nến xác nhận quay lại theo xu hướng: vào lại lần hai cùng sóng.

Bộ lọc thêm (11/2026): chỉ vào lại khi khung lớn còn đủ lực (ADX 14 khung lớn hoặc độ dốc EMA 21
khung lớn vượt ngưỡng; chỉ dùng nến khung lớn đã đóng), và không vào trong giờ đầu phiên London
(08:00 GMT mùa đông, 07:00 UTC mùa hè), nơi nhịp quét hai chiều hay cắt lỗ lệnh vào lại."""
from datetime import datetime, timedelta, timezone

from services.api import strategies as S
from services.api.methods.base import Gates, Method, Plan, series, side_word, trend_side

LOOK = 40
HTF_ADX_MIN = 22.0  # ADX 14 khung lớn tối thiểu
HTF_SLOPE_MIN = 0.25  # độ dốc EMA 21 khung lớn qua 3 nến, tính theo ATR 14 khung lớn
HTF_SLOPE_BARS = 3
MIN_ATR_RATIO = 0.8  # ATR hiện tại / ATR trung bình 50 nến tối thiểu
MAX_REENTRIES = 1  # số nến xác nhận tối đa trong một nhịp hồi (kể cả nến hiện tại: chỉ lần đầu)
MIN_RISK_ATR = 1.0  # khoảng stop tối thiểu (ATR)
MAX_RISK_ATR = 3.0  # khoảng stop tối đa (ATR)


def _uk_summer(moment: datetime) -> bool:
    """Giờ mùa hè Anh: từ 01:00 UTC Chủ nhật cuối tháng 3 đến 01:00 UTC Chủ nhật cuối tháng 10."""
    def last_sunday(month: int) -> datetime:
        day = datetime(moment.year, month + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        return day - timedelta(days=(day.weekday() + 1) % 7)
    return last_sunday(3) <= moment < last_sunday(10)


def _london_first_hour(m: dict[str, object]) -> bool:
    """True khi lệnh sẽ khớp (mở nến kế tiếp) trong giờ đầu tiên của phiên London."""
    times = m.get("times")
    frame = S.TF_SECONDS.get(str(m.get("timeframe")), 900)
    if times and len(times) == len(m["bars"]):
        fill = datetime.fromtimestamp(int(times[-1]) + frame, timezone.utc)
        return fill.hour == (7 if _uk_summer(fill) else 8)
    hour = m.get("hour")
    return hour is not None and int(hour) in (7, 8)  # không rõ ngày: chặn cả hai khả năng


def _higher_strength(m: dict[str, object], buy: bool) -> tuple[bool, str]:
    """Đo lực xu hướng trên khung lớn dựng từ nến đã đóng: ADX 14 hoặc độ dốc EMA 21 cùng chiều lệnh."""
    times = m.get("times")
    bars = m["bars"]
    name, factor = S.HIGHER.get(str(m.get("timeframe")), ("H1", 4))
    if not times or len(times) != len(bars) or factor <= 1:
        adx = m.get("adx")
        return adx is not None and float(adx) >= HTF_ADX_MIN, f"ADX {0 if adx is None else float(adx):.0f} (khung tín hiệu)"
    seconds = S.TF_SECONDS.get(str(m.get("timeframe")), 900) * factor
    big = S._aggregate_clock(bars, times, seconds)
    frame = S.TF_SECONDS.get(str(m.get("timeframe")), 900)
    if big and (int(times[-1]) + frame) % seconds != 0:
        big = big[:-1]  # nến khung lớn cuối chưa đóng: bỏ
    if len(big) < 60:
        return False, f"chưa đủ nến {name}"
    adx = S._adx(big, 14)
    ema = S._ema([bar[3] for bar in big], 21)
    big_atr = S._last(S._atr(big, 14)) or 0.0
    now, before = ema[-1], ema[-1 - HTF_SLOPE_BARS]
    slope = 0.0
    if now is not None and before is not None and big_atr > 0:
        slope = (now - before) / big_atr * (1 if buy else -1)
    strong = (adx is not None and adx >= HTF_ADX_MIN) or slope >= HTF_SLOPE_MIN
    return strong, f"ADX {name} {0 if adx is None else adx:.0f}, EMA 21 {name} dốc {slope:.2f} ATR/{HTF_SLOPE_BARS} nến"


class TrendReentry(Method):
    id = "reentry"
    name = "Vào lại theo xu hướng"
    alias = "Jesse Livermore"
    family = "trend"
    magic = 260617
    status = "paper"
    why = "Jesse Livermore nổi tiếng với việc quay lại thị trường đúng chiều xu hướng sau mỗi nhịp điều chỉnh, thay vì đuổi giá."
    source = "Trend Re-entry: vào lại sau khi vị thế trước đã đóng."
    gates = (
        "Xu hướng còn nguyên (EMA 20/50, giá cùng phía EMA 200)",
        "Khung lớn cùng chiều",
        "Khung lớn còn mạnh (ADX ≥ 22 hoặc EMA 21 dốc ≥ 0,25 ATR/3 nến)",
        "Ngoài giờ đầu phiên London",
        "Sóng trước đã tạo đỉnh/đáy mới (40 nến)",
        "Giá hồi về EMA 20 sau đỉnh/đáy đó",
        "Nhịp hồi giữ EMA 50",
        "Nến xác nhận vượt đỉnh/thủng đáy nến trước",
        "Biến động đủ (ATR ≥ 80% trung bình 50 nến)",
        "Chưa vào lại trong nhịp hồi này",
        "Stop không quá xa (≤ 3 ATR)",
    )
    entry_rules = (
        "EMA 20 trên EMA 50 và giá trên EMA 200 (mua; bán ngược lại)",
        "Khung H1 cùng chiều",
        "Khung lớn còn lực: ADX 14 từ 22, hoặc EMA 21 dốc cùng chiều ít nhất 0,25 ATR qua 3 nến (chỉ nến đã đóng)",
        "Không vào khi lệnh khớp trong giờ đầu phiên London (08:00 GMT mùa đông, 07:00 UTC mùa hè)",
        "Trong 40 nến gần nhất có đỉnh mới cao hơn 40 nến trước đó, cách nến tín hiệu ít nhất 3 nến",
        "Sau đỉnh đó giá hồi chạm EMA 20 (± 0,2 ATR) mà không đóng dưới EMA 50",
        "Nến tín hiệu đóng tăng, vượt đỉnh nến trước",
        "ATR hiện tại ≥ 80% ATR trung bình 50 nến",
        "Trong nhịp hồi chưa có nến xác nhận nào trước đó (mỗi nhịp chỉ vào lại một lần)",
        "Khoảng stop từ 1 đến 3 ATR",
    )
    exit_rules = ("Cắt lỗ dưới đáy nhịp hồi 0,3 ATR (tối thiểu 1 ATR, tối đa 3 ATR)", "Lời 1R thì bật cắt lỗ bám 3 ATR", "Không chốt lời cố định")
    manage = "trail"
    max_bars = 400

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        side = trend_side(m)
        g.need(self.gates[0], side, "EMA chưa xếp theo một chiều rõ ràng")
        buy = side == "buy"
        g.need(self.gates[1], m["higherBias"] == ("up" if buy else "down"), f"khung lớn đang {m['higherBias']}")
        strong, detail = _higher_strength(m, buy)
        g.need(self.gates[2], strong, f"xu hướng khung lớn yếu: {detail}")
        g.need(self.gates[3], not _london_first_hour(m), "lệnh sẽ khớp trong giờ đầu phiên London")
        bars, atr = m["bars"], float(m["atr"])
        ema20, ema50 = series(m, "ema", 20), series(m, "ema", 50)
        n = len(bars)
        start = n - 1 - LOOK
        g.need(self.gates[4], start - LOOK >= 0, "chưa đủ nến")
        window = bars[start: n - 1]
        prior = bars[start - LOOK: start]
        if buy:
            index = max(range(len(window)), key=lambda i: window[i][1])
            fresh = window[index][1] > max(bar[1] for bar in prior)
        else:
            index = min(range(len(window)), key=lambda i: window[i][2])
            fresh = window[index][2] < min(bar[2] for bar in prior)
        extreme = start + index
        g.need(self.gates[4], fresh and n - 1 - extreme >= 3, "sóng trước chưa tạo đỉnh/đáy mới, hoặc đỉnh/đáy vừa mới hình thành")
        since = range(extreme + 1, n - 1)
        if buy:
            touched = any(bars[i][2] <= (ema20[i] or 0) + 0.2 * atr for i in since)
            held = all(bars[i][3] > (ema50[i] or 0) for i in since)
        else:
            touched = any(bars[i][1] >= (ema20[i] or 0) - 0.2 * atr for i in since)
            held = all(bars[i][3] < (ema50[i] or 1e12) for i in since)
        g.need(self.gates[5], touched, "giá chưa hồi về EMA 20 sau đỉnh/đáy")
        g.need(self.gates[6], held, "nhịp hồi đã đóng qua EMA 50, sóng có thể đã gãy")
        last, prev = bars[-1], bars[-2]
        confirmed = (last[3] > prev[1] and last[3] > last[0]) if buy else (last[3] < prev[2] and last[3] < last[0])
        g.need(self.gates[7], confirmed, "nến vừa đóng chưa xác nhận quay lại xu hướng")
        # Biến động đủ: ATR hiện tại không thấp hơn 80% ATR trung bình 50 nến
        atr_series = [v for v in series(m, "atr", 14)[-50:] if v]
        g.need(self.gates[8], not atr_series or atr >= MIN_ATR_RATIO * (sum(atr_series) / len(atr_series)),
               "biến động quá thấp so với trung bình 50 nến")
        # Tối đa 1 lần vào lại mỗi nhịp hồi: nếu sau lần chạm EMA 20 đầu tiên đã có nến xác nhận khác thì bỏ
        first_touch = next((i for i in since if (bars[i][2] <= (ema20[i] or 0) + 0.2 * atr if buy
                                                  else bars[i][1] >= (ema20[i] or 0) - 0.2 * atr)), None)
        repeats = 0
        if first_touch is not None:
            for i in range(first_touch + 1, n - 1):
                c, p = bars[i], bars[i - 1]
                if (c[3] > p[1] and c[3] > c[0]) if buy else (c[3] < p[2] and c[3] < c[0]):
                    repeats += 1
        g.need(self.gates[9], repeats < MAX_REENTRIES, "đã có nến xác nhận vào lại trong nhịp hồi này (tránh vào lại liên tiếp)")
        lows = [bars[i] for i in since] + [last]
        stop = (min(bar[2] for bar in lows) - 0.3 * atr) if buy else (max(bar[1] for bar in lows) + 0.3 * atr)
        risk = abs(float(last[3]) - stop)
        # Stop theo ATR: không quá sát (nhiễu quét) và không quá xa (R xấu)
        if risk < MIN_RISK_ATR * atr:
            stop = float(last[3]) - MIN_RISK_ATR * atr if buy else float(last[3]) + MIN_RISK_ATR * atr
        g.need(self.gates[10], risk <= MAX_RISK_ATR * atr, f"stop quá xa ({risk / atr:.1f} ATR)")
        return Plan(side, float(last[3]), stop, None,
                    f"Vào lại {side_word(side)} lần hai trong cùng sóng: khung lớn còn lực ({detail}), hồi về EMA 20, giữ EMA 50, nến xác nhận.")


METHOD = TrendReentry()
