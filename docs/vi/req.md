# Yêu cầu hệ thống & hiện trạng triển khai

[English](../en/req.md) · [Mục lục tài liệu](../README.md)

Tài liệu này thay thế bản đặc tả ban đầu (mô tả ứng dụng desktop Tauri/React, LLM qua OpenRouter và
event bus). Nó nêu hệ thống **hiện là gì** và cần gì, đồng thời liệt kê các ý tưởng ban đầu **chưa
xây**. Rà soát lần cuối: 2026-11-12.

## 1. Sản phẩm

Phòng giao dịch vàng (XAUUSD) tự động trên MetaTrader 5: 16 agent theo luật, một trưởng phòng phân
xử và giữ rủi ro, cuộc họp hằng ngày qua Claude CLI để phân bổ tiền thật / lệnh giấy và có thể sửa
mã agent, bộ backtest phát lại đúng đường mã thật, và giao diện một trang chạy cục bộ. Là phần mềm
nghiên cứu ưu tiên demo, không phải sản phẩm cam kết hiệu quả.

## 2. Yêu cầu chạy

| Yêu cầu | Giá trị |
|---|---|
| Hệ điều hành | Windows 10/11 (gói MetaTrader5, Windows DPAPI) |
| Python | 3.13 (3.11+ dự kiến chạy được) |
| Gói | `requirements.txt`: fastapi, uvicorn, pydantic, MetaTrader5, numpy, scipy, scikit-learn, lightgbm, xgboost, hmmlearn |
| Sàn / terminal | MetaTrader 5, tài khoản **hedging**; phát triển trên Exness Standard, `XAUUSDm` |
| Mạng | Chỉ cục bộ (127.0.0.1:8787). Internet cho MT5, các CDN của trang, Telegram, Claude |
| Tùy chọn | Claude CLI (`claude.exe`) cho cuộc họp và ý kiến thứ hai; bot Telegram |
| Phần cứng | Máy hiện đại bất kỳ; vòng lặp nhẹ (~600 nến mỗi khung mỗi lượt 5 giây). Backtest 4 năm M15 dùng vài trăm MB RAM |

## 3. Kiến trúc (như đã xây)

| Lớp | Công nghệ | Ở đâu |
|---|---|---|
| Giao diện | Một trang HTML, Tailwind (CDN), Lightweight Charts 4.1.3, canvas "phòng làm việc" | `mockup/index.html` |
| Backend | Python, FastAPI, Pydantic, một luồng autopilot nền | `services/api/` |
| Sàn | Gói Python `MetaTrader5`, một phiên tại một thời điểm | `mt5_session.py`, `mt5_client.py` |
| Lưu trữ | SQLite (`data/app.db`) + trạng thái JSON (`data/runtime.json`) | `settings_store.py`, `journal.py`, `shadow.py` |
| Bí mật | Windows DPAPI | `secrets.py` |
| AI | Claude CLI (`claude -p`, đầu ra JSON) cho cổng và cuộc họp; tùy chọn LightGBM/XGBoost/GARCH/HMM và mô hình tín hiệu logistic | `llm_judge.py`, `meeting.py`, `trainer.py`, `meta_model.py` |
| Thông báo | Telegram Bot API | `notify.py` |

Monolith theo module; không message bus, không microservice, không WebSocket (giao diện gọi
`/api/live` định kỳ).

## 4. Yêu cầu chức năng và trạng thái

Chú giải: ✅ đã làm · 🟡 một phần · ❌ chưa xây

### Kết nối MT5
| Yêu cầu | Trạng thái |
|---|---|
| Kết nối, số dư/vốn/ký quỹ, bid/ask, OHLC, thông số mã (tick size/value, khối lượng min/max/step), spread | ✅ |
| Vị thế đang mở, lịch sử giao dịch, lệnh thị trường MUA/BÁN kèm SL/TP, sửa SL (bám), đóng lệnh | ✅ |
| Chống gửi trùng, kết quả do sàn xác nhận, khớp/trượt giá ghi trong sổ lệnh | ✅ |
| Lệnh chờ, đóng một phần | ❌ |
| Tự kết nối lại | 🟡 (mỗi lượt mở lại phiên; lỗi được thử lại ở lượt sau) |

