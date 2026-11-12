from services.api.settings_store import read_password, read_settings, save_settings


def connect_account(terminal_path: str, server: str, login: str, symbol: str, password: str) -> dict[str, str | float | bool]:
    login = login.strip()
    server = server.strip()
    symbol = symbol.strip()
    terminal_path = terminal_path.strip()
    if not login.isdigit():
        raise ValueError("Số tài khoản chỉ gồm chữ số.")
    if not server or not symbol or not terminal_path:
        raise ValueError("Cần đủ đường dẫn MetaTrader, máy chủ, tài khoản và mã vàng.")

    stored_password = password.strip()
    if not stored_password:
        existing = read_password()
        if not existing:
            raise ValueError("Nhập mật khẩu MetaTrader trên màn Cài đặt.")
        stored_password = existing

    save_settings(terminal_path, server, login, symbol, password.strip())

    try:
        import MetaTrader5 as mt5
    except ImportError as error:
        raise RuntimeError("Chưa cài gói MetaTrader5. Chạy pip install -r requirements.txt") from error

    from services.api.mt5_session import open_terminal

    with open_terminal() as mt5:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise RuntimeError(f"Đã mở MetaTrader nhưng chưa đọc được tài khoản ({code}): {message}")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Tài khoản đã vào, nhưng không thấy mã {symbol}. Kiểm tra tên mã trên Exness.")
        return {
            "ok": True,
            "login": str(account.login),
            "name": account.name,
            "server": account.server,
            "balance": float(account.balance),
            "currency": account.currency,
            "symbol": symbol,
        }
