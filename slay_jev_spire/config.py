"""API 密钥配置：环境变量优先，本机 Windows DPAPI 加密存储。"""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys

from .selectors import SelectionError


DEFAULT_KEY_PATH = Path(__file__).resolve().parents[1] / 'config' / 'jev-key.dpapi'


def _crypt(data: bytes, decrypt: bool) -> bytes:
    """调用当前 Windows 用户的 DPAPI；不显示 UI，不输出密钥。"""
    if sys.platform != 'win32':
        raise OSError('Windows DPAPI unavailable')

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    try:
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise OSError('Windows key protection failed')
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            if decrypt:
                ctypes.memset(target.data, 0, target.size)
            kernel32.LocalFree(target.data)
    finally:
        ctypes.memset(buffer, 0, len(data))


def save_jev_key(secret: str, path: Path = DEFAULT_KEY_PATH) -> None:
    """保存当前用户加密的 Jev 密钥；临时文件也只包含密文。"""
    if not secret.strip():
        raise SelectionError('Jev 密钥不能为空。')
    try:
        encrypted = _crypt(secret.strip().encode('utf-8'), False)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.dpapi.tmp')
        temporary.write_bytes(encrypted)
        temporary.replace(path)
    except OSError:
        raise SelectionError('无法保存本机加密密钥；请检查 Windows 用户与文件权限。') from None


def load_jev_key(path: Path = DEFAULT_KEY_PATH) -> None:
    """环境变量优先，否则读取本机加密密钥到当前进程内存。"""
    if os.environ.get('TYPESAFE_API_KEY', '').strip():
        return
    try:
        secret = _crypt(path.read_bytes(), True).decode('utf-8').strip()
        if not secret:
            raise ValueError('Empty key')
    except (OSError, ValueError, UnicodeError):
        raise SelectionError('未配置可读取的 Jev 密钥；请运行 configure_key.py 或设置 TYPESAFE_API_KEY。') from None
    os.environ['TYPESAFE_API_KEY'] = secret
