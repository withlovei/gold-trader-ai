"""Multi-agent coordinator on real M15 history with a fake MetaTrader:
pullback agent orders with its own magic, may stack with a same-side position, is blocked against
a winning opposite position, allowed against a losing one, and blocked by the total open-risk cap."""
import json, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
from services.api import journal, live, notify, shadow
from services.api import llm_judge as _llm; _llm.submit = lambda *a, **k: None; _llm.decide = lambda *a, **k: None  # never call the real CLI in tests
tmpdb = Path(tempfile.mkdtemp()) / "t.db"
journal.DB_PATH = tmpdb; shadow.DB_PATH = tmpdb; live.RUNTIME_PATH = tmpdb.with_name("runtime.json")
notify.send = lambda text: None

SP = sys.argv[1]
dtype = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")]
R = json.load(open(SP + "/hist/M15.json")); T = [r[0] for r in R]
KEY = "pullback-M15"; BOOK = live.EXTRA_BOOKS[KEY]; MAGIC_PB = int(BOOK["magic"])
assert MAGIC_PB == 260613 and MAGIC_PB in live.AGENT_MAGICS


def frame(i):
    rows = [tuple(r[:5]) for r in R[i - 598: i + 1]] + [(T[i + 1],) + (R[i + 1][1],) * 4]
    return np.array(rows, dtype=dtype), T[i + 1] + 10


class Fake:
    TRADE_ACTION_DEAL = 1; TRADE_ACTION_SLTP = 6; ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1; ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0; ORDER_FILLING_IOC = 1; ORDER_FILLING_RETURN = 2; TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M15 = 15; TIMEFRAME_M30 = 30

    def __init__(s, rates, now, positions=()):
        s.rates, s.now, s.orders, s.positions = rates, now, [], list(positions)

    def copy_rates_from_pos(s, sym, f, a, n): return s.rates
    def positions_get(s, symbol=None, ticket=None):
        return [p for p in s.positions if p.ticket == ticket] if ticket is not None else list(s.positions)
    def history_deals_get(s, a=None, b=None, position=None): return []
    def last_error(s): return (0, "")

    def order_send(s, req):
        s.orders.append(req)
        if "position" not in req:
            s.positions.append(NS(magic=req["magic"], time=s.now, type=req["type"], ticket=100 + len(s.orders), volume=req["volume"],
                                  price_open=req["price"], sl=req["sl"], tp=req["tp"], comment=req["comment"], profit=0.0))
        return NS(retcode=10009, comment="done", order=len(s.orders), price=req["price"], volume=req["volume"])


INFO = NS(trade_tick_size=0.001, trade_tick_value=0.1, volume_step=0.01, volume_min=0.01, volume_max=200, digits=3,
          filling_mode=1, spread=200, point=0.001, swap_mode=1, swap_long=-493.4, swap_short=0)
LIMITS = {"perTradePercent": 0.75, "dailyLossPercent": 2.5, "drawdownPercent": 30, "maxPositions": 3, "maxLossStreak": 4,
          "minRewardRatio": 1.5, "minLotPercent": 2.0, "maxOpenRiskPercent": 6.0}

# a bar where the pullback card is confirmed (whatever the selector chose)
pb = None
for i in range(len(R) - 50, 700, -1):
    rates, now = frame(i)
    card = live._agent_card(live._strategy_for(rates, T[i], 1.5), "pullback")
    if card.get("confirmed") and card.get("side") in {"buy", "sell"}:
        pb = i; side = card["side"]; break
print("pullback signal bar", T[pb], side)
px = float(frame(pb)[0]["open"][-1])


def other(kind, profit, sl_dist=10.0, volume=0.05, magic=live.MAGIC, ticket=900):
    """an open position of another agent: kind 'same'/'opposite' relative to the pullback side"""
    t = (0 if side == "buy" else 1) if kind == "same" else (1 if side == "buy" else 0)
    sl = px - sl_dist if t == 0 else px + sl_dist
    return NS(magic=magic, time=0, type=t, ticket=ticket, volume=volume, price_open=px, sl=sl, tp=0.0, comment="GoldTrader trend", profit=profit)


def run(positions):
    rates, now = frame(pb)
    fake = Fake(rates, now, positions)
    state = {"mode": "full"}
    live._book_step(fake, state, KEY, BOOK, "XAUUSDm", NS(bid=px, ask=px + 0.2, time=now), INFO, 10000.0, LIMITS, 0.0, 10000.0, 0, "")
    sent = [o for o in fake.orders if "position" not in o]
    return sent, state["books"][KEY]["last"]["reason"]


sent, why = run([])
print("1 alone:", len(sent), sent[0]["magic"] if sent else why[-120:])
assert len(sent) == 1 and sent[0]["magic"] == MAGIC_PB and "pullback" in sent[0]["comment"]
sent, why = run([other("same", 50.0)])
print("2 same side stacked:", len(sent))
assert len(sent) == 1
sent, why = run([other("opposite", 25.0)])
print("3 opposite winning -> blocked:", len(sent), "|", why[why.find("Không gửi"):][:120])
assert not sent and "đang lãi" in why
sent, why = run([other("opposite", -25.0)])
print("4 opposite losing -> allowed:", len(sent))
assert len(sent) == 1
# 0.5 lot x 11 price = $550 = 5.5% of 10,000 already at risk -> new trade pushes past 6%
sent, why = run([other("same", 0.0, sl_dist=11.0, volume=0.5)])
print("5 open-risk cap:", len(sent), "|", why[why.find("tổng rủi ro"):][:120])
assert not sent and "tổng rủi ro" in why
# a trailed position (stop past entry) carries no risk
trailed = other("same", 80.0, sl_dist=-5.0, volume=0.5)
sent, why = run([trailed])
print("6 trailed position counts 0 risk:", len(sent))
assert len(sent) == 1
print("ALL AGENT CHECKS PASSED")
