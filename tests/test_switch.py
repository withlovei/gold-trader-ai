"""Real/research switch per agent + the new books: a real method book sends with its own magic and
the card's holding limit, a research book never sends, trail books ratchet with their own magic,
the dashboard view splits staff / lab by the switch. Fake MetaTrader fed with real M15 history."""
import json, sys, tempfile
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
R = json.load(open(SP + "/hist/M15.json")); T = [r[0] for r in R]


def frame(i):
    rows = [tuple(r[:5]) for r in R[i - 598: i + 1]] + [(T[i + 1],) + (R[i + 1][1],) * 4]
    return np.array(rows, dtype=dtype), T[i + 1] + 10


class Fake:
    TRADE_ACTION_DEAL = 1; TRADE_ACTION_SLTP = 6; ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1; ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0; ORDER_FILLING_IOC = 1; ORDER_FILLING_RETURN = 2; TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M15 = 15

    def __init__(s, rates, now):
        s.rates, s.now, s.orders, s.positions = rates, now, [], []

    def copy_rates_from_pos(s, sym, frame_, a, n): return s.rates
    def positions_get(s, symbol=None, ticket=None):
        return [p for p in s.positions if p.ticket == ticket] if ticket is not None else list(s.positions)
    def history_deals_get(s, a=None, b=None, position=None): return []
    def last_error(s): return (0, "")

    def order_send(s, req):
        s.orders.append(req)
        if req["action"] == s.TRADE_ACTION_SLTP:
            for p in s.positions:
                if p.ticket == req["position"]:
                    p.sl = req["sl"]
        elif "position" not in req:
            s.positions.append(NS(magic=req["magic"], time=s.now, type=req["type"], ticket=len(s.orders), volume=req["volume"],
                                  price_open=req["price"], sl=req["sl"], tp=req["tp"], comment=req["comment"], profit=0.0))
        else:
            s.positions = [p for p in s.positions if p.ticket != req["position"]]
        return NS(retcode=10009, comment="done", order=len(s.orders), price=req.get("price"), volume=req.get("volume"))


INFO = NS(trade_tick_size=0.001, trade_tick_value=0.1, volume_step=0.01, volume_min=0.01, volume_max=200, digits=3,
          filling_mode=1, spread=200, point=0.001, swap_mode=1, swap_long=-493.4, swap_short=0)
LIMITS = {"perTradePercent": 0.75, "dailyLossPercent": 2.5, "drawdownPercent": 30, "maxPositions": 14, "maxLossStreak": 4,
          "minRewardRatio": 1.5, "maxOpenRiskPercent": 30, "minLotPercent": 2}


def tick(fake):
    px = float(fake.rates["open"][-1]); return NS(bid=px, ask=px + 0.2, time=fake.now)


def step(fake, state, key):
    live._book_step(fake, state, key, live.EXTRA_BOOKS[key], "XAUUSDm", tick(fake), INFO, 10000.0, LIMITS, 0.0, 10000.0, 0, "")


def find(strategy_id, start):
    for i in range(start, 700, -1):
        rates, _ = frame(i)
        st = live._strategy_for(rates, T[i], 1.5, "M15", 900)
        card = next((c for c in st.get("catalog") or [] if c.get("id") == strategy_id), None)
        if card and card.get("confirmed") and card.get("side") in {"buy", "sell"}:
            return i
    raise AssertionError("no signal for " + strategy_id)


assert len(live.all_books()) == 16 and len({int(c["magic"]) for c in live.all_books().values()}) == 16
assert live.agent_real("flag-M30") is False and live.agent_real("flag-H1") is False, "new flag agents start in research"
assert live.agent_real("fakeout-M15") is True, "default must be real (user's choice)"

