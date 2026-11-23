"""Windows 11 低级键盘钩子。

只能在 win32 上 import；Linux 端通过 keylock.create_keyboard_lock 动态加载。
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

from .keylock import KeyboardLock

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_Q = 0x51

_MOD_GROUPS = {
    "shift": {VK_SHIFT, VK_LSHIFT, VK_RSHIFT},
    "ctrl": {VK_CONTROL, VK_LCONTROL, VK_RCONTROL},
    "alt": {VK_MENU, VK_LMENU, VK_RMENU},
}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class WindowsHookLock(KeyboardLock):
    backend = "win-hook"

    def __init__(
        self,
        widget,
        allow_escape: bool = True,
        on_escape: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(on_escape)
        self.widget = widget
        self.allow_escape = allow_escape
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._hook = None
        self._proc = None
        self._user32 = None
        self._pressed: set[int] = set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        for _ in range(100):
            if self._hook:
                break
            time.sleep(0.02)
        self._active = True

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = user32
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._thread_id = int(kernel32.GetCurrentThreadId())
        self._proc = HOOKPROC(self._callback)
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, module, 0)
        if not self._hook:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        user32 = self._user32
        if user32 is None or code != 0:
            return user32.CallNextHookEx(self._hook, code, wparam, lparam) if user32 else 0
        try:
            kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(kb.vkCode)
        except Exception:
            return user32.CallNextHookEx(self._hook, code, wparam, lparam)
        if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self._pressed.add(vk)
        elif wparam in (WM_KEYUP, WM_SYSKEYUP):
            self._pressed.discard(vk)
        if not self._active:
            return user32.CallNextHookEx(self._hook, code, wparam, lparam)
        if (
            self.allow_escape
            and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            and vk == VK_Q
            and self._combo_ready()
        ):
            self._fire_escape()
        return 1  # 吞掉按键

    def _combo_ready(self) -> bool:
        for keys in _MOD_GROUPS.values():
            if not (self._pressed & keys):
                return False
        return True

    def _fire_escape(self) -> None:
        if self.on_escape is None:
            return
        try:
            self.widget.after(0, self.on_escape)
        except Exception:
            pass

    def stop(self) -> None:
        self._active = False
        user32 = self._user32
        if user32 is not None and self._thread_id:
            try:
                user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if user32 is not None and self._hook:
            try:
                user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
        self._hook = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
