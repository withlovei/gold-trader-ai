"""TEMPLATE — sao chép file này để thêm một phương pháp (một agent) mới.

Các bước:
  1. Sao chép thành services/api/methods/<ten_file>.py, đổi tên lớp và các trường bên dưới.
  2. Khai báo `gates`: danh sách điều kiện vào, đúng thứ tự scan() kiểm tra. Giao diện hiện từng
     điều kiện thành chip ✓ / ✗ / ·, nên đặt tên ngắn, đọc là hiểu.
  3. Viết scan(): gọi g.need("tên điều kiện", điều_kiện, "lý do khi chưa đạt") cho từng điều kiện.
     Điều kiện nào sai thì scan dừng ngay ở đó (khung tự bắt), các điều kiện sau hiện "chưa xét".
     Đủ hết thì trả Plan(side, entry, stop, take, summary). take=None: khung tự tính theo `reward`.
  4. Đăng ký trong services/api/methods/__init__.py (danh sách _MODULES) và đặt status = "paper".
  5. Khởi động lại server. Agent xuất hiện ở phòng nghiên cứu (trang Phòng giao dịch và Phương
     pháp), ghi lệnh giấy trên mỗi nến M15 đóng, và chọn được trên trang Kiểm thử.
  6. Kiểm thử tách đôi: chọn tham số trên 2022–2024, kiểm tra trên 2025–2026, thêm chênh lệch gấp đôi.
     Chỉ khi cả hai giai đoạn dương mới bàn chuyện lên tiền thật (bước riêng, cần bạn đồng ý).

Dữ liệu trong m (thị trường trên nến vừa đóng, xem strategies._market):
  m["bars"]        list nến (open, high, low, close), nến cuối là nến vừa đóng (tối đa 600 nến)
  m["times"]       giờ mở của từng nến (UTC, giây)
  m["timeframe"]   "M15", ...           m["price"]      giá đóng nến cuối
  m["ema20"], m["ema50"], m["ema200"]   EMA của nến cuối;  m["ema20Prev"] EMA20 nến trước
  m["atr"]         ATR 14;  m["atr100"] ATR 100;  m["expanding"] ATR14 ≥ ATR100
  m["adx"]         ADX 14;  m["rsi"]    RSI 14
  m["higherBias"]  "up" / "down" / "flat" / "unknown" của khung lớn (H1 khi đang ở M15)
  m["recentHigh"], m["recentLow"]  đỉnh/đáy 20 nến;  m["support"], m["resistance"]
Hàm tiện ích trong base: series(m, "ema"|"rsi"|"atr", kỳ), box(m, số_nến), trend_side(m),
frame_bias(m, giây), close_position(nến), side_word(side).
"""
from services.api.methods.base import Gates, Method, Plan, box, side_word


class TemplateMethod(Method):
    id = "template"  # khóa ngắn, không dấu, không trùng
    name = "Tên phương pháp"
    alias = "Tên trader"
    family = "trend"
    magic = 260699  # mã sổ riêng (chỉ dùng khi lên tiền thật)
    status = "draft"
    why = "Vì sao gắn tên trader này."
    source = "Mô tả phương pháp bằng một câu."
    gates = (
        "Điều kiện 1",
        "Điều kiện 2",
    )
    entry_rules = ("Mô tả điều kiện 1", "Mô tả điều kiện 2")
    exit_rules = ("Chốt lời 2R", "Đóng sau tối đa 48 nến")
    manage = "fixed"
    reward = 2.0
    max_bars = 48

    def scan(self, m: dict[str, object], g: Gates) -> Plan | None:
        high, low = box(m, 20)
        last = m["bars"][-1]
        side = "buy" if last[3] > high else "sell"
        g.need("Điều kiện 1", last[3] > high or last[3] < low, "giá chưa ra khỏi vùng 20 nến")
        g.need("Điều kiện 2", m["expanding"], "biến động chưa mở rộng")
        entry = float(last[3])
        stop = (high + low) / 2
        return Plan(side, entry, stop, None, f"Tín hiệu {side_word(side)} mẫu.")
