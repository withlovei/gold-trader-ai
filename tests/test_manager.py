"""Trưởng phòng: two agents signal the same side on one closed bar -> only the best ranked one sends;
a trade already open on that side blocks every new one on it; the dashboard line tells why."""
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
exec(open(SP + "/test_switch.py", encoding="utf-8").read().split("class Fake:")[1].join(["class Fake:", ""]).split("INFO = ")[0]) if False else None


def frame(i):
    rows = [tuple(r[:5]) for r in R[i - 598: i + 1]] + [(T[i + 1],) + (R[i + 1][1],) * 4]
    return np.array(rows, dtype=dtype), T[i + 1] + 10


class Fake:
    TRADE_ACTION_DEAL = 1; TRADE_ACTION_SLTP = 6; ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1; ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0; ORDER_FILLING_IOC = 1; ORDER_FILLING_RETURN = 2; TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M15 = 15

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
LIMITS = {"perTradePercent": 0.75, "dailyLossPercent": 2.5, "drawdownPercent": 30, "maxPositions": 14, "maxLossStreak": 4,
          "minRewardRatio": 1.5, "maxOpenRiskPercent": 30, "minLotPercent": 2}
# only M15 extra books on real money (the fake serves M15 bars only); main trend-M15 is decided in _snapshot
for key, config in live.all_books().items():
    live.set_agent_real(key, str(config["timeframe"]) == "M15" and key != "trend-M15")
M15 = {key: str(c["strategies"][0]) for key, c in live.EXTRA_BOOKS.items() if c["timeframe"] == "M15"}

found = None
for i in range(len(R) - 60, len(R) - 4000, -1):
    st = live._strategy_for(frame(i)[0], T[i], 1.5, "M15", 900)
    cards = {c["id"]: c for c in st.get("catalog") or [] if isinstance(c, dict)}
    sides = {}
    for key, sid in M15.items():
        c = cards.get(sid)
        if c and c.get("confirmed") and c.get("side") in {"buy", "sell"}:
            sides.setdefault(c["side"], []).append(key)
    pair = next((v for v in sides.values() if len(v) >= 2), None)
    if pair:
        found = (i, pair); break
assert found, "no bar with two agents on one side"
i, pair = found
print("bar", T[i], "agents same side:", pair)


def run(fake, state):
    tick = NS(bid=float(fake.rates["open"][-1]), ask=float(fake.rates["open"][-1]) + 0.2, time=fake.now)
    live._manager_review(fake, state, "XAUUSDm", tick, LIMITS, list(fake.positions))
    for key in live.EXTRA_BOOKS:
        if live.agent_real(key):
            live._book_step(fake, state, key, live.EXTRA_BOOKS[key], "XAUUSDm", tick, INFO, 10000.0, LIMITS, 0.0, 10000.0, 0, "")


# 1. same bar, same side -> exactly one order, from the best ranked agent
rates, now = frame(i); fake = Fake(rates, now); state = {"mode": "full"}
run(fake, state)
sent = [o for o in fake.orders if "position" not in o]
magics = {int(c["magic"]): k for k, c in live.EXTRA_BOOKS.items()}
print("1 orders:", [magics[o["magic"]] for o in sent])
print("  manager:", state["manager"]["last"]["lines"])
assert len(sent) == 1, sent
best = max(pair, key=lambda k: live._manager_score(k, live.EXTRA_BOOKS[k], {})[0])
assert magics[sent[0]["magic"]] == best, (best, sent)
loser = next(k for k in pair if k != best)
assert "trưởng phòng chọn" in state["books"][loser]["last"]["reason"], state["books"][loser]["last"]["reason"]
assert "Trưởng phòng chọn" in state["books"][best]["last"]["reason"]
# second pass on the same bar: nothing more
run(fake, state)
assert len([o for o in fake.orders if "position" not in o]) == 1
print("  loser reason:", state["books"][loser]["last"]["reason"].split("Không gửi lệnh:")[-1][:160])

# 2. a trade opened earlier on that side by another agent -> the new moment still trades (one agent)
side = "buy" if sent[0]["type"] == 0 else "sell"
fake2 = Fake(rates, now)
fake2.positions.append(NS(magic=260611, time=now - 3600, type=0 if side == "buy" else 1, ticket=999, volume=0.01,
                          price_open=float(rates["close"][-2]), sl=float(rates["close"][-2]) * (0.99 if side == "buy" else 1.01), tp=0.0, comment="GoldTrader trend", profit=-1.0))
state2 = {"mode": "full"}
run(fake2, state2)
sent2 = [o for o in fake2.orders if "position" not in o]
assert len(sent2) == 1 and magics[sent2[0]["magic"]] == best, fake2.orders  # an earlier same-side trade no longer blocks
print("2 earlier same-side trade does not block: sent", magics[sent2[0]["magic"]])

# 3. dashboard line
view = live._agents_view(state, list(fake.positions), INFO, 10000.0, LIMITS, live._strategy_for(rates, T[i], 1.5, "M15", 900))
assert "rưởng phòng" in view["coordinatorActivity"], view["coordinatorActivity"]
print("3 boss:", view["coordinatorActivity"][:200])
print("ALL MANAGER CHECKS PASSED")
