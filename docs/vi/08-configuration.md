# 8. Cấu hình & dữ liệu

[English](../en/08-configuration.md) · [Mục lục tài liệu](../README.md)

## 8.1 Cấu hình nằm ở đâu

Hầu hết mọi thứ được cấu hình trong giao diện và lưu trong SQLite (`data/app.db`). Biến môi trường
duy nhất đều là tùy chọn (xem `.env.example`; GoldTrader không tự đọc file `.env` — hãy đặt biến
trong shell hoặc trình khởi chạy của bạn).

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CLAUDE_CLI` | (tự tìm) | Đường dẫn đầy đủ tới `claude.exe`; nếu không có thì `PATH`, rồi bản mới nhất của extension VS Code |
| `GOLDTRADER_AUTOPILOT` | `1` | `0` = không chạy vòng nền / không họp theo lịch |

## 8.2 Cài đặt trong giao diện

| Màn hình | Gì | Lưu ở |
|---|---|---|
| Cài đặt → MetaTrader 5 | đường dẫn terminal, máy chủ, tài khoản, mã, mật khẩu | `mt5_settings` (mật khẩu mã hóa DPAPI) |
| Cài đặt → Claude | bật/tắt ý kiến Claude cho từng tín hiệu | cờ `llmJudge` |
| Cài đặt → Telegram | bật, chat id, token bot | `telegram_settings` (token mã hóa DPAPI) |
| Rủi ro | mỗi lệnh, lỗ ngày, sụt giảm, vị thế, chuỗi thua, tỷ lệ lời/lỗ, lot tối thiểu, tổng rủi ro mở | `risk_settings` |
| Mô hình | chế độ và huấn luyện mô hình tín hiệu | `model_settings`, `data/models/` |
| Chế độ (thanh bên) | `analysis` / `signal` / `semi` / `full`, dừng khẩn cấp | `data/runtime.json` |
| Quản lý agent | tiền thật hay nghiên cứu cho từng agent | cờ `agentReal:<id>` |

## 8.3 Cờ (bảng `app_flags`)

| Cờ | Ý nghĩa |
|---|---|
| `agentReal:<id>` | `on`/`off`; không có = mặc định của sổ (`defaultReal`, nếu không thì tiền thật) |
| `llmJudge` | `on`/`off` cổng Claude cho từng tín hiệu |
| `meetingDate` | ngày UTC gần nhất cuộc họp theo lịch đã bắt đầu |
| `meetingRunning` | đặt khi cuộc họp đang chạy (phát hiện cuộc họp bị gián đoạn) |

## 8.4 Hằng số trong mã bạn có thể chỉnh

| Hằng số | File | Ý nghĩa |
|---|---|---|
| `LIVE_TIMEFRAME`, `DECISION_SECONDS` | `live.py` | khung của sổ chính (M15) |
| `AUTOPILOT_SECONDS` (5) | `live.py` | chu kỳ vòng nền |
| `SEND_WINDOW_SECONDS` (120) | `live.py` | tuổi tối đa của nến đã đóng để còn gửi lệnh |
| `EXTRA_BOOKS` | `live.py` | các agent (khung, magic, chiến lược, tên, `defaultReal`) |
| `MANAGER_PRIOR_TRADES`, `MANAGER_EDGE` | `live.py` | xếp hạng của trưởng phòng |
| `BLOCK_HOURS` (18–23 UTC) | `strategies.py` | không khớp lệnh trong các giờ này |
| `MEETING_HOUR_UTC/MINUTE_UTC`, `MAX_IMPROVE` | `meeting.py` | lịch họp và số lần sửa mã |
| `TESTED` | `methods/__init__.py`, `agents.py` | số liệu walk-forward đã lưu |

## 8.5 Thư mục `data/` (git bỏ qua)

```
data/app.db              cài đặt, cờ, rủi ro, sổ lệnh, lệnh giấy, nhật ký
data/runtime.json        trạng thái trực tiếp (chế độ, khóa, quyết định gần nhất mỗi sổ)
data/candles/<MÃ>/       bộ đệm nến cho biểu đồ
data/models/             mô hình ML tùy chọn
data/meetings/           biên bản họp (JSON mỗi ngày)
data/backups/<ts>/       bản sao mã nguồn trước khi cuộc họp sửa code
data/backtest-latest.json
data/uvicorn.log|err     log server nếu chạy bằng tiến trình khởi động lại
```

**Sao lưu:** chép thư mục `data/` khi server đã dừng. **Chuyển sang máy khác:** mật khẩu MT5 và token
Telegram đã lưu không chuyển được — blob DPAPI gắn với người dùng Windows và máy — nên hãy nhập lại
trong giao diện trên máy mới.

**Bắt đầu lại từ đầu:** dừng server và xóa `data/` (mất sổ lệnh và cài đặt).

## 8.6 Không bao giờ commit

`data/`, `.env*`, mọi file `*.db`, log, ảnh chụp màn hình có số tài khoản. `.gitignore` đã chặn
sẵn; hãy chạy `git status` trước mỗi lần push.
