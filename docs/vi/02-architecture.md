# 2. Kiến trúc

[English](../en/02-architecture.md) · [Mục lục tài liệu](../README.md)

Monolith theo module: một tiến trình Python (FastAPI + một luồng autopilot chạy nền), một cơ sở dữ
liệu SQLite, một giao diện một trang. Không có message bus, không có microservice.

```
                 ┌──────────────────────── trình duyệt ───────────────────┐
                 │  mockup/index.html  (giao diện, phòng làm việc, hộp thoại)│
                 └───────────────▲──────────────────────────┬──────────────┘
                                 │ GET /api/live (2 giây)    │ POST …
                      ┌──────────┴──────────────────────────▼──────────┐
                      │ services/api/main.py  (FastAPI, 127.0.0.1:8787) │
                      └──────────┬──────────────────────────────────────┘
          khởi động luồng nền    │
┌────────────────────────────────▼─────────────────────────────────────────┐
│ live.py  run_autopilot  → snapshot() mỗi 5 giây  (dưới _STATE_LOCK)       │
│   đọc MT5 ─► sổ chính trend-M15 ─► _book_step cho từng EXTRA_BOOK         │
│   ─► trưởng phòng: _manager_review / _coordinator_blocks / _risk_blocks   │
│   ─► _claude_gate (tùy chọn) ─► _send_order ─► sổ lệnh ─► Telegram        │
│   meeting.maybe_start()  (22:10 UTC, thứ Hai–thứ Sáu)                      │
└───────┬─────────────┬──────────────┬─────────────┬──────────────┬────────┘
        │             │              │             │              │
  mt5_session    strategies +     shadow.py     journal.py    llm_judge.py
  (MetaTrader5)  methods/*       (lệnh giấy)    (SQLite)     (Claude CLI)
```

## 2.1 Nhịp ra quyết định

- Autopilot thức dậy **mỗi 5 giây** (`AUTOPILOT_SECONDS`) và chạy `snapshot()`; không cần mở tab
  trình duyệt.
- Mỗi agent ("sổ") quyết định **một lần cho mỗi nến đóng của khung riêng** (M15, M30, H1, H4).
  Lệnh chỉ được gửi trong `SEND_WINDOW_SECONDS` (120 giây) sau khi nến đóng, không bao giờ vào trễ.
- Giữa các nến, lệnh đang mở được quản lý: dừng theo thời gian (`maxBars`), cắt lỗ bám cho agent
  dạng trail. Cắt lỗ và chốt lời luôn được đặt phía sàn lúc vào lệnh.
- Cuối tuần: vòng lặp nghỉ khi thị trường đóng cửa.

## 2.2 Sổ và agent

`live.all_books()` trả về sổ chính (`trend-M15`) cộng `EXTRA_BOOKS`. Mỗi sổ có khung thời gian, số
giây mỗi nến, **mã sổ (magic)**, mã chiến lược và tên hiển thị. Tiền thật / nghiên cứu là cờ
`agentReal:<id>` (lưu ở `app_flags`, mặc định là tiền thật trừ khi sổ ghi `"defaultReal": False`).
Xem [03-agents-and-strategies.md](03-agents-and-strategies.md).

## 2.3 Trưởng phòng (agent tổng)

Cài đặt trong `live.py`:

- `_manager_review` — mỗi nến mới đóng, gom mọi agent tiền thật đang báo tín hiệu và chỉ cho agent
  xếp cao nhất vào lệnh (điểm = lợi thế kiểm thử co về kết quả thật). Không mở mua và bán cùng
  lúc. Các thời điểm khác nhau không bị phân xử.
- `_coordinator_blocks` — không bao giờ mở ngược lệnh *đang lãi* của agent khác; giới hạn tổng
  rủi ro đang mở (`maxOpenRiskPercent`).
- `_risk_blocks` — các cổng tài khoản: lỗ ngày, khóa sụt giảm, số vị thế tối đa, chuỗi thua theo
  từng agent, chênh lệch giá, vị thế chưa có cắt lỗ.

## 2.4 Agent nghiên cứu (lệnh giấy)

Agent có cờ tiền thật tắt không bao giờ gửi lệnh vào. Chúng vẫn đánh giá và ghi **lệnh giấy**
(`shadow.py`), đóng theo cùng quy tắc cắt lỗ / mục tiêu / thời gian để so với kết quả thật. Mỗi
dòng lệnh giấy mang `frame_seconds`.

## 2.5 Backtest

`backtest.py::_simulate` phát lại lịch sử qua **cùng đường mã quyết định** như giao dịch thật (thẻ
chiến lược, điều kiện, thoát lệnh, giới hạn rủi ro, chênh lệch giá, phí qua đêm, bước khối lượng).
Chế độ: `auto` (bản sao của bộ chọn chính), một mã chiến lược, và `agents` (nhiều agent). Báo cáo
gồm chỉ số, thống kê từng agent và danh sách lệnh (`chartTrades`).

## 2.6 Dữ liệu và trạng thái

| Ở đâu | Gì |
|---|---|
| `data/app.db` | cài đặt, cờ, rủi ro, sổ lệnh (`trade_journal`), lệnh giấy, lượt gọi/phủ quyết LLM, nhật ký `manager_log` |
| `data/runtime.json` | trạng thái trực tiếp: chế độ, dừng khẩn cấp, khóa sụt giảm, nến/quyết định gần nhất mỗi sổ, trạng thái trưởng phòng |
| `data/candles/` | bộ đệm nến cho biểu đồ |
| `data/models/` | mô hình ML tùy chọn (mô hình tín hiệu, báo cáo LightGBM/XGBoost/HMM) |
| `data/meetings/` | một file biên bản JSON cho mỗi ngày họp |
| `data/backups/` | bản sao mã nguồn trước khi cuộc họp sửa code |

`data/` bị git bỏ qua. `runtime.json` được ghi nguyên tử (file tạm + `fsync` + thay thế); file đọc
không được sẽ chuyển thành `runtime.corrupt-<ts>.json`.

## 2.7 Bí mật

`secrets.py` bọc Windows DPAPI (`CryptProtectData`): mật khẩu MT5 và token Telegram được mã hóa cho
người dùng Windows hiện tại và lưu dạng blob trong `app.db`. Chúng không bao giờ bị ghi log hay
trả về qua API.

## 2.8 ML tùy chọn

`trainer.py` (LightGBM + XGBoost + GARCH + HMM) và `meta_model.py` (bộ chấm tín hiệu logistic) là
tùy chọn. Nghiên cứu không thấy lợi thế đáng tin từ các mô hình dự đoán hướng; mô hình tín hiệu
chỉ dùng ở chế độ `shadow` hoặc `size` để ghi nhận hoặc giảm nửa khối lượng, không bao giờ bỏ lệnh
hay tăng khối lượng.

## 2.9 Nên xem file nào

| Tôi muốn… | File |
|---|---|
| đổi lúc/cách gửi lệnh | `services/api/live.py` (`_book_step`, `_send_order`) |
| thêm / chỉnh một agent | `services/api/methods/`, `agents.py`, `EXTRA_BOOKS` trong `live.py` |
| đổi luật rủi ro | `live._risk_blocks`, `settings_store.py` |
| hiểu backtest | `services/api/backtest.py` |
| đổi giao diện | `mockup/index.html` |
