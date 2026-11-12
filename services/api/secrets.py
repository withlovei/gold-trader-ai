import ctypes
from ctypes import wintypes


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_from(data: bytes) -> tuple[DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def protect(secret: str) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, _buffer = _blob_from(secret.encode("utf-8"))
    protected = DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        "GoldTrader",
        None,
        None,
        None,
        0,
        ctypes.byref(protected),
    )
    if not ok:
        raise OSError("Không mã hóa được mật khẩu trên máy này.")
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        kernel32.LocalFree(protected.pbData)


def unprotect(protected_bytes: bytes) -> str:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, _buffer = _blob_from(protected_bytes)
    plain = DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(plain),
    )
    if not ok:
        raise OSError("Không đọc được mật khẩu đã lưu.")
    try:
        return ctypes.string_at(plain.pbData, plain.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(plain.pbData)
