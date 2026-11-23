"""Windows 11 低级键盘钩子。

只能在 win32 上 import；Linux 端通过 keylock.create_keyboard_lock 动态加载。

实现要点：
- 所有 Win32 函数都显式声明 argtypes/restype。64 位下 HHOOK 是指针宽度，
  ctypes 默认用 c_int 接收会截断，钩子安装会直接失败。
- 钩子回调在独立线程里跑消息循环，紧急组合键通过队列交回 Tk 主线程，
  避免在非主线程调用 Tk。
"""
from __future__ import annotations

import ctypes
import queue
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


LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


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
        self._ready = threading.Event()
        self._error = ""
        self._escape_queue: "queue.Queue[bool]" = queue.Queue()
        self._poll_id = None
        self._closed = False

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._active = True
            return
        self._closed = False
        self._error = ""
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="thyclass-keyhook", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        if self._hook:
            self._active = True
            self._schedule_escape_poll()
        else:
            self._active = False
            if not self._error:
                self._error = "键盘钩子安装超时（可能被安全软件拦截）"

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            HOOKPROC,
            wintypes.HMODULE,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = LRESULT
        user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostThreadMessageW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        self._user32 = user32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        self._proc = HOOKPROC(self._callback)
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, module, 0)
        if not self._hook:
            self._error = (
                f"SetWindowsHookEx 失败（WinError {ctypes.get_last_error()}），"
                "可能被安全软件拦截"
            )
            self._ready.set()
            return
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        # 消息循环退出后再卸载，避免钩子还指向已退出的线程
        try:
            user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass
        self._hook = None

    # ------------------------------------------------------------------ 回调
    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        user32 = self._user32
        if user32 is None:
            return 0
        if code != 0:
            return user32.CallNextHookEx(None, code, wparam, lparam)
        try:
            kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(kb.vkCode)
        except Exception:
            return user32.CallNextHookEx(None, code, wparam, lparam)
        if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self._pressed.add(vk)
        elif wparam in (WM_KEYUP, WM_SYSKEYUP):
            self._pressed.discard(vk)
        if not self._active:
            return user32.CallNextHookEx(None, code, wparam, lparam)
        if (
            self.allow_escape
            and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            and vk == VK_Q
            and self._combo_ready()
        ):
            self._escape_queue.put(True)
        return 1  # 吞掉按键

    def _combo_ready(self) -> bool:
        for keys in _MOD_GROUPS.values():
            if not (self._pressed & keys):
                return False
        return True

    # 紧急键交回 Tk 主线程，避免跨线程调用 Tk
    def _schedule_escape_poll(self) -> None:
        self._poll_id = None
        if self._closed or self.widget is None:
            return
        try:
            self._poll_id = self.widget.after(60, self._pump_escape)
        except Exception:
            self._poll_id = None

    def _pump_escape(self) -> None:
        self._poll_id = None
        if self._closed:
            return
        fired = False
        while True:
            try:
                self._escape_queue.get_nowait()
            except queue.Empty:
                break
            fired = True
        if fired and self._active and self.on_escape is not None:
            try:
                self.on_escape()
            except Exception:
                pass
        if not self._closed:
            self._schedule_escape_poll()

    def stop(self) -> None:
        self._active = False
        self._closed = True
        if self._poll_id is not None:
            try:
                self.widget.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
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
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._pressed.clear()

    def describe(self) -> str:
        if self._active:
            if self.allow_escape:
                return "Windows 低级键盘钩子已生效（Ctrl+Alt+Shift+Q 可紧急解锁）"
            return "Windows 低级键盘钩子已生效（已关闭紧急解锁）"
        return self._error or "键盘钩子未生效"
