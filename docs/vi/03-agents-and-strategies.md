# 3. Agent & chiến lược

[English](../en/03-agents-and-strategies.md) · [Mục lục tài liệu](../README.md)

> Tên agent là nhãn mượn từ các nhà giao dịch nổi tiếng để mô tả phong cách của phương pháp. Không
> có ý liên kết hay được bảo trợ.

## 3.1 Các agent

Mỗi agent là một chiến lược trên một khung thời gian, có **mã sổ MT5 (magic) riêng** và tối đa **một
lệnh đang mở**. Agent tổng là trưởng phòng (bí danh "Paul Tudor Jones").

| Mã agent | Bí danh | Khung | Magic | Phương pháp (tóm tắt) | Mặc định |
|---|---|---|---|---|---|
| `trend-M15` | Linda Raschke | M15 | 260611 | Hồi về EMA 20 theo xu hướng, biến động mở rộng, cắt lỗ bám | tiền thật |
| `trend-M30` | Ed Seykota | M30 | 260612 | Cùng phương pháp xu hướng trên M30, TP 2R, 48 nến | tiền thật |
| `pullback-M15` | Larry Connors | M15 | 260613 | RSI(2) giảm sâu trong xu hướng dài, TP 1,5R, 24 nến | tiền thật |
| `breakout-M15` | Nicolas Darvas | M15 | 260614 | Phá vùng | tiền thật |
| `reversal-M15` | Richard Wyckoff | M15 | 260615 | Đảo chiều sau quét thanh khoản | tiền thật |
| `range-M15` | John Bollinger | M15 | 260616 | Đi ngang / hồi về trung bình Bollinger | tiền thật |
| `reentry-M15` | Jesse Livermore | M15 | 260617 | Vào lại lần hai trong cùng nhịp xu hướng | tiền thật |
| `mtf-M15` | Alexander Elder | M15 | 260618 | Xu hướng đa khung | tiền thật |
| `brkconfirm-M15` | William O'Neil | M15 | 260619 | Phá vùng có xác nhận | tiền thật |
| `retest-M15` | Al Brooks | M15 | 260620 | Phá vùng rồi kiểm tra lại | tiền thật |
| `momentum-M15` | Richard Dennis | M15 | 260621 | Phá vùng động lượng, cắt lỗ bám | tiền thật |
| `volexp-M15` | Toby Crabel | M15 | 260622 | Bùng nổ biến động | tiền thật |
| `fakeout-M15` | Larry Williams | M15 | 260623 | Phá vỡ thất bại (đánh ngược) | tiền thật |
| `trend-H4` | John W. Henry | H4 | 260624 | Xu hướng H4, TP 2R, 48 nến | tiền thật |
| `flag-M30` | Dan Zanger | M30 | 260625 | Cờ tăng (chỉ mua) | **nghiên cứu** |
| `flag-H1` | Thomas Bulkowski | H1 | 260626 | Cờ tăng (chỉ mua) | **nghiên cứu** |

"Mặc định" là mức của bản cài mới. Cuộc họp hằng ngày và bạn có thể đổi bất cứ lúc nào.

## 3.2 Tiền thật và nghiên cứu

- **Tiền thật**: agent gửi lệnh với magic của mình.
- **Nghiên cứu (lệnh giấy)**: không gửi lệnh mới; tín hiệu được ghi thành lệnh giấy và theo dõi tới
  khi chạm cắt lỗ / mục tiêu / hết giờ. Lệnh thật đang mở của agent vừa chuyển xuống nghiên cứu vẫn
  được quản lý tới khi đóng.
- Chuyển trong giao diện (*Quản lý agent*, hoặc bấm vào bàn trong phòng làm việc) hoặc bằng
  `POST /api/agents/mode {"id": "...", "real": true|false}`.

## 3.3 Lợi thế kiểm thử trung thực

Walk-forward trên lịch sử M15 đã lưu, $10k, chênh lệch giá 0,2 (chọn 2022–2024 / kiểm tra
2025–2026), R trung bình mỗi lệnh. Một phương pháp chỉ đạt chuẩn khi **cả hai** giai đoạn ≥ +0,05R
và PF ≥ 1,10.

