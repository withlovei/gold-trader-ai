"""Daily meeting with a fake Claude CLI: decisions applied with full authority, code edit applied
and logged with its diff, a broken edit rolled back, diary complete. Real settings/journal untouched."""
import json, sys, tempfile, hashlib
from pathlib import Path
from types import SimpleNamespace as NS
import pathlib as _pl; ROOT = str(_pl.Path(__file__).resolve().parents[1]); sys.path.insert(0, ROOT)
from services.api import journal, live, shadow, settings_store, meeting, notify
tmp = Path(tempfile.mkdtemp())
journal.DB_PATH = tmp / "t.db"; shadow.DB_PATH = tmp / "t.db"; settings_store.DB_PATH = tmp / "s.db"
meeting.MEETING_DIR = tmp / "meetings"; meeting.BACKUP_DIR = tmp / "backups"
notify.send = lambda text: None
TARGET = Path(ROOT) / "services" / "api" / "methods" / "false_breakout.py"
original = TARGET.read_bytes()
mode = {"edit": "good"}


def fake(command, input=None, **kw):
    if "--permission-mode" not in command:  # decision call
        answer = {"summary": "Wyckoff lỗ liên tục, cho xuống. Bulkowski lên thử.",
                  "decisions": [{"id": "reversal-M15", "real": False, "reason": "3 lệnh thua, kiểm thử ~0"},
                                {"id": "flag-H1", "real": True, "reason": "kiểm thử đạt cả hai giai đoạn"},
                                {"id": "trend-M15", "real": True, "reason": "giữ"}],
                  "improve": [{"id": "fakeout-M15", "goal": "lọc phá vỡ giả trong phiên Á"}]}
        assert "reversal-M15" in input and "agentIds" in input
        return NS(stdout=json.dumps({"result": "Biên bản:\n" + json.dumps(answer, ensure_ascii=False), "total_cost_usd": 0.1}), stderr="", returncode=0)
    assert command[command.index("--tools") + 1] == "Read,Edit,Write,Grep,Glob"
    if mode["edit"] == "good":
        TARGET.write_bytes(original + b"\n# meeting test edit\n")
    else:
        TARGET.write_bytes(original + b"\ndef broken(:\n")
    return NS(stdout=json.dumps({"result": 'xong {"summary": "Thêm lọc phiên Á.", "files": ["services/api/methods/false_breakout.py"]}'}), stderr="", returncode=0)


try:
    assert live.agent_real("reversal-M15") is True and live.agent_real("flag-H1") is False
    out = meeting.run({"balance": 930, "equity": 928}, runner=fake, restart=False)
    assert live.agent_real("reversal-M15") is False and live.agent_real("flag-H1") is True, "decisions not applied"
    imp = out["improvements"][0]
    assert imp["status"] == "applied" and "meeting test edit" in imp["diff"], imp
    st = meeting.status()
    kinds = [e["kind"] for e in st["events"]]
    assert "decision" in kinds and "change" in kinds and "code" in kinds and kinds[-1] == "done" and st["result"]["changes"], st
    print("progress events:", len(kinds), [e["text"][:50] for e in st["events"][:3]])
    print("1 applied:", [(c["name"], c["real"]) for c in out["changes"]], "|", imp["statusText"][:80])
    TARGET.write_bytes(original)

    mode["edit"] = "broken"
    out2 = meeting.run(None, runner=fake, restart=False)
    imp2 = out2["improvements"][0]
    assert imp2["status"] == "rolled_back" and TARGET.read_bytes() == original, imp2
    print("2 broken edit rolled back:", imp2["statusText"])

    kinds = [row["kind"] for row in journal.manager_log(100)]
    for k in ("meeting", "decision", "change", "improve", "code", "rollback"):
        assert k in kinds, (k, kinds)
    full = journal.manager_log(100, "meeting")
    assert any((row["detail"] or {}).get("context") for row in full), "context missing from diary"
    assert any("raw" in ((row["detail"] or {}).get("llm") or {}) for row in full), "raw CLI answer missing"
    print("3 diary kinds:", sorted(set(kinds)), "| entries", len(kinds))
    print("4 telegram:\n" + meeting.telegram_text(out)[:300])
    assert len(meeting.history()) == 1  # same date file overwritten
    from datetime import datetime, timezone
    assert meeting.due(datetime(2026, 11, 11, 22, 15, tzinfo=timezone.utc)) and not meeting.due(datetime(2026, 11, 11, 21, 0, tzinfo=timezone.utc))
    assert not meeting.due(datetime(2026, 11, 14, 22, 15, tzinfo=timezone.utc))  # Saturday
    print("ALL MEETING CHECKS PASSED")
finally:
    TARGET.write_bytes(original)
