# 5. Họp hằng ngày (phòng giao dịch tự cải thiện)

[English](../en/05-daily-meeting.md) · [Mục lục tài liệu](../README.md)

Mỗi ngày giao dịch, trưởng phòng gọi **Claude CLI** để đánh giá cả phòng, quyết định agent nào giao
dịch tiền thật, và tùy chọn giao cải tiến mã của một agent. Cài đặt trong
`services/api/meeting.py` (+ `restart.py`, `journal.manager_log`).

> Tính năng này trao cho AI **toàn quyền** quyết định agent nào giao dịch tiền thật và quyền **sửa
> mã nguồn của bạn mà không qua cổng backtest**. Hãy xem nhật ký sau mỗi cuộc họp. Tắt nếu không
> muốn như vậy (xem §5.6).

## 5.1 Lịch

- **22:10 UTC, thứ Hai–thứ Sáu** (5:10 sáng giờ Việt Nam), ngay sau khi vàng đóng cửa ngày.
- Do vòng autopilot khởi chạy (`meeting.maybe_start`), một lần cho mỗi ngày UTC (cờ `meetingDate`).
- Thủ công: nút **Họp ngay** (giao diện, thanh công cụ phòng làm việc, hoặc bàn trưởng phòng) hoặc
  `POST /api/meeting/run`.

## 5.2 Diễn biến

1. **Gom dữ liệu**: với mỗi agent — số walk-forward, điểm của trưởng phòng, thống kê lệnh thật, thống
   kê lệnh giấy, lệnh trong 26 giờ qua, ảnh chụp tài khoản, tóm tắt cuộc họp trước.
2. **Quyết định** (Claude CLI, không dùng công cụ): trả JSON
   `{"summary", "decisions": [{id, real, reason}], "improve": [{id, goal}]}`. Mọi agent đều có
   quyết định; thay đổi `real` được áp dụng ngay (`set_agent_real`). Không có ngưỡng nào bị ép: CLI
   tự quyết.
3. **Cải tiến** (tối đa 2 agent, `MAX_IMPROVE`): lần gọi Claude CLI thứ hai với công cụ
   `Read, Edit, Write, Grep, Glob` và `--permission-mode acceptEdits` tại thư mục gốc repo sẽ sửa
   trực tiếp mã nguồn của agent.
4. **Lưới an toàn** (giữ lại dù không có cổng backtest):
   - toàn bộ thư mục `services/` được sao sang `data/backups/<thời điểm>/` trước;
   - sau khi sửa, một **bài chạy thử** import ứng dụng và đánh giá danh mục chiến lược trên nến
     tổng hợp cho M15/M30/H1/H4; hỏng thì khôi phục bản sao;
   - bản diff của mọi file đã sửa được lưu vào nhật ký.
5. **Khởi động lại**: nếu có mã được áp dụng, một tiến trình phụ tách rời (`python -m
   services.api.restart`) dừng server, chạy lại với mã mới và chờ `/api/health`; nếu server mới
   không trả lời trong 60 giây thì mã được khôi phục từ bản sao và server chạy lại.
6. **Biên bản**: lưu ở `data/meetings/<ngày>.json`, tóm tắt gửi Telegram, ghi vào nhật ký.

Một bản sửa chạy được nhưng làm chiến lược tệ hơn **không** được tự phát hiện. Agent đã bị sửa nên
ở nghiên cứu cho tới khi lệnh giấy chứng minh được nó.

## 5.3 Nhật ký

Mỗi bước là một dòng trong `manager_log` gắn mã cuộc họp: bắt đầu/tóm tắt cuộc họp, quyết định từng
agent, chuyển bàn, giao cải tiến, sửa mã (kèm diff), khôi phục, khởi động lại, và phân xử theo nến
của trưởng phòng. Giao diện hiện mỗi cuộc họp thành một thẻ có chip (⬆ tiền thật, ⬇ bàn giấy, 🛠 mã,
↩ khôi phục) và dòng thời gian riêng; dòng sửa mã mở ra thành diff có màu. `GET /api/meetings` trả
dữ liệu đã nhóm, `GET /api/manager-log` trả nhật ký phẳng.

Khi đang họp, **Họp ngay** mở hộp thoại hiện diễn biến trực tiếp (`GET /api/meeting` →
`status.events`), các quyết định và kết quả.

## 5.4 Chi phí

Mỗi cuộc họp gồm một lần gọi quyết định (~$0,05–0,5, vài phút) cộng tối đa hai lần chạy sửa mã (mỗi
lần vài phút và vài đô la quy đổi API). Tính vào gói Claude của bạn.

## 5.5 Cảnh báo khi khởi động lại

Không bao giờ khởi động lại server khi cuộc họp đang chạy: luồng họp chết giữa chừng. Kiểm tra
`GET /api/meeting` → `status.running` trước. Nếu một cuộc họp bị cắt ngang, lần chạy autopilot kế
tiếp ghi dòng "gián đoạn" vào nhật ký; hãy xem `git diff` và `data/backups/`.

## 5.6 Tắt hoặc giới hạn

- Chạy server với `GOLDTRADER_AUTOPILOT=0`: vòng nền, và do đó cuộc họp theo lịch, không khởi động
  (vẫn bấm *Họp ngay* được; tab giao diện đang mở vẫn chạy bước ra quyết định, nên dùng chế độ
  *Chỉ xem* để chắc chắn không có lệnh), hoặc
- xóa lời gọi `meeting.maybe_start` trong `live.run_autopilot`, hoặc
- đặt `MAX_IMPROVE = 0` trong `meeting.py` để giữ quyết định nhưng cấm sửa mã.

## 5.7 Xem lại và hoàn tác thay đổi mã

```powershell
git diff                       # thay đổi trong thư mục làm việc
git checkout -- services\api\methods\trend_reentry.py      # hoàn tác một file
```

hoặc chép file về từ `data\backups\<thời điểm>\services\`.