### Dữ liệu thị trường & phân tích
| Yêu cầu | Trạng thái |
|---|---|
| Khung M1…D1 cho biểu đồ; M5–H4 cho quyết định | ✅ |
| EMA 9/20/50/200, RSI, ATR, ADX, Bollinger, hỗ trợ/kháng cự, đỉnh đáy, zig-zag theo ATR | ✅ |
| MACD, Stochastic, VWAP, pivot, FVG, order block, thư viện mẫu nến | ❌ (mẫu nến đã được đánh giá ngoại tuyến và loại) |
| Trạng thái thị trường (HMM) | 🟡 tùy chọn, huấn luyện khi cần, không dùng để chặn lệnh |

### Chiến lược / agent
| Yêu cầu | Trạng thái |
|---|---|
| Xu hướng, hồi giá | ✅ nhóm cốt lõi đã kiểm chứng |
| Phá vùng, đảo chiều, đi ngang, vào lại, đa khung, phá vùng xác nhận, kiểm tra lại, động lượng, bùng nổ biến động, phá vỡ thất bại, cờ tăng | ✅ đã cài; đa số chưa chứng minh (xem [03](03-agents-and-strategies.md)) |
| Bộ chọn chiến lược theo trạng thái thị trường | ❌ thay bằng mỗi chiến lược một agent + trưởng phòng |
| Magic riêng từng agent, một vị thế mỗi agent, công tắc tiền thật/nghiên cứu, lệnh giấy (shadow) | ✅ |

### Quyết định, rủi ro, thực thi
| Yêu cầu | Trạng thái |
|---|---|
| Trưởng phòng: một lệnh mỗi nến giữa các agent cạnh tranh, không mua/bán cùng lúc, giới hạn tổng rủi ro mở | ✅ |
| Rủi ro mỗi lệnh, lỗ ngày, khóa sụt giảm, số vị thế, chuỗi thua theo agent, lọc spread, quy tắc lot tối thiểu, dừng khẩn cấp | ✅ |
| Giới hạn lỗ tuần, hạn chế phiên ngoài giờ cấm khớp 18–24 UTC | ❌ |
| Cắt lỗ bám (chandelier), dừng theo thời gian, SL/TP phía sàn | ✅ |
| Bộ chấm điểm có trọng số (xu hướng/AI/LLM) | ❌ (đã gỡ: chỉ mang tính trang trí) |
| Máy trạng thái lệnh tường minh | ❌ (vị thế được đối chiếu với MT5 mỗi lượt) |
| Chặn tin tức / lịch kinh tế | ❌ (đã thử ngoại tuyến: không có lợi) |

### AI
| Yêu cầu | Trạng thái |
|---|---|
| Mô hình ML cục bộ (LightGBM, XGBoost, GARCH, HMM) | 🟡 tùy chọn; không tìm thấy lợi thế đáng tin; không dùng để mở lệnh |
| Mô hình tín hiệu (meta) | 🟡 chỉ `shadow` (ghi) hoặc `size` (giảm nửa) |
| LLM thẩm định | ✅ qua **Claude CLI** (không phải OpenRouter): `vào` / `giảm` / `bỏ`, ghi sổ, không bao giờ tăng cỡ lệnh |
| OpenRouter, lớp LLM độc lập nhà cung cấp, quản lý prompt, theo dõi chi phí token | ❌ (chi phí do CLI báo được lưu theo từng lượt gọi) |
| Họp hằng ngày: Claude CLI quyết định tiền thật/lệnh giấy và sửa mã agent | ✅ |

