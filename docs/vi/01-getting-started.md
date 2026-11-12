# 1. Bắt đầu

[English](../en/01-getting-started.md) · [Mục lục tài liệu](../README.md)

Hướng dẫn này đưa bạn từ một máy Windows sạch đến phòng giao dịch chạy trên **tài khoản demo**.

> Làm mọi bước dưới đây trên tài khoản **demo** trước. Chỉ cân nhắc tài khoản thật sau nhiều tuần
> chạy demo mà bạn hiểu rõ kết quả.

## 1.1 Yêu cầu

| Mục | Ghi chú |
|---|---|
| Windows 10/11 | Bắt buộc: gói `MetaTrader5` và kho bí mật DPAPI chỉ chạy trên Windows. |
| Python 3.13 | 3.11+ có thể chạy. Tải ở python.org hoặc `winget install Python.Python.3.13`. |
| MetaTrader 5 | Cài terminal của sàn. Phát triển trên **Exness** (tài khoản Standard, mã `XAUUSDm`). |
| Tài khoản hedging | **Bắt buộc.** Các agent giữ lệnh ngược chiều cùng lúc; tài khoản netting sẽ gộp chúng. Tài khoản Exness là hedging. |
| Internet | Giao diện tải Tailwind, Lightweight Charts và Google Fonts từ CDN. |
| Claude CLI (tùy chọn) | Cho cuộc họp hằng ngày và ý kiến thứ hai của Claude. Xem §1.6. |
| Bot Telegram (tùy chọn) | Thông báo lệnh vào/đóng. Xem §1.7. |

Phải cho phép giao dịch tự động trong MT5: **Tools → Options → Expert Advisors → Allow algorithmic
trading**, và nút **Algo Trading** trên thanh công cụ phải bật (màu xanh).

## 1.2 Cài đặt

