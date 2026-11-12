"""Detached restart helper used after the daily meeting changed code:
    python -m services.api.restart <backup dir>
Stops the server on port 8787, starts it again with the new code and waits for /api/health. If
the new server does not answer within 60 s, the code is restored from the backup and the server is
started once more. Every step goes into the head of desk's diary."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8787
MEETING = sys.argv[2] if len(sys.argv) > 2 else ""
FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _log(kind: str, text: str, detail: object = None) -> None:
    try:
        sys.path.insert(0, str(ROOT))
        from services.api import journal

        journal.log_manager(kind, text, detail, MEETING)
    except Exception:  # noqa: BLE001
        pass


def _stop() -> None:
    script = (f"$p = Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue | "
              "Select-Object -ExpandProperty OwningProcess -Unique; foreach ($id in $p) { Stop-Process -Id $id -Force -Confirm:$false }")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _start() -> None:
    data = ROOT / "data"
    out = open(data / "uvicorn.log", "ab")
    err = open(data / "uvicorn.err", "ab")
    subprocess.Popen([sys.executable, "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                     cwd=str(ROOT), stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=FLAGS, close_fds=True)


def _healthy(seconds: int = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=3) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False


def main(backup: str) -> None:
    time.sleep(3)  # let the meeting thread finish writing its minutes
    _stop()
    time.sleep(2)
    _start()
    if _healthy():
        _log("restart", "Server đã chạy lại với mã mới.")
        return
    from services.api.meeting import restore_code

    _stop()
    if backup:
        restore_code(backup)
    _start()
    ok = _healthy()
    _log("rollback", "Server không chạy được với mã mới, đã khôi phục mã cũ từ " + (backup or "(không có bản sao)") +
         (" và chạy lại thành công." if ok else ". Server vẫn chưa chạy, cần kiểm tra tay."), {"backup": backup})


if __name__ == "__main__":
    main("" if len(sys.argv) < 2 or sys.argv[1] == "-" else sys.argv[1])
