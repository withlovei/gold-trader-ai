# 6. API HTTP

[English](../en/06-api.md) · [Mục lục tài liệu](../README.md)

FastAPI tại `http://127.0.0.1:8787`. Chỉ chạy cục bộ; **không có xác thực nên đừng mở cổng này ra
mạng**. Tài liệu tương tác: `/docs` (Swagger) khi server đang chạy. Mọi nội dung gửi nhận là JSON.
Lỗi trả về dạng `{"detail": ...}` hoặc `{"ok": false, "message": ...}`.

## Trực tiếp

| Phương thức | Đường dẫn | Mục đích |
|---|---|---|
| GET | `/api/live` | Ảnh chụp đầy đủ: giá, tài khoản, quyết định, pipeline, agent (`agents.agents`, `agents.lab`), mức dùng rủi ro. Giao diện gọi mỗi 2 giây. Gọi vào cũng chạy bước ra quyết định. |
| POST | `/api/mode` | `{"mode": "analysis"\|"signal"\|"semi"\|"full", "emergency": bool?}` — chỉ `full` gửi lệnh |
| POST | `/api/agents/mode` | `{"id": "reversal-M15", "real": false}` — chuyển agent giữa tiền thật và nghiên cứu |
| POST | `/api/risk/unlock` | Mở khóa sụt giảm thủ công |
| GET | `/api/health` | Kiểm tra còn sống |
| GET | `/api/chart?timeframe=M15` | Nến, EMA, Bollinger, vùng giá, thẻ chiến lược cho biểu đồ |
| GET | `/api/journal` | Sổ lệnh + thống kê + bảng so sánh ý kiến Claude |

## Cài đặt

| Phương thức | Đường dẫn | Mục đích |
|---|---|---|
| GET/POST | `/api/settings/risk` | Đọc / lưu giới hạn rủi ro (xem [04](04-risk-and-safety.md)) |
| POST | `/api/settings/risk/default` | Gợi ý và lưu rủi ro theo vốn và ATR (về mức thử nghiệm nếu không đọc được MT5) |
| GET | `/api/settings/mt5` | Cài đặt MT5 đã lưu (không bao giờ trả mật khẩu) |
| POST | `/api/mt5/connect` | `{"terminalPath","server","login","password","symbol"}` — kết nối và lưu |
| GET/POST | `/api/settings/telegram` | `{"enabled","chatId","token"}` |
| POST | `/api/settings/telegram/test` | Gửi tin thử |
| GET/POST | `/api/settings/llm` | Bật/tắt ý kiến thứ hai của Claude; báo đường dẫn CLI đã tìm thấy |

## Họp hằng ngày & trưởng phòng

| Phương thức | Đường dẫn | Mục đích |
|---|---|---|
| GET | `/api/meeting` | `{status: {running, step, startedAt, events[], result}, history[], schedule}` |
| POST | `/api/meeting/run` | Họp ngay (`{"ok": false}` nếu đang họp) |
| GET | `/api/meetings?limit=20` | Nhật ký nhóm theo cuộc họp kèm tóm tắt và chip |
| GET | `/api/manager-log?limit=200&kind=` | Nhật ký phẳng; `kind` ∈ meeting, decision, change, improve, code, rollback, restart, arbitration |

## Backtest & mô hình

| Phương thức | Đường dẫn | Mục đích |
|---|---|---|
| POST | `/api/backtest` | `{"strategy":"auto"\|<id>, "timeframe","start","end","capital"}` |
| POST | `/api/backtest/compare` | So sánh các chế độ trong một giai đoạn |
| GET | `/api/backtest/latest` | Báo cáo đã lưu gần nhất (`data/backtest-latest.json`) |
| GET | `/api/models/latest` | Báo cáo huấn luyện ML gần nhất |
| POST | `/api/models/train` | `{"timeframe","bars"}` huấn luyện bộ LightGBM/XGBoost/HMM (cần MT5) |
| GET | `/api/models/signal` | Báo cáo và chế độ mô hình tín hiệu (meta) |
| POST | `/api/models/signal/train` | Huấn luyện mô hình tín hiệu |
| POST | `/api/settings/model` | `{"mode": "off"\|"shadow"\|"size"}` |

## Tĩnh

`GET /` trả `mockup/index.html`; `/js/*` và `/css/*` trả script và style của giao diện.

## Ví dụ

```powershell
curl http://127.0.0.1:8787/api/health
curl -X POST http://127.0.0.1:8787/api/agents/mode -H "Content-Type: application/json" -d "{\"id\":\"flag-M30\",\"real\":true}"
curl -X POST http://127.0.0.1:8787/api/mode -H "Content-Type: application/json" -d "{\"mode\":\"analysis\"}"
```

> CORS chỉ cho phép thêm `http://127.0.0.1:8765` / `localhost:8765`; giao diện được phục vụ cùng
> nguồn ở cổng 8787.
