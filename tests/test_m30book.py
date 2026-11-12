"""Live M30 book: order with own magic at half size, one position per book, 48-bar time stop,
pullback refused, M15 book unaffected. Fake MetaTrader fed with real history."""
import json, sys, tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
from services.api import journal, live, notify, shadow
from services.api import llm_judge as _llm; _llm.submit = lambda *a, **k: None; _llm.decide = lambda *a, **k: None  # never call the real CLI in tests
tmpdb = Path(tempfile.mkdtemp()) / "t.db"
journal.DB_PATH = tmpdb; shadow.DB_PATH = tmpdb; live.RUNTIME_PATH = tmpdb.with_name("runtime.json")
notify.send = lambda text: print("   [tele]", text.splitlines()[0])

SP = sys.argv[1]
dtype = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")]
R30 = json.load(open(SP + "/hist/M30.json")); t30 = [r[0] for r in R30]
BOOK = live.EXTRA_BOOKS["trend-M30"]; MAGIC30 = int(BOOK["magic"])
assert MAGIC30 != live.MAGIC and float(BOOK["factor"]) == 1.0


def frame(i):
    """M30 rates as MetaTrader returns them right after bar i closed: bar i+1 is forming."""
    rows = [tuple(r[:5]) for r in R30[i - 598: i + 1]] + [(t30[i + 1],) + (R30[i + 1][1],) * 4]
    return np.array(rows, dtype=dtype), t30[i + 1] + 10


class Fake:
    TRADE_ACTION_DEAL = 1; TRADE_ACTION_SLTP = 6; ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1; ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0; ORDER_FILLING_IOC = 1; ORDER_FILLING_RETURN = 2; TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M30 = 30; TIMEFRAME_M15 = 15

    def __init__(s, m30, now):
        s.m30, s.now, s.orders, s.positions = m30, now, [], []

    def copy_rates_from_pos(s, sym, frame_, a, n): return s.m30
    def positions_get(s, symbol=None, ticket=None):
        return [p for p in s.positions if p.ticket == ticket] if ticket is not None else list(s.positions)
    def history_deals_get(s, a=None, b=None, position=None): return []
    def last_error(s): return (0, "")

    def order_send(s, req):
        s.orders.append(req)
        if "position" not in req:
            s.positions.append(NS(magic=req["magic"], time=s.now, type=req["type"], ticket=len(s.orders), volume=req["volume"],
                                  price_open=req["price"], sl=req["sl"], tp=req["tp"], comment=req["comment"]))
        else:
            s.positions = [p for p in s.positions if p.ticket != req["position"]]
        return NS(retcode=10009, comment="done", order=len(s.orders), price=req["price"], volume=req["volume"])


INFO = NS(trade_tick_size=0.001, trade_tick_value=0.1, volume_step=0.01, volume_min=0.01, volume_max=200, digits=3,
          filling_mode=1, spread=200, point=0.001, swap_mode=1, swap_long=-493.4, swap_short=0)
LIMITS = {"perTradePercent": 0.75, "dailyLossPercent": 2.5, "drawdownPercent": 20, "maxPositions": 2, "maxLossStreak": 4, "minRewardRatio": 1.5}


def tick(fake):
    px = float(fake.m30["open"][-1]); return NS(bid=px, ask=px + 0.2, time=fake.now)


def step(fake, state):
    live._book_step(fake, state, "trend-M30", BOOK, "XAUUSDm", tick(fake), INFO, 10000.0, LIMITS, 0.0, 10000.0, 0, "")


# find a confirmed M30 trend signal and a bar where the selector picks pullback
trend_i = pull_i = None
for i in range(len(R30) - 120, 700, -1):
    m30, now = frame(i)
    st = live._strategy_for(m30, t30[i], 1.5, "M30", 1800)
    if trend_i is None and st.get("id") == "trend" and st.get("confirmed") and st.get("live"):
        trend_i = i
    if pull_i is None and st.get("id") == "pullback" and st.get("confirmed") and st.get("live"):
        pull_i = i
    if trend_i and pull_i:
        break
print("trend signal bar", t30[trend_i], "| pullback bar", t30[pull_i])

# 1. pullback picked on M30 -> refused
m30, now = frame(pull_i); fake = Fake(m30, now); state = {"mode": "full"}
step(fake, state)
assert not fake.orders, fake.orders
print("1 pullback refused:", state["books"]["trend-M30"]["last"]["reason"][:90])

# 2. trend signal -> one order, own magic, full size (agent share 1/3 x 3), fixed 2R target
m30, now = frame(trend_i); fake = Fake(m30, now); state = {"mode": "full"}
step(fake, state)
assert len(fake.orders) == 1, fake.orders
o = fake.orders[0]; dist = abs(o["price"] - o["sl"])
full = 10000 * 0.0075 / (dist / 0.001 * 0.1)
print(f"2 order magic={o['magic']} volume={o['volume']} (full {full:.3f}, half {full/2:.3f}) tp/sl={abs(o['tp']-o['price'])/dist:.2f}R comment={o['comment']}")
assert o["magic"] == MAGIC30 and o["volume"] <= full + 0.001 and o["volume"] >= full - 0.011
assert abs(abs(o["tp"] - o["price"]) / dist - 2.0) < 0.02 and o["comment"].endswith("M30")
rows = journal.summary()["rows"]; assert rows[0]["strategy"] == "Theo xu hướng M30", rows[0]["strategy"]
print("  journal:", rows[0]["strategy"])

# 3. same bar again -> no second order; an M15 position does not block the M30 book
step(fake, state); assert len(fake.orders) == 1
print("3 same bar -> still 1 order")

# 4. 48 M30 bars later the time stop closes it (book magic only)
p = fake.positions[0]
j = trend_i + 49
fake.m30, fake.now = frame(j)[0], frame(j)[1]
fake.positions.append(NS(magic=live.MAGIC, time=p.time, type=0, ticket=999, volume=0.01, price_open=p.price_open, sl=p.sl, tp=0.0, comment="GoldTrader trend"))
before = len(fake.orders); step(fake, state)
closes = [x for x in fake.orders[before:] if "position" in x]
print("4 time stop:", [(x["position"], x["magic"], x["comment"]) for x in closes])
assert len(closes) == 1 and closes[0]["position"] == p.ticket and closes[0]["magic"] == MAGIC30
assert any(q.ticket == 999 for q in fake.positions), "M15 position must stay"
print("ALL M30 BOOK CHECKS PASSED")