# 1. fixed-exit method (reversal: 8 bars) on real money -> order with own magic, book keeps 8 bars
i = find("reversal", len(R) - 200)
rates, now = frame(i); fake = Fake(rates, now); state = {"mode": "full"}
step(fake, state, "reversal-M15")
assert len(fake.orders) == 1, state["books"]["reversal-M15"]["last"]["reason"]
o = fake.orders[0]
assert o["magic"] == 260615 and o["tp"] > 0, o
assert state["books"]["reversal-M15"]["maxBars"] == 8, state["books"]["reversal-M15"]
print("1 reversal real: magic", o["magic"], "volume", o["volume"], "maxBars", state["books"]["reversal-M15"]["maxBars"])
# 8 bars later the time stop (8, not the trend 48) closes it
fake.rates, fake.now = frame(i + 9)
before = len(fake.orders); step(fake, state, "reversal-M15")
closes = [x for x in fake.orders[before:] if "position" in x]
assert len(closes) == 1 and closes[0]["magic"] == 260615 and closes[0]["comment"] == "GoldTrader het gio", fake.orders[before:]
print("  closed after 8 bars:", closes[0]["comment"])

# 2. switch to research -> same signal, no order, reason says research
print("  switch:", live.set_agent_real("reversal-M15", False))
assert live.agent_real("reversal-M15") is False
rates, now = frame(i); fake = Fake(rates, now); state = {"mode": "full"}
step(fake, state, "reversal-M15")
last = state["books"]["reversal-M15"]["last"]
assert not fake.orders and live.RESEARCH_NOTE in last["reason"] and last["signal"], last
print("2 research: no order |", last["reason"][:110])
assert live.set_agent_real("nope", True)["ok"] is False

# 3. trail method (momentum) -> no fixed TP, book manage=trail, stop ratchets with its own magic
i = find("momentum", len(R) - 200)
rates, now = frame(i); fake = Fake(rates, now); state = {"mode": "full"}
step(fake, state, "momentum-M15")
assert len(fake.orders) == 1 and fake.orders[0]["tp"] == 0.0 and fake.orders[0]["magic"] == 260621, fake.orders
book = state["books"]["momentum-M15"]
assert book["manage"] == "trail", book
journal_risk = abs(fake.orders[0]["price"] - fake.orders[0]["sl"])
journal.initial_risk = lambda ticket: journal_risk
moves = []
for k in range(1, 60):
    fake.rates, fake.now = frame(i + k)
    before = len(fake.orders)
    step(fake, state, "momentum-M15")
    moves += [x for x in fake.orders[before:]]
    if not fake.positions:
        break
assert all(x["magic"] == 260621 for x in moves), moves
print("3 momentum trail: orders after entry", [(x.get("comment") or "SLTP", round(x.get("sl", 0), 2)) for x in moves][:6])

# 4. dashboard view: reversal in the lab, the rest on the desk
st = live._strategy_for(frame(i)[0], T[i], 1.5, "M15", 900)
view = live._agents_view({"books": {}}, [], INFO, 10000.0, LIMITS, st)
staff = [row["id"] for row in view["agents"]]; lab = [row["id"] for row in view["lab"]]
assert "reversal-M15" in lab and "flag-M30" in lab and "flag-H1" in lab and "reversal-M15" not in staff and len(staff) == 13 and "trend-H4" in staff, (staff, lab)
assert all(row["alias"] for row in view["agents"]), [row["id"] for row in view["agents"] if not row["alias"]]
assert abs(view["agents"][0]["share"] - round(1 / 13, 4)) < 1e-9
print("4 view: staff", len(staff), "lab", lab)

# 5. main trend-M15 in research -> paper ids include trend
live.set_agent_real("trend-M15", False)
ids = tuple(dict.fromkeys([str((c.get("strategies") or ("",))[0]) for k, c in live.all_books().items() if str(c.get("timeframe")) == "M15" and not live.agent_real(k)]))
assert "trend" in ids and "reversal" in ids, ids
print("5 paper ids:", ids)
print("ALL SWITCH CHECKS PASSED")