### Backtest
| Yêu cầu | Trạng thái |
|---|---|
| Backtest OHLC bản sao của bản thật có spread, phí qua đêm, hoa hồng, quy tắc khối lượng, thống kê từng agent | ✅ |
| Walk-forward (chọn 2022–24, kiểm tra 2025–26), từng năm, thử gấp đôi spread | ✅ (script / công thức ở [07](07-backtest-and-research.md)) |
| Backtest theo tick, giao diện Monte Carlo, bộ tối ưu tham số | ❌ |

### Giao diện
| Yêu cầu | Trạng thái |
|---|---|
| Tổng quan giao dịch, phòng làm việc trực quan, thẻ agent, sổ lệnh, biểu đồ, rủi ro, kiểm thử, mô hình, cài đặt | ✅ |
| Công tắc tiền thật/nghiên cứu, hộp thoại cuộc họp, nhật ký theo từng cuộc họp, sao | ✅ |
| Vỏ desktop Tauri, React/TypeScript | ❌ (trang HTML thuần) |
| Đa ngôn ngữ | ✅ giao diện Việt/Anh (chọn ở thanh trên, `?lang=en`); tài liệu Anh + Việt. Văn bản do backend/Claude sinh ra chỉ dịch theo cụm đã biết |

### Vận hành
| Yêu cầu | Trạng thái |
|---|---|
| File trạng thái ghi nguyên tử, fsync; cách ly trạng thái hỏng | ✅ |
| Log có cấu trúc, giám sát lỗi, endpoint sức khỏe | 🟡 (`/api/health`, logging của Python) |
| Khung migration cơ sở dữ liệu | ❌ (thêm cột bằng `ALTER TABLE` khi thiếu) |
| Test | ✅ 11 script hồi quy trong `tests/` (MT5 giả + lịch sử thật) |

## 5. Yêu cầu phi chức năng

- **An toàn trước:** cổng rủi ro độc lập với AI; SL phía sàn cho mọi lệnh vào.
- **Truy vết:** mọi lệnh thật được ghi sổ kèm kế hoạch, giá khớp, trượt giá, spread, agent, lý do
  thoát và ý kiến Claude; nhật ký trưởng phòng theo từng cuộc họp.
- **Bảo mật:** bí mật mã hóa DPAPI; server chỉ nghe localhost; không xác thực (đừng mở ra ngoài).
- **Hiệu năng:** quyết định theo từng nến đóng; vòng 5 giây chỉ đọc và kiểm tra.
- **Dễ bảo trì:** type hint, mỗi phương pháp một module, có test, CLAUDE.md cho trợ lý AI.

## 6. Dữ liệu (các bảng SQLite như đã xây)

`mt5_settings`, `telegram_settings`, `risk_settings`, `model_settings`, `app_flags`,
`trade_journal`, `shadow_trades`, `llm_calls`, `llm_vetoes`, `manager_log` (+ bộ đệm nến/biểu đồ
dạng JSON). Thiết kế 20 bảng ban đầu không được áp dụng.

## 7. Hạn chế đã biết

- Chỉ Windows; một terminal MT5; tập trung XAUUSD (mã cấu hình được, nhưng chiến lược được chỉnh cho
  vàng).
- Lợi thế mỏng, phụ thuộc giai đoạn; 2022–2026 là thị trường vàng tăng (lưu ý xu hướng nền của cờ
  tăng chỉ mua).
- Cuộc họp hằng ngày có thể đổi mã mà không qua cổng backtest; bản sửa tệ hơn không được tự phát
  hiện.
- API cục bộ không có xác thực.

## 8. Ý tưởng của bản đặc tả gốc chưa xây

Ứng dụng desktop Tauri/React · OpenRouter và quản lý prompt · event bus với schema payload sự kiện ·
chấm điểm quyết định có trọng số · module lịch kinh tế · máy trạng thái lệnh · lệnh chờ / đóng một
phần · backtest theo tick · quy trình phê duyệt triển khai mô hình · lược đồ 20 bảng. Cố ý để ngoài
để giữ một monolith nhỏ, kiểm thử được; hoan nghênh đóng góp.
