# GoldTrader AI

[English](README.md) · **Tiếng Việt**

Phòng giao dịch tự động nhiều agent cho **vàng (XAUUSD)** trên **MetaTrader 5**. Mười sáu "agent"
theo luật (mỗi agent là một phương pháp, có mã sổ riêng, khung thời gian riêng và vị thế riêng)
giao dịch dưới sự điều phối của **trưởng phòng**: phân xử tín hiệu và giữ giới hạn rủi ro chung cho
cả tài khoản. Mỗi ngày trưởng phòng gọi **Claude CLI** để đánh giá từng agent, quyết định ai giao
dịch tiền thật, ai xuống bàn giấy (chỉ ghi lệnh giấy), và có thể sửa mã nguồn của agent cần cải
tiến.

> ⚠️ **Không phải lời khuyên đầu tư. Giao dịch có đòn bẩy có thể mất nhiều hơn số tiền đã nạp.**
> Đây là phần mềm nghiên cứu. Hãy chạy trên **tài khoản demo** trước. Kết quả kiểm thử quá khứ
> không đảm bảo tương lai; đa số agent trong repo có lợi thế mỏng hoặc âm khi kiểm thử (xem
> [docs/vi/03-agents-and-strategies.md](docs/vi/03-agents-and-strategies.md)). Bạn tự chịu trách
> nhiệm với số tiền của mình.

## Tính năng

- **16 agent**, mỗi agent một phương pháp riêng (theo xu hướng, hồi giá, phá vùng, đảo chiều, đi
  ngang, vào lại, đa khung, động lượng, bùng nổ biến động, phá vỡ thất bại, cờ tăng, …) và một mã
  sổ MT5 riêng nên mọi lệnh đều truy được về agent.
- **Công tắc tiền thật / nghiên cứu cho từng agent.** Agent nghiên cứu chỉ ghi lệnh giấy để đo hiệu
  quả mà không rủi ro.
- **Trưởng phòng (agent tổng):** nhiều agent báo tín hiệu cùng một nến thì chỉ agent xếp cao nhất
  được vào lệnh; không mở mua và bán cùng lúc; giới hạn rủi ro chung (mỗi lệnh, lỗ ngày, khóa sụt
  giảm, tổng rủi ro đang mở, chuỗi thua).
- **Họp hằng ngày (22:10 UTC, thứ Hai–thứ Sáu):** Claude CLI xem xét mọi agent, quyết định tiền
  thật hay bàn giấy; có thể sửa mã nguồn agent; mã được sao lưu, chạy thử và khôi phục nếu lỗi. Mọi
  bước ghi vào nhật ký theo từng cuộc họp.
- **Backtest walk-forward trung thực** (chọn 2022–2024, kiểm tra 2025–2026) có chênh lệch giá, phí
  qua đêm và quy tắc khối lượng như sàn; kèm kịch bản nghiên cứu ý tưởng mới.
- **Giao diện** (chạy cục bộ): phòng làm việc trực quan với từng bàn, sao theo lợi nhuận, sổ lệnh,
  biểu đồ, rủi ro, kiểm thử, mô hình, cài đặt.
- **Thông báo Telegram** (tin ngắn cho lệnh vào/đóng) và **ý kiến thứ hai của Claude** cho mỗi tín
  hiệu (tùy chọn).
- Bí mật (mật khẩu MT5, token Telegram) được mã hóa bằng Windows DPAPI, không rời khỏi máy; thư mục
  dữ liệu bị git bỏ qua.

## Yêu cầu

- Windows 10/11 (gói Python `MetaTrader5` và DPAPI chỉ chạy trên Windows)
- Python 3.13 (3.11+ có thể chạy)
- MetaTrader 5 đã cài và đăng nhập tài khoản sàn (phát triển trên Exness Standard, mã `XAUUSDm`)
- Tùy chọn: Claude CLI (cho cuộc họp hằng ngày và ý kiến thứ hai), bot Telegram

## Bắt đầu nhanh

```powershell
git clone https://github.com/withlovei/gold-trader-ai.git
cd gold-trader-ai
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
scripts\start.bat          # chạy server và mở http://127.0.0.1:8787/
```

Trong giao diện: **Cài đặt → MT5** (đường dẫn terminal, máy chủ, tài khoản, mật khẩu, mã) →
**Rủi ro** (dùng số dư demo nhỏ) → chọn chế độ. Hướng dẫn đầy đủ:
[docs/vi/01-getting-started.md](docs/vi/01-getting-started.md).

## Tài liệu

| Chủ đề | English | Tiếng Việt |
|---|---|---|
| Bắt đầu | [01](docs/en/01-getting-started.md) | [01](docs/vi/01-getting-started.md) |
| Kiến trúc | [02](docs/en/02-architecture.md) | [02](docs/vi/02-architecture.md) |
| Agent & chiến lược | [03](docs/en/03-agents-and-strategies.md) | [03](docs/vi/03-agents-and-strategies.md) |
| Rủi ro & an toàn | [04](docs/en/04-risk-and-safety.md) | [04](docs/vi/04-risk-and-safety.md) |
| Họp hằng ngày (phòng tự cải thiện) | [05](docs/en/05-daily-meeting.md) | [05](docs/vi/05-daily-meeting.md) |
| API HTTP | [06](docs/en/06-api.md) | [06](docs/vi/06-api.md) |
| Backtest & nghiên cứu | [07](docs/en/07-backtest-and-research.md) | [07](docs/vi/07-backtest-and-research.md) |
| Cấu hình & dữ liệu | [08](docs/en/08-configuration.md) | [08](docs/vi/08-configuration.md) |
| Xử lý sự cố | [09](docs/en/09-troubleshooting.md) | [09](docs/vi/09-troubleshooting.md) |
| Yêu cầu hệ thống & hiện trạng | [req](docs/en/req.md) | [req](docs/vi/req.md) |

Hướng dẫn cho người đóng góp / trợ lý AI: [CLAUDE.md](CLAUDE.md).

## Cấu trúc dự án

```
services/api/         ứng dụng FastAPI, vòng giao dịch thật, agent, backtest, sổ lệnh, cuộc họp
services/api/methods/ các phương pháp nghiên cứu (mỗi agent một module) + khung chung
mockup/               index.html + css/ + js/ (giao diện; tiếng Việt và tiếng Anh)
scripts/              start.bat / start.ps1, tải lịch sử nến
tests/                test hồi quy (MetaTrader giả cấp bằng lịch sử thật)
docs/                 tài liệu (en / vi)
data/                 dữ liệu chạy (git bỏ qua): app.db, nến, mô hình, bản sao lưu, biên bản họp
```

## Miễn trừ

Tên agent (Raschke, Seykota, Connors, Darvas, …) chỉ là nhãn mượn từ các nhà giao dịch nổi tiếng
để mô tả phong cách của phương pháp. Dự án này **không liên kết, không được bảo trợ và không phái
sinh từ công trình của** bất kỳ ai trong số đó.

## Giấy phép

[MIT](LICENSE). Mã nghiên cứu, không bảo hành; xem phần miễn trừ ở trên.