| Agent | 2022–24 | 2025–26 | Kết luận |
|---|---|---|---|
| trend-M15 / pullback-M15 / trend-M30 | toàn kỳ 2022–26: +0,152R / +0,188R / +0,122R mỗi lệnh; dương hầu hết các năm (2022 yếu, trend-M30 −4R) | | nhóm cốt lõi |
| trend-H4 | +0,131R | +0,262R | đạt nhưng ít lệnh (36 / 32) |
| flag-M30 | +0,335R PF 1,75 | +0,288R PF 1,60 | đạt |
| flag-H1 | +0,099R PF 1,19 | +0,081R PF 1,16 | đạt (mỏng) |
| reentry | +0,006R | +0,094R | trượt 2022–24 |
| brkconfirm | −0,029R | +0,091R | trượt 2022–24 |
| momentum / retest | −0,09R / −0,04R | +0,02R / +0,01R | trượt |
| mtf, volexp, fakeout | âm | âm | trượt |
| breakout / reversal / range | gần như không có lợi thế (reversal ≈ 0,006R; range quá ít lệnh) | | chưa chứng minh |

Điều rút ra từ các con số: chiến lược đánh ngược và đi ngang thua trên vàng; chỉ có hồi về EMA theo
xu hướng kèm bộ lọc biến động là lợi thế bền; mẫu nến (toàn bộ 61 mẫu TA-Lib) không có lợi thế; cờ
tăng M30/H1 bền nhưng chỉ mua trong thị trường tăng (lưu ý xu hướng nền). **Đừng bật agent trượt
kiểm thử với tiền thật** trừ khi bạn chấp nhận trả tiền cho thí nghiệm.

## 3.4 Chiến lược cốt lõi (xu hướng)

Các điều kiện theo thứ tự (hiện thành ô xanh/đỏ trong giao diện): EMA 20/50/200 xếp cùng một chiều ·
ADX ≥ 15 · khung lớn cùng chiều · biến động mở rộng (ATR14 ≥ ATR100) · một trong ba nến trước chạm
EMA 20 · ba giá đóng gần nhất giữ EMA 50 · nến xác nhận đóng theo xu hướng, vượt đỉnh/thủng đáy
nến trước · thân nến tín hiệu ≤ 1 ATR (M15) · cắt lỗ ≤ 3 ATR · giờ khớp ngoài 18–24 UTC. Cắt lỗ đặt
sau nhịp hồi. M15: không chốt lời cố định, cắt lỗ bám (3 ATR) khi lãi đạt 1R; M30/H4: TP 2R và dừng
sau 48 nến. Danh sách điều kiện chính xác của từng chiến lược nằm trong
`services/api/strategies.py` và `methods/*.py`.

## 3.5 Sao

Mỗi bàn hiện sao theo **lãi ròng của các lệnh thật đã đóng**: agent có lãi 3–5 (cao nhất = 5), lỗ
hoặc hòa 1–2, chưa có lệnh đóng 0. Sao xếp hạng bằng chứng, không phải chất lượng: vài lệnh chưa
chứng minh được gì.

## 3.6 Trưởng phòng phân xử

Khi nhiều agent tiền thật báo tín hiệu trên **cùng một nến**, trưởng phòng xếp hạng theo điểm =
(40 × lợi thế kiểm thử + tổng R thật) / (40 + số lệnh thật đã đóng) và chỉ cho agent tốt nhất vào
lệnh. Không bao giờ mở mua và bán cùng nến, không mở ngược lệnh đang lãi của agent khác. Tín hiệu ở
các thời điểm khác nhau đều được phép, nên thành tích mỗi agent cho thấy tín hiệu của nó đúng hay
sai. Các quyết định được ghi vào nhật ký (`arbitration`).

## 3.7 Thêm một agent

1. Sao chép `services/api/methods/_template.py`, cài điều kiện, `scan`, cắt lỗ/mục tiêu (xem
   `methods/base.py`, `bull_flag.py` làm ví dụ đầy đủ).
2. Đăng ký trong `methods/__init__.py`.
3. Thêm một sổ vào `EXTRA_BOOKS` trong `live.py` với **magic mới** và tên; thêm mô tả danh tính ở
   `agents.py`.
4. Chạy walk-forward ([07](07-backtest-and-research.md)), lưu kết quả vào `methods.TESTED`.
5. Để ở nghiên cứu (`"defaultReal": False`) cho tới khi nó kiếm được tiền thật.
6. Thêm test trong `tests/`.
