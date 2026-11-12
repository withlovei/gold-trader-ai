# 7. Backtest & nghiên cứu

[English](../en/07-backtest-and-research.md) · [Mục lục tài liệu](../README.md)

## 7.1 Backtest trong giao diện

Màn hình **Kiểm thử**: chọn chiến lược (`auto` = bản sao của bộ chọn chính, một chiến lược/agent, hoặc
chế độ nhiều agent), khung thời gian, ngày và vốn ban đầu, rồi chạy. Server lấy lịch sử từ terminal
MT5 của bạn (hoặc kho nến cục bộ) và phát lại qua cùng đường mã như giao dịch thật:

- chỉ quyết định trên nến đã đóng, khớp ở giá mở nến kế, **chênh lệch giá** lúc vào, **phí qua
  đêm** lúc rollover (21:00), hoa hồng, khối lượng tối thiểu/bước, `minLotPercent`;
- mọi cổng như bản thật: giờ cấm (18–24 UTC), lỗ ngày, khóa sụt giảm, chuỗi thua từng agent, giới
  hạn rủi ro, thoát lệnh (cắt lỗ, mục tiêu, hết giờ, cắt lỗ bám);
- biểu đồ nến kèm dấu lệnh và phát lại; chỉ số (lãi ròng, PF, tỷ lệ thắng, sụt giảm tối đa, Sharpe,
  kỳ vọng, R, chuỗi); thống kê từng agent.

Báo cáo lưu ở `data/backtest-latest.json`. Danh sách lệnh trong báo cáo bị cắt ngắn; danh sách đầy
đủ là `chartTrades`.

## 7.2 Bài kiểm thử trung thực (walk-forward)

- **Chọn** tham số / phương pháp trên 2022-09 … 2024-12, **kiểm tra** trên 2025-01 … 2026-11.
- Chênh lệch giá 0,2 đơn vị giá, $10.000, thử gấp đôi chênh lệch, và kết quả từng năm.
- Một phương pháp chỉ đủ điều kiện dùng tiền thật khi **cả hai** giai đoạn ≥ +0,05R mỗi lệnh với
  PF ≥ 1,10 (`methods.verdict`), và chỉ khi bạn đồng ý.
- Lưu ý: lịch sử M15 từ MT5 bị giới hạn ~99.000 nến (≈ 4 năm); M5 ≈ 1,5 năm.
- Kết quả quá khứ không bao giờ đảm bảo tương lai. Lợi thế ở đây mỏng (+0,1R mỗi lệnh) và phụ thuộc
  giai đoạn thị trường.

## 7.3 Lịch sử đã lưu cho script và test

```powershell
.venv\Scripts\python.exe scripts\fetch_history.py data\research XAUUSDm
```

ghi `data/research/hist/{M5,M15,M30,H1,H4}.json` (mỗi dòng `[time, o, h, l, c, spread]`). Sau đó:

```powershell
.venv\Scripts\python.exe tests\run_all.py data\research
```

## 7.4 Đánh giá một phương pháp mới (công thức)

```python
import json, sys
from datetime import timezone
sys.path.insert(0, ".")
from services.api import backtest as b
from services.api.settings_store import read_risk

rows = json.load(open("data/research/hist/M30.json"))
market = {"spread": 0.2, "tickSize": 0.001, "tickValue": 0.1, "volumeMin": 0.01, "volumeMax": 200.0,
          "volumeStep": 0.01, "swapLong": -493.4, "swapShort": 0.0, "swapMode": 1, "point": 0.001}
limits = dict(read_risk()); limits.update({"drawdownPercent": 100.0, "dailyLossPercent": 100.0, "maxLossStreak": 1000})
sd, ed = b._parse_day("2025-01-01"), b._parse_day("2026-11-06")
lo = int(b._warmup(sd, "M30").replace(tzinfo=timezone.utc).timestamp())
hi = int(ed.replace(tzinfo=timezone.utc).timestamp()) + 86400
sel = [r for r in rows if lo <= r[0] < hi]
report = b._simulate([tuple(map(float, r[1:5])) for r in sel], [int(r[0]) for r in sel],
                     market, "flag", "M30", sd, ed, 10000.0, limits)
trades = report["chartTrades"]          # danh sách đầy đủ; mỗi lệnh có "r", "openedTs", "agent", ...
```

Chạy cho cả hai giai đoạn, so R trung bình và hệ số lợi nhuận, kiểm tra kết quả từng năm và một lần
chạy với chênh lệch giá gấp đôi, rồi lưu số liệu vào `methods.TESTED` (khóa kiểu `"flag-H1"` khi cùng
phương pháp được đo trên khung khác).

## 7.5 Nghiên cứu đã tìm ra gì (tóm tắt)

- Chiến lược đánh ngược / đi ngang thua trên vàng suốt 2022–2026; hồi về EMA theo xu hướng kèm bộ lọc
  biến động (ATR14 ≥ ATR100) và không khớp lệnh 18–24 UTC là lợi thế bền duy nhất.
- Cắt lỗ bám kiểu chandelier (3 ATR sau 1R) làm R mỗi lệnh của xu hướng M15 gần gấp đôi.
- Chia khối lượng theo mô hình meta, chặn tin tức, bộ lọc ADX / hiệu suất, vào lệnh giới hạn, dời hòa
  vốn, phân bổ "theo phong độ gần đây": không cái nào cải thiện kết quả walk-forward.
- Mẫu nến (cả 61 mẫu TA-Lib) không có lợi thế ổn định; mẫu hình giá: chỉ cờ tăng M30/H1 trụ được
  (chỉ mua, lưu ý xu hướng nền).
- Chạy nhiều agent tương quan phần lớn chỉ là đòn bẩy trên cùng một nhịp giá; tăng rủi ro mỗi lệnh
  của một bộ chọn thắng nhiều biến thể nhiều agent ở cùng mức sụt giảm. Phòng nhiều agent là nền
  tảng nghiên cứu và theo dõi, không phải cải tiến đã được chứng minh.
- Phát lại backtest của mọi agent trên M5 và hủy lệnh sớm bằng kiểm tra mỗi 5 phút **không** thắng
  cách thoát lệnh hiện tại.

## 7.6 ML tùy chọn

`POST /api/models/train` (hoặc màn hình **Mô hình**) huấn luyện LightGBM, XGBoost, GARCH và bộ lọc
trạng thái HMM trên các nến gần đây. Mô hình tín hiệu (meta) chấm điểm tín hiệu xu hướng; chế độ
`off`, `shadow` (chỉ ghi, khuyến nghị) và `size` (giảm nửa khối lượng khi điểm thấp; không bao giờ
bỏ lệnh hay tăng khối lượng). Mô hình ghi vào `data/models/`, không thuộc repo.
