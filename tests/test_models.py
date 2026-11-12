import json
import sys
import tempfile
import threading
import time as _time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
import numpy as np

from services.api import journal, live, notify
from services.api import llm_judge as _llm; _llm.submit = lambda *a, **k: None; _llm.decide = lambda *a, **k: None  # never call the real CLI in tests
journal.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

SP = sys.argv[1]
rows = json.load(open(SP + "/hist/M30.json"))
dtype = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")]
SIGNAL = 1788881400
idx = next(i for i, r in enumerate(rows) if r[0] == SIGNAL)
base = [tuple(r[:5]) for r in rows[idx - 599: idx + 1]]
forming = (SIGNAL + 900, rows[idx + 1][1], rows[idx + 1][1], rows[idx + 1][1], rows[idx + 1][1])
RATES = np.array(base + [forming], dtype=dtype)


class FakeMT5:
    TRADE_ACTION_DEAL = 1; ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1; ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0; ORDER_FILLING_IOC = 1; ORDER_FILLING_RETURN = 2; TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M30 = 30; TIMEFRAME_M15 = 15

    def __init__(self, age, equity=10000.0, keep_positions=True, slow=0.0):
        self.age, self.equity, self.keep, self.slow = age, equity, keep_positions, slow
        self.orders, self.positions = [], []

    def account_info(self): return NS(equity=self.equity, balance=self.equity, margin_free=self.equity)
    def symbol_info_tick(self, symbol):
        px = float(RATES["open"][-1]); return NS(bid=px, ask=px + 0.2, time=SIGNAL + 900 + self.age)
    def symbol_info(self, symbol):
        return NS(trade_tick_size=0.001, trade_tick_value=0.1, volume_step=0.01, volume_min=0.01, volume_max=200, digits=3, filling_mode=1, spread=200)
    def copy_rates_from_pos(self, symbol, frame, start, count):
        if self.slow: _time.sleep(self.slow)
        return RATES
    def positions_get(self, symbol=None, ticket=None):
        if ticket is not None:
            return [p for p in self.positions if p.ticket == ticket]
        return list(self.positions)
    def history_deals_get(self, a=None, b=None, position=None):
        if position is None:
            return []
        return [d for d in getattr(self, "deals", []) if d.position_id == position]
    def last_error(self): return (0, "")
    def order_send(self, req):
        self.orders.append(req)
        if self.keep and "position" not in req:
            self.positions.append(NS(magic=req["magic"], time=SIGNAL + 900, type=req["type"], ticket=len(self.orders), volume=req["volume"], price_open=req["price"], sl=req["sl"], tp=req["tp"]))
        return NS(retcode=10009, comment="done", order=len(self.orders), price=req["price"] + 0.05, volume=req["volume"])


def setup(fake, state=None):
    tmp = Path(tempfile.mkdtemp()) / "runtime.json"
    tmp.write_text(json.dumps(state or {"mode": "full", "emergency": False}), encoding="utf-8")
    live.RUNTIME_PATH = tmp

    @contextmanager
    def terminal():
        with live_lock:
            yield fake
    live.open_terminal = terminal
    live._weekend_close = lambda: (False, None)
    live.regime_now = lambda closes: {"line": "HMM test", "veto": None, "block": ""}
    live.latest_report = lambda: {}
    return tmp


live_lock = threading.Lock()

# 1. many concurrent callers on a fresh signal -> exactly one order
fake = FakeMT5(age=10)
path = setup(fake)
threads = [threading.Thread(target=live.snapshot) for _ in range(6)]
[t.start() for t in threads]; [t.join() for t in threads]
deals = [o for o in fake.orders if "position" not in o]
per_book = {}
for o in deals: per_book[o["magic"]] = per_book.get(o["magic"], 0) + 1
print("1 concurrent callers -> orders per book (magic: count):", per_book)
# the fake returns the same bars for every frame, so the M30 book may also see a signal: one order per book at most
assert per_book.get(live.MAGIC) == 1 and all(v == 1 for v in per_book.values())
live.EXTRA_BOOKS = {}  # the remaining checks are about the main book; the M30 book has test_m30book.py

# 2. signal noticed 5 minutes late -> no order
fake = FakeMT5(age=300)
path = setup(fake)
out = live.snapshot()
print("2 late signal -> orders:", len(fake.orders), "|", out["decision"]["reason"][-110:])
assert not fake.orders and "Không vào lệnh trễ" in out["decision"]["reason"]

# 3. position vanished (e.g. instantly stopped out) -> still no second order for the same bar
fake = FakeMT5(age=10, keep_positions=False)
path = setup(fake)
live.snapshot()
state = json.loads(path.read_text(encoding="utf-8")); state["decision"].pop("candle")  # force re-decision
path.write_text(json.dumps(state), encoding="utf-8")
out = live.snapshot()
print("3 re-decision same bar -> orders:", len(fake.orders), "|", out["decision"]["reason"][-50:])
assert len(fake.orders) == 1

