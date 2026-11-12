"""Every Claude gate call is logged once per agent (answer, unreadable, error, timeout), never twice."""
import json, subprocess, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
from services.api import journal, llm_judge

tmp = Path(tempfile.mkdtemp())
journal.DB_PATH = tmp / "t.db"
llm_judge.DATA_DIR = tmp
llm_judge.enabled = lambda: True
llm_judge.find_cli = lambda: "claude.exe"


def runner_for(result=None, is_error=False, cost=0.03, raise_=None):
    def run(*a, **k):
        if raise_:
            raise raise_
        payload = {"result": result, "is_error": is_error, "total_cost_usd": cost, "duration_ms": 6000,
                   "usage": {"input_tokens": 3000, "output_tokens": 80}}
        return NS(stdout=json.dumps(payload))
    return run


ctx = {"agentId": "pullback-M15", "agent": "Larry Connors", "side": "buy", "entry": 4100, "stop": 4090, "bars": [], "gates": []}
assert llm_judge.decide(ctx, runner_for('{"decision": "giảm", "reason": "sát cản"}'))["decision"] == "giảm"
assert llm_judge.decide(ctx, runner_for('{"decision": "vào", "reason": "ok"}', cost=0.02))["decision"] == "vào"
assert llm_judge.decide(ctx, runner_for("không phải json", cost=0.01)) is None
assert llm_judge.decide(ctx, runner_for(None, is_error=True, cost=0.005)) is None
assert llm_judge.decide(ctx, runner_for(raise_=subprocess.TimeoutExpired("claude", 40))) is None
assert llm_judge.decide(ctx, runner_for(raise_=OSError("missing"))) is None  # never started: not logged
assert llm_judge.decide({**ctx, "agentId": "trend-M30"}, runner_for('{"decision": "bỏ", "reason": "gãy"}', cost=0.04))["decision"] == "bỏ"
journal.record_veto("trend-M30", 1, "M30", "buy", 1.0, 0.5, None, "gãy", {"cost": 0.04})  # must not log again
costs = journal.llm_costs()["agents"]
print(json.dumps(costs, ensure_ascii=False))
pb, m30 = costs["pullback-M15"], costs["trend-M30"]
assert pb["calls"] == 5 and abs(pb["cost"] - 0.065) < 1e-9, pb
assert pb["decisions"] == {"giảm": 1, "vào": 1, "lỗi": 2, "quá giờ": 1}, pb["decisions"]
assert pb["today"]["calls"] == 5 and pb["inputTokens"] == 12000
assert m30["calls"] == 1 and m30["decisions"] == {"bỏ": 1}
print("COST CHECKS PASSED")
