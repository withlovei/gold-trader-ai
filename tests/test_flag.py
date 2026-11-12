"""Bull flag agent on M30: research book paper-trades on its own frame (an M15 call never walks it),
real book sends with magic 260625, the measured target and the per-trade holding limit."""
import json, sqlite3, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
from services.api import journal, live, notify, shadow, settings_store
from services.api import llm_judge as _llm; _llm.submit = lambda *a, **k: None; _llm.decide = lambda *a, **k: None
tmp = Path(tempfile.mkdtemp())
journal.DB_PATH = tmp / "t.db"; shadow.DB_PATH = tmp / "t.db"; live.RUNTIME_PATH = tmp / "runtime.json"
settings_store.DB_PATH = tmp / "settings.db"
notify.send = lambda text: None
SP = sys.argv[1]
dtype = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")]
R = json.load(open(SP + "/hist/M30.json")); T = [r[0] for r in R]


def frame(i):
    rows = [tuple(r[:5]) for r in R[i - 598: i + 1]] + [(T[i + 1],) + (R[i + 1][1],) * 4]
    return np.array(rows, dtype=dtype), T[i + 1] + 10


class Fake:
    TRADE_ACTION_DEAL = 1; TRADE_ACTION_SLTP = 6; ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1; ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0; ORDER_FILLING_IOC = 1; ORDER_FILLING_RETURN = 2; TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M30 = 30

    def __init__(s, rates, now): s.rates, s.now, s.orders, s.positions = rates, now, [], []
    def copy_rates_from_pos(s, *a): return s.rates
    def positions_get(s, symbol=None, ticket=None): return list(s.positions)
    def history_deals_get(s, *a, **k): return []
    def last_error(s): return (0, "")

    def order_send(s, req):
        s.orders.append(req)
        if "position" not in req and req["action"] == s.TRADE_ACTION_DEAL:
            s.positions.append(NS(magic=req["magic"], time=s.now, type=req["type"], ticket=len(s.orders), volume=req["volume"],
                                  price_open=req["price"], sl=req["sl"], tp=req["tp"], comment=req["comment"], profit=0.0))
        return NS(retcode=10009, comment="done", order=len(s.orders), price=req.get("price"), volume=req.get("volume"))


INFO = NS(trade_tick_size=0.001, trade_tick_value=0.1, volume_step=0.01, volume_min=0.01, volume_max=200, digits=3,
          filling_mode=1, spread=200, point=0.001, swap_mode=1, swap_long=-493.4, swap_short=0)
LIMITS = {"perTradePercent": 0.75, "dailyLossPercent": 2.5, "drawdownPercent": 30, "maxPositions": 16, "maxLossStreak": 4,
          "minRewardRatio": 1.5, "maxOpenRiskPercent": 30, "minLotPercent": 2}
BOOK = live.EXTRA_BOOKS["flag-M30"]


def step(fake, state):
    px = float(fake.rates["open"][-1])
    live._book_step(fake, state, "flag-M30", BOOK, "XAUUSDm", NS(bid=px, ask=px + 0.2, time=fake.now), INFO, 10000.0, LIMITS, 0.0, 10000.0, 0, "")


sig = None
for i in range(len(R) - 60, 800, -1):
    rates, _ = frame(i)
    st = live._strategy_for(rates, T[i], 1.5, "M30", 1800)
    card = next((c for c in st.get("catalog") or [] if c.get("id") == "flag"), None)
    if card and card.get("confirmed"):
        sig = (i, card); break
assert sig, "no flag signal found"
i, card = sig
print("signal", T[i], card["summary"][:90], "| maxBars", card["maxBars"], "| take", card["takeProfit"])
assert card["side"] == "buy" and card["takeProfit"] > card["entry"] and 24 <= card["maxBars"] <= 200

# 1. research (default): no order, one paper row on the M30 frame
assert live.agent_real("flag-M30") is False
rates, now = frame(i); fake = Fake(rates, now); state = {"mode": "full"}
step(fake, state)
assert not fake.orders
rows = [dict(r) for r in sqlite3.connect(shadow.DB_PATH).execute("SELECT strategy, status, frame_seconds, max_bars, take FROM shadow_trades").fetchall()] if False else None
con = sqlite3.connect(shadow.DB_PATH); con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute("SELECT * FROM shadow_trades")]
assert len(rows) == 1 and rows[0]["strategy"] == "flag" and rows[0]["frame_seconds"] == 1800 and rows[0]["max_bars"] == card["maxBars"], rows
print("1 research: paper row", {k: rows[0][k] for k in ("strategy", "frame_seconds", "max_bars", "status")})

# 2. an M15 call must not walk the M30 paper row
before = dict(rows[0])
shadow.process(("reentry",), [], [tuple(r[1:5]) for r in R[i - 50: i + 40]], [r[0] for r in R[i - 50: i + 40]], 900,
               NS(bid=1.0, ask=1.2), 0.2, 0.0, 0.0)
after = dict(con.execute("SELECT * FROM shadow_trades").fetchone())
assert after["bars_held"] == before["bars_held"] and after["status"] == "open", (before, after)
print("2 M15 call left the M30 row alone")

# 3. later M30 bars close it on its own rules
for k in range(1, 210):
    rates, now = frame(i + k); fake.rates, fake.now = rates, now
    step(fake, state)
    row = dict(con.execute("SELECT * FROM shadow_trades").fetchone())
    if row["status"] == "closed":
        break
print("3 paper trade closed:", row["status"], row["reason"], "R", row["r"], "after", row["bars_held"], "bars")
assert row["status"] == "closed"

# 4. real money: order with own magic, measured target, per-trade holding limit kept by the book
live.set_agent_real("flag-M30", True)
rates, now = frame(i); fake = Fake(rates, now); state = {"mode": "full"}
step(fake, state)
assert len(fake.orders) == 1, state["books"]["flag-M30"]["last"]["reason"]
o = fake.orders[0]
assert o["magic"] == 260625 and o["tp"] > o["price"] > o["sl"], o
assert state["books"]["flag-M30"]["maxBars"] == card["maxBars"], state["books"]["flag-M30"]
print("4 real: magic", o["magic"], "tp/sl R", round((o["tp"] - o["price"]) / (o["price"] - o["sl"]), 2), "maxBars", state["books"]["flag-M30"]["maxBars"])
print("ALL FLAG CHECKS PASSED")