```powershell
git clone https://github.com/withlovei/gold-trader-ai.git
cd gold-trader-ai
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 1.3 Chạy

```powershell
scripts\start.bat
```

Lệnh này chạy `uvicorn services.api.main:app` tại `127.0.0.1:8787` và mở giao diện ở
<http://127.0.0.1:8787/>. Server chỉ nghe trên máy bạn (không mở ra mạng).

Chạy tay nếu muốn:

```powershell
.venv\Scripts\python.exe -m uvicorn services.api.main:app --host 127.0.0.1 --port 8787
```

Lần chạy đầu tạo thư mục `data/` (cơ sở dữ liệu SQLite, trạng thái chạy). Với **bản cài mới, chế
độ là "Chỉ xem": không giao dịch gì** cho đến khi bạn đổi ở §1.5.

## 1.4 Kết nối MetaTrader 5

1. Mở MT5, đăng nhập tài khoản **demo** ít nhất một lần.
2. Trong giao diện vào **Cài đặt** → MetaTrader 5:
   - *Đường dẫn phần mềm* — đường dẫn `terminal64.exe` (mặc định `C:\Program Files\MetaTrader 5\terminal64.exe`)
   - *Máy chủ* — tên máy chủ của sàn đúng như MT5 hiển thị (ví dụ `Exness-MT5Trial…`)
   - *Số tài khoản* — số tài khoản của bạn
   - *Mật khẩu* — mật khẩu tài khoản (mã hóa bằng Windows DPAPI trong `data/app.db`; không bao giờ
     xuất hiện trong repo hay log)
   - *Mã giao dịch* — `XAUUSDm` (Exness Standard) hoặc `XAUUSD`
3. Bấm kết nối. Thanh trên cùng phải hiện **MT5** màu xanh và có giá trực tiếp.

## 1.5 Đặt rủi ro, rà soát agent, chọn chế độ

1. Màn hình **Rủi ro**. Mặc định thận trọng (0,5% mỗi lệnh, lỗ ngày 2%, sụt giảm 10%, 2 vị thế).
   Với 16 agent bạn sẽ cần *số vị thế tối đa* và *rủi ro mở tối đa* cao hơn; với số dư nhỏ hãy đặt
   *giới hạn lot tối thiểu* (`minLotPercent`) để lệnh 0,01 lot không bị chặn hết. Xem
   [04-risk-and-safety.md](04-risk-and-safety.md). **Bắt đầu nhỏ.**
2. **Phòng giao dịch** → *Quản lý agent*. **Mặc định mọi agent trừ hai agent cờ tăng đều ở tiền
   thật.** Đa số agent có lợi thế kiểm thử mỏng hoặc âm. Hãy chuyển agent bạn chưa tin sang
   *Nghiên cứu* (chỉ ghi lệnh giấy). Bộ khởi đầu thận trọng là các agent có walk-forward dương:
   `trend-M15`, `pullback-M15`, `trend-M30`, `trend-H4`, `flag-M30`. Xem
   [03-agents-and-strategies.md](03-agents-and-strategies.md).
3. Thanh bên **Chế độ**:
   - *Chỉ xem* — chỉ phân tích, không gửi lệnh (mặc định lần chạy đầu)
   - *Tín hiệu* — hiện tín hiệu
   - *Duyệt tay* — duyệt thủ công
   - *Tự động* — **chế độ duy nhất gửi lệnh**; chạy trên server kể cả khi đóng trình duyệt.
4. Xem vài phiên ở *Chỉ xem* trước, rồi chuyển *Tự động* trên tài khoản demo.

Nút **Dừng khẩn cấp** chặn mọi lệnh mới ngay lập tức.

## 1.6 Claude CLI (tùy chọn)

Cần cho [cuộc họp hằng ngày](05-daily-meeting.md) và ý kiến thứ hai cho từng tín hiệu.

1. Cài Claude Code (<https://claude.com/claude-code>) và đăng nhập một lần (`claude`).
2. GoldTrader tìm file chạy theo thứ tự: biến môi trường `CLAUDE_CLI` → `PATH` → bản mới nhất ở
   `~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe`.
3. **Cài đặt → Claude** hiện đường dẫn đã tìm thấy và công tắc bật/tắt.

Lượt dùng tính vào gói Claude của bạn. Nếu thiếu CLI hoặc quá giờ, giao dịch vẫn chạy theo luật cố
định (không có ý kiến không phải là phủ quyết).

## 1.7 Telegram (tùy chọn)

1. Trên Telegram chat với **@BotFather**, `/newbot`, sao chép mã bot (token).
2. Gửi một tin bất kỳ cho bot (hoặc thêm bot vào nhóm), rồi lấy chat id
   (ví dụ qua `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. **Cài đặt → Telegram**: dán token và chat id, bật, bấm *Gửi tin thử*.

Token được lưu mã hóa. Tin nhắn ngắn gọn: lệnh vào (chiều, khối lượng, giá, SL/TP, rủi ro, agent),
lệnh đóng (kết quả, R, lý do), cộng tóm tắt cuộc họp hằng ngày.

## 1.8 Tùy chọn: lịch sử nến và test

```powershell
.venv\Scripts\python.exe scripts\fetch_history.py data\research XAUUSDm   # MT5 phải đang chạy
.venv\Scripts\python.exe tests\run_all.py data\research
```

Xem [07-backtest-and-research.md](07-backtest-and-research.md). Màn hình **Kiểm thử** chạy
backtest ngay trong giao diện (tự lấy lịch sử từ MT5).

## 1.9 Danh sách kiểm tra trước khi tin tưởng với tiền thật

- [ ] Ít nhất vài tuần chạy demo ở *Tự động*, đã xem lại sổ lệnh.
- [ ] Bạn hiểu lợi thế kiểm thử và mức sụt giảm tệ nhất của từng agent tiền thật.
- [ ] Rủi ro mỗi lệnh, lỗ ngày và khóa sụt giảm đặt ở mức bạn chịu được.
- [ ] Tài khoản hedging, đã cho phép giao dịch tự động, hiểu quy tắc khối lượng `XAUUSDm` (tối thiểu 0,01 lot).
- [ ] Bật Telegram để thấy mọi lệnh.
- [ ] Biết nút dừng khẩn cấp ở đâu.

Gặp sự cố? Xem [09-troubleshooting.md](09-troubleshooting.md).
