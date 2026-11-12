# 9. Xử lý sự cố

[English](../en/09-troubleshooting.md) · [Mục lục tài liệu](../README.md)

| Triệu chứng | Nguyên nhân có thể | Cách xử lý |
|---|---|---|
| Giao diện không có giá, "Mất kết nối" | Server không chạy | Chạy `scripts\start.bat`; kiểm tra `http://127.0.0.1:8787/api/health` |
| `Chưa đọc được giá thời gian thực` / lỗi MT5 | MT5 đóng, chưa đăng nhập, sai đường dẫn, mã chưa có trong Market Watch | Mở MT5, đăng nhập, đưa `XAUUSDm` vào Market Watch, kiểm tra lại đường dẫn/máy chủ/tài khoản trong Cài đặt |
| `ModuleNotFoundError: MetaTrader5` | Sai Python / không phải Windows / chưa dùng venv | Dùng `.venv\Scripts\python.exe -m pip install -r requirements.txt`; chỉ Windows |
| Lệnh bị từ chối (retcode 10027) | Giao dịch tự động bị tắt | Bật nút **Algo Trading** ở MT5; Tools → Options → Expert Advisors |
| Lệnh bị từ chối "invalid stops/volume" | Giới hạn mã khác mặc định Exness | Kiểm tra lot tối thiểu/bước; tăng số dư hoặc `minLotPercent` |
| Không bao giờ có lệnh | Chế độ là *Chỉ xem* (mặc định lần đầu), dừng khẩn cấp, khóa sụt giảm, hoặc mọi agent ở nghiên cứu | Xem chế độ ở thanh bên, dòng chặn của từng agent, màn hình `Rủi ro` |
| Agent báo `đủ N vị thế` | Đã đạt `maxPositions` | Tăng `maxPositions` (và `maxOpenRiskPercent`) có chủ đích |
| Lệnh bị chặn "chênh lệch quá rộng" | Spread > 0,8 | Chờ; thường gặp lúc rollover/tin tức |
| Nhiều lần trượt điều kiện `Biến động mở rộng` (ATR14 ≥ ATR100) | Bộ lọc biến động theo thiết kế | Bình thường: ~⅓ số ngày không có tín hiệu xu hướng; đừng nới (đó chính là lợi thế) |
| `runtime.json unreadable` trong log | File bị cắt do mất điện | Đã xử lý: chuyển thành `runtime.corrupt-<ts>.json`, chế độ đặt lại Tự động; kiểm tra lại chế độ và khóa |
| Telegram thử không được | Sai token/chat id; chưa bắt đầu với bot | Nhắn bot trước; kiểm tra chat id qua `getUpdates`; xem dòng trạng thái `Cài đặt → Telegram` |
| Ý kiến Claude luôn "không có ý kiến" | Không thấy CLI / chưa đăng nhập / quá giờ | Đặt `CLAUDE_CLI`, chạy `claude` một lần để đăng nhập; **Cài đặt → Claude** hiện đường dẫn |
| Cuộc họp không chạy | Cuối tuần, chưa đến 22:10 UTC, server tắt, `GOLDTRADER_AUTOPILOT=0`, hôm nay đã họp | Bấm **Họp ngay** hoặc xem `GET /api/meeting` |
| Cuộc họp "bị gián đoạn" | Server khởi động lại giữa cuộc họp | Xem `git diff` và `data/backups/`, họp lại |
| Mã do cuộc họp sửa gây lỗi | Bản sửa của CLI chạy được nhưng sai | `git diff`, hoàn tác file (xem [05](05-daily-meeting.md) §5.7), giữ agent ở nghiên cứu |
| Giao diện mất định dạng | CDN bị chặn (Tailwind, biểu đồ, font) | Cho phép `cdn.tailwindcss.com`, `unpkg.com`, `fonts.googleapis.com` |
| Test lỗi thiếu `hist/M15.json` | Chưa tải lịch sử | `scripts\fetch_history.py <thư mục>`, rồi `tests\run_all.py <thư mục>` |
| `test_meeting` để lại file đã đổi | Test bị dừng giữa chừng | `git checkout -- services/api/methods/false_breakout.py` |

## Log

Server in ra cửa sổ của nó. Khi chạy bằng tiến trình khởi động lại, đầu ra nằm ở
`data/uvicorn.log` và `data/uvicorn.err`. Nhật ký trưởng phòng (`/api/manager-log`) hiện sự kiện
họp và phân xử. Sổ lệnh (`/api/journal`) hiện mọi lệnh thật kèm trượt giá, spread, lý do thoát và,
nếu bật, ý kiến của Claude.

## Nhờ giúp đỡ

Mở issue tại <https://github.com/withlovei/gold-trader-ai/issues> kèm: phiên bản Windows và Python,
bạn đã làm gì, nội dung lỗi, và **không** kèm mật khẩu, token, số tài khoản hay ảnh chụp màn hình
có chúng.
