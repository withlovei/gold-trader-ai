"""Research-method framework: cards, gates, draft status, paper trades with each method's exits."""
import json, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
from services.api import agents, methods, shadow
from services.api.methods.base import Gates, Method, Plan
from services.api.strategies import evaluate_strategies
from services.api.chart_analysis import _atr, _thresholds

SP = sys.argv[1]
R = json.load(open(SP + "/hist/M15.json"))


def catalog_at(i, **kw):
    rows = R[i - 599: i + 1]
    bars = [tuple(map(float, r[1:5])) for r in rows]
    times = [int(r[0]) for r in rows]
    a = [v for v in _atr(bars, 14) if v][-1]
    s, r = _thresholds(bars, a)
    return evaluate_strategies(bars, "M15", s, r, 0.2, 1.5, times, 12, **kw)["catalog"], bars, times


cat, _, _ = catalog_at(len(R) - 2)
ids = [c["id"] for c in cat]
assert ids[:5] == ["trend", "pullback", "breakout", "reversal", "range"] and set(ids[5:]) == set(methods.BY_ID), ids
for card in cat[5:]:
    assert card["live"] is False and card["gates"][-1]["name"].startswith("Giờ"), card["id"]
    assert not card.get("chosen")
assert len(catalog_at(len(R) - 2, methods=False)[0]) == 5
print("1 catalog ok:", ids[5:])

# a confirmed signal of each fixed/trail method somewhere in recent history, with valid prices
seen = {}
for i in range(len(R) - 2, len(R) - 4000, -1):
    cat, bars, times = catalog_at(i)
    for card in cat[5:]:
        if card.get("confirmed") and card["id"] not in seen:
            risk = abs(card["entry"] - card["stop"])
            assert risk > 0 and card["side"] in {"buy", "sell"}
            if card["manage"] == "fixed":
                assert card["takeProfit"] is not None and (card["takeProfit"] > card["entry"]) == (card["side"] == "buy")
            else:
                assert card["takeProfit"] is None
            assert all(g["state"] == "ok" for g in card["gates"]), card["gates"]
            seen[card["id"]] = (i, card)
    if len(seen) == len(methods.METHODS):
        break
print("2 signals found for:", sorted(seen))
assert len(seen) == len(methods.METHODS)


# draft status: card says not implemented, never confirmed
class Draft(Method):
    id, name, alias, status, gates = "draftx", "Thử", "Ai đó", "draft", ("A", "B")


card = Draft().evaluate({"timeframe": "M15", "atr": 1.0})
assert "Chưa triển khai" in card["summary"] and not card["confirmed"] and [g["state"] for g in card["gates"]] == ["wait", "wait", "wait"]


class Broken(Method):
    id, name, alias, status, gates = "broken", "Hỏng", "X", "paper", ("A",)

    def scan(self, m, g):
        return 1 / 0


card = Broken().evaluate({"timeframe": "M15", "atr": 1.0})
assert "Lỗi trong code" in card["summary"] and not card["confirmed"]
print("3 draft / broken method handled")

# paper trades keep each method's exits
tmp = Path(tempfile.mkdtemp()) / "t.db"
shadow.DB_PATH = tmp
fixed_id = next(k for k, (_, c) in seen.items() if c["manage"] == "fixed")
i, card = seen[fixed_id]
cat, bars, times = catalog_at(i)
tick = NS(bid=bars[-1][3], ask=bars[-1][3] + 0.2)
shadow.process((fixed_id,), cat, bars, times, 900, tick, 0.2, -4.9, 0.0)
with shadow._connect() as c:
    row = dict(c.execute("SELECT * FROM shadow_trades").fetchone())
assert row["manage"] == "fixed" and row["take"] is not None and row["max_bars"] == card["maxBars"], row
# walk forward until it closes
for j in range(i + 1, i + 200):
    rows = R[j - 599: j + 1]
    shadow.process((), None, [tuple(map(float, r[1:5])) for r in rows], [int(r[0]) for r in rows], 900, tick, 0.2, -4.9, 0.0)
    with shadow._connect() as c:
        row = dict(c.execute("SELECT * FROM shadow_trades").fetchone())
    if row["status"] == "closed":
        break
assert row["status"] == "closed" and row["reason"] in {"Chốt lời", "Cắt lỗ", f"Hết {card['maxBars']} nến"}, row
assert row["bars_held"] <= card["maxBars"]
summary = shadow.summary()
assert fixed_id in summary["strategies"] and "·" in summary["strategies"][fixed_id]["name"]
print("4 paper trade", fixed_id, "closed:", row["reason"], "after", row["bars_held"], "bars, R", row["r"])

# lab agents
lab = agents.lab_agents()
assert len(lab) == 3 + len(methods.METHODS)
assert agents.label("retest-M15") == "Al Brooks (Phá vùng rồi kiểm tra lại M15)"
assert agents.profile("mtf-M15")["why"] and agents.method_rules("fakeout-M15")["entry"]
assert agents.alias("trend-M15") == "Linda Raschke"
print("ALL METHOD CHECKS PASSED")
