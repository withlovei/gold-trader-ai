# 4. Rủi ro & an toàn

[English](../en/04-risk-and-safety.md) · [Mục lục tài liệu](../README.md)

Luật rủi ro nằm trong mã (`live._risk_blocks`, `_coordinator_blocks`, `_drawdown_gate`) và **độc
lập với mọi AI**: Claude hay ML chỉ có thể giảm hoặc bỏ lệnh; không gì ghi đè được cổng rủi ro hay
làm lệnh lớn hơn mức luật cho phép.

## 4.1 Cài đặt (màn hình Rủi ro / `POST /api/settings/risk`)

| Cài đặt | Khóa | Mặc định | Ý nghĩa |
|---|---|---|---|
| Rủi ro mỗi lệnh | `perTradePercent` | 0,5 % | % vốn mất nếu chạm cắt lỗ; tính lot từ khoảng cắt lỗ thật, tick size và tick value |
| Giới hạn lỗ ngày | `dailyLossPercent` | 2 % | không vào lệnh mới khi lỗ trong ngày chạm mức này |
| Giới hạn sụt giảm | `drawdownPercent` | 10 % | khóa lệnh mới khi vốn thấp hơn đỉnh chừng này |
| Số vị thế tối đa | `maxPositions` | 2 (1–20) | số vị thế mở trên mọi agent |
| Chuỗi thua tối đa | `maxLossStreak` | 3 | theo từng agent: thua liên tiếp chừng này lệnh thì agent nghỉ hết ngày |
| Tỷ lệ lời/lỗ tối thiểu | `minRewardRatio` | 1,5 | khoảng chốt lời / cắt lỗ tối thiểu cho kế hoạch có mục tiêu cố định |
| Giới hạn lot tối thiểu | `minLotPercent` | 0 | nếu lot tính ra nhỏ hơn mức tối thiểu của sàn, gửi lot tối thiểu **chỉ khi** rủi ro của nó ≤ % này (cho tài khoản nhỏ giao dịch được) |
| Tổng rủi ro mở | `maxOpenRiskPercent` | 6 % | tổng rủi ro của mọi vị thế agent đang mở |

Mặc định dành cho một agent. Phòng nhiều agent cần `maxPositions` và `maxOpenRiskPercent` lớn hơn
(tác giả chạy 0,75 % mỗi lệnh, lỗ ngày 2,5 %, khóa sụt giảm 30 %, 14 vị thế, rủi ro mở 30 % trên
tài khoản demo nhỏ). Hãy chọn số của riêng bạn; rủi ro lớn hơn nghĩa là sụt giảm lớn hơn.

## 4.2 Các cổng áp dụng trước mỗi lệnh vào

1. Chế độ là *Tự động* và dừng khẩn cấp đang tắt.
2. Agent ở tiền thật; không có lệnh đang mở; chuỗi thua dưới giới hạn.
3. Lỗ ngày, khóa sụt giảm, số vị thế tối đa, tổng rủi ro mở, chênh lệch giá (≤ 0,8 đơn vị giá), và
   không có vị thế nào thiếu cắt lỗ.
4. Tín hiệu còn mới: nến đóng cách đây ≤ 120 giây (không vào trễ).
5. Trưởng phòng: không ngược lệnh đang lãi của agent khác; một lệnh cho mỗi nến giữa các agent
   cạnh tranh.
6. Khối lượng: tính từ rủi ro, khoảng cắt lỗ, tick value thật và bước khối lượng của mã; cộng quy
   tắc lot tối thiểu ở trên.
7. Cổng Claude tùy chọn: `vào` (đủ), `giảm` (một nửa), `bỏ` (bỏ qua). Không trả lời ⇒ theo luật.

## 4.3 Khóa sụt giảm

Khi vốn thấp hơn đỉnh `drawdownPercent`, lệnh mới bị khóa. Khóa tự mở **một lần** sau thời gian chờ,
đỉnh được tính lại từ vốn hiện tại; lần khóa thứ hai cần mở khóa thủ công (`POST /api/risk/unlock`
hoặc nút trong giao diện). Lệnh đang mở vẫn giữ cắt lỗ.

## 4.4 Cách hệ thống tự bảo vệ

- **SL/TP phía sàn** cho mọi lệnh vào; dừng theo thời gian và cắt lỗ bám là phần thêm.
- **Chống gửi trùng:** `lastSentBar` theo từng nến, ghi xuống đĩa *trước* khi có thể gửi lại.
- **Một vị thế cho mỗi agent**, nhận diện bằng magic.
- **Cần tài khoản hedging**; các agent có thể giữ lệnh ngược chiều cùng lúc (lệnh đang lỗ không bị
  đóng chỉ vì agent khác đổi hướng).
- **Chịu được khởi động lại:** trạng thái nằm trên đĩa; autopilot chạy tiếp ở nến sau; file trạng
  thái hỏng được cách ly.
- **MT5 ngừng:** vòng lặp ghi lỗi và thử lại; không bao giờ coi lệnh đã thành công nếu chưa có xác
  nhận từ sàn.
- **Claude / Telegram ngừng:** giao dịch tiếp tục theo luật cố định.
- **Dừng khẩn cấp:** chặn mọi lệnh mới ngay (lệnh đang mở vẫn giữ cắt lỗ).

## 4.5 Hệ thống KHÔNG bảo vệ bạn khỏi

- Sàn nới chênh lệch giá hoặc báo giá lại; giá nhảy qua cắt lỗ (trượt giá được ghi trong sổ lệnh).
- Chiến lược suy yếu: lợi thế mỏng và phụ thuộc giai đoạn thị trường.
- Cài đặt của chính bạn: rủi ro quá lớn sẽ cháy tài khoản.
- Cuộc họp hằng ngày có thể đổi mã (xem [05](05-daily-meeting.md)); hãy xem nhật ký của nó.

## 4.6 Lời khuyên thực tế

- Demo trước, nhiều tuần. Giữ rủi ro mỗi lệnh nhỏ (≤ 1 %).
- Ưu tiên agent đạt cả hai giai đoạn walk-forward; để agent trượt ở nghiên cứu.
- Đừng sửa tay `data/runtime.json` khi server đang chạy.
- Coi mọi con số backtest là mức trần.
