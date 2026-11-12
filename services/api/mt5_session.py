import threading
from collections.abc import Iterator
from contextlib import contextmanager

from services.api.settings_store import read_password, read_settings

_lock = threading.Lock()


@contextmanager
def open_terminal() -> Iterator[object]:
    with _lock:
        yield _ensure()


def _ensure() -> object:
    password = read_password()
    settings = read_settings()
    if not password or not str(settings["login"]).isdigit():
        raise RuntimeError("Chưa có tài khoản MetaTrader. Vào Cài đặt và bấm Lưu và kết nối.")
    try:
        import MetaTrader5 as mt5
    except ImportError as error:
        raise RuntimeError("Chưa cài gói MetaTrader5 trong môi trường dự án.") from error
    if mt5.account_info() is not None:
        return mt5
    ready = mt5.initialize(
        path=str(settings["terminalPath"]),
        login=int(str(settings["login"])),
        password=password,
        server=str(settings["server"]),
        timeout=60_000,
    )
    if not ready or mt5.account_info() is None:
        code, message = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"Không vào được MetaTrader ({code}): {message}")
    return mt5
