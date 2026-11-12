"""Run every regression test and print one PASS/FAIL line each.

usage: python tests/run_all.py <dir containing hist/M15.json, M30.json, H1.json, H4.json, M5.json>

Create the history first with:  python scripts/fetch_history.py <dir> XAUUSDm
Tests use a fake MetaTrader, temporary SQLite files and a stubbed Claude CLI / Telegram; they never
touch the real data/ folder. test_meeting.py temporarily edits and restores
services/api/methods/false_breakout.py.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = [
    "test_cost", "test_streak", "test_methods", "test_agents", "test_switch", "test_flag",
    "test_manager", "test_gate", "test_m30book", "test_models", "test_meeting",
]
OK_MARKS = ("PASSED", "OK")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    data = sys.argv[1]
    failed = 0
    for name in TESTS:
        done = subprocess.run(
            [sys.executable, str(HERE / f"{name}.py"), data],
            capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        lines = [line for line in (done.stdout or "").strip().splitlines() if line.strip()]
        last = lines[-1] if lines else (done.stderr or "").strip().splitlines()[-1:] or [""]
        last = last if isinstance(last, str) else last[0]
        passed = done.returncode == 0 and any(mark in last for mark in OK_MARKS)
        failed += 0 if passed else 1
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {last[:100]}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
