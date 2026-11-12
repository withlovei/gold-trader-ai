import sys, time
from types import SimpleNamespace as NS
import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
from services.api import live
from services.api import llm_judge as _llm; _llm.submit = lambda *a, **k: None; _llm.decide = lambda *a, **k: None  # never call the real CLI in tests
now = int(time.time())
# opening deals (entry 0) carry the magic; broker SL closes (entry 1) carry magic 0
deals = [
    NS(entry=0, magic=260611, position_id=1, time=now - 900, profit=0, commission=0, swap=0),
    NS(entry=0, magic=260612, position_id=2, time=now - 800, profit=0, commission=0, swap=0),
    NS(entry=0, magic=260612, position_id=3, time=now - 700, profit=0, commission=0, swap=0),
    NS(entry=1, magic=0, position_id=1, time=now - 600, profit=-50, commission=0, swap=0),
    NS(entry=1, magic=0, position_id=2, time=now - 500, profit=-30, commission=0, swap=0),
    NS(entry=1, magic=260612, position_id=3, time=now - 400, profit=-30, commission=0, swap=0),
]
class F:
    def history_deals_get(self, a=None, b=None, position=None):
        return [d for d in deals if d.position_id == position] if position is not None else deals
f = F()
allb, m15, m30 = live._loss_streak(f, now), live._loss_streak(f, now, 260611), live._loss_streak(f, now, 260612)
print("all", allb, "M15", m15, "M30", m30)
assert (allb, m15, m30) == (3, 1, 2)
print("STREAK OK")