# 4. emergency stop pressed while a slow snapshot is running is not overwritten
fake = FakeMT5(age=10, slow=0.4)
path = setup(fake, {"mode": "analysis", "emergency": False})
t = threading.Thread(target=live.snapshot); t.start(); _time.sleep(0.1)
live.set_mode("", True); t.join()
print("4 emergency persisted:", json.loads(path.read_text(encoding="utf-8"))["emergency"])
assert json.loads(path.read_text(encoding="utf-8"))["emergency"] is True

# 5. drawdown lock: lock, auto-unlock once after 48h, second lock needs manual unlock
fake = FakeMT5(age=10, equity=6900.0)
path = setup(fake, {"mode": "full", "emergency": False, "peakEquity": 10000.0, "lastBar": SIGNAL, "decision": {"candle": "x", "scores": ["HMM 4 nến"], "points": "1", "reason": live.LIVE_MARK}})
out = live.snapshot()
print("5a locked:", out["drawdownLock"], [b for b in out["pipeline"]["steps"] if "Cổng rủi ro" in b["name"]][0]["value"])
assert out["drawdownLock"] and out["risk"] == "Đang chặn"
real_time = live.time.time
live.time.time = lambda: real_time() + 49 * 3600
out = live.snapshot()
st = json.loads(path.read_text(encoding="utf-8"))
print("5b after 49h:", out["drawdownLock"], "peak", st["peakEquity"], "autoUnlocks", st["autoUnlocks"])
assert not out["drawdownLock"] and st["peakEquity"] == 6900.0
fake.equity = 4800.0
out = live.snapshot()
live.time.time = lambda: real_time() + 200 * 3600
out = live.snapshot()
print("5c second hit, 150h later still locked:", out["drawdownLock"])
assert out["drawdownLock"]
live.unlock_drawdown()
out = live.snapshot()
print("5d after manual unlock:", out["drawdownLock"], "peak", json.loads(path.read_text(encoding="utf-8"))["peakEquity"])
assert not out["drawdownLock"]
live.time.time = real_time

# 6. sent flag survives a re-decision of the same candle; journal records fill + slippage
fake = FakeMT5(age=10)
path = setup(fake)
live.snapshot()
st = json.loads(path.read_text(encoding="utf-8")); st["decision"]["scores"] = []  # force a same-candle re-decision
path.write_text(json.dumps(st), encoding="utf-8")
out = live.snapshot()
print("6 history after re-decision: sent =", out["history"][0]["sent"], "| orders", len(fake.orders))
assert out["history"][0]["sent"] is True and len(fake.orders) == 1
rows = journal.summary()["rows"]
print("  journal:", rows[0]["status"], rows[0]["side"], "fill", rows[0]["fill"], "slippage", rows[0]["slippage"], "risk $", round(rows[0]["riskMoney"], 2))
assert rows[0]["status"] == "Đang mở" and abs(rows[0]["slippage"] - (0.05 if rows[0]["side"] == "Mua" else -0.05)) < 1e-6

# 7. broker closes it at the stop -> journal closes it with R and a Telegram text is built
pos = fake.positions.pop()
fake.deals = [
    NS(position_id=pos.ticket, entry=0, time=SIGNAL + 900, price=pos.price_open, profit=0.0, commission=-0.5, swap=0.0, reason=3, comment=""),
    NS(position_id=pos.ticket, entry=1, time=SIGNAL + 900 * 6, price=pos.sl, profit=-74.1, commission=-0.5, swap=0.0, reason=4, comment="[sl 4413.74]"),
]
sent_texts = []
notify.send = lambda text: sent_texts.append(text)
out = live.snapshot()
stats = journal.summary()["stats"]
print("7 closed:", stats["closed"], "net", stats["net"], "R", stats["totalR"], "| review:", [x for x in out["pipeline"]["steps"] if "Đối chiếu" in x["name"]][0]["value"])
assert stats["closed"] == 1 and stats["net"] == -75.1 and len(sent_texts) == 1
print("  telegram close text:"); print(sent_texts[0])
row = journal._connect().execute("SELECT * FROM trade_journal").fetchone()
print("  telegram open text:"); print(notify.order_text("XAUUSDm", "M30", "Theo xu hướng", dict(row), 10000.0, "Lý do mẫu."))
print("ALL AUTOPILOT CHECKS PASSED")

# 8. signal model: score is shown, and a low score halves the volume (never raises it)
from services.api import meta_model
for mode in ("shadow", "size"):
    meta_model.read_mode = lambda m=mode: m
    fake = FakeMT5(age=10)
    setup(fake)
    out = live.snapshot()
    m = out["decision"].get("model")
    vol = [o for o in fake.orders if "position" not in o][0]["volume"]
    print(f"8 mode={mode}: score={m['score']} threshold={m['threshold']} factor={m['factor']} volume={vol} | {out['decision']['reason'][-70:]}")
    if mode == "shadow":
        full_volume = vol
    else:
        expected = full_volume if not m["low"] else round(int(full_volume / 2 * 100) / 100, 2)
        assert m["factor"] == (0.5 if m["low"] else 1.0) and abs(vol - expected) <= 0.011, (vol, expected)
print("MODEL CHECKS PASSED")
