"""广播期间锁定键盘。

- Linux/X11：对广播全屏窗口做 Tk 全局 grab（底层就是 XGrabKeyboard），
  所有按键都进入本进程，只放行配置的紧急组合键。
- Windows 11：WH_KEYBOARD_LL 低级键盘钩子，在系统层面吞掉按键。
- Wayland / 无桌面：没有通用的全局键盘拦截 API，退回 NullLock，
  界面会明确提示“仅遮罩、无法强制锁键”。

紧急组合键（默认 Ctrl+Alt+Shift+Q）是安全阀：任何情况下本机使用者
都能用它调出解锁对话框，避免机器被永久锁死。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from typing import Callable, Optional, Sequence

EMERGENCY_SEQUENCE = ("<Control-Alt-Shift-q>", "<Control-Alt-Shift-Q>")


class KeyboardLock:
    backend = "none"

    def __init__(self, on_escape: Optional[Callable[[], None]] = None) -> None:
        self.on_escape = on_escape
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        return "未启用"


class NullLock(KeyboardLock):
    backend = "none"

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def describe(self) -> str:
        return "无法强制锁定键盘（Wayland/无桌面环境）"


class TkGlobalGrabLock(KeyboardLock):
    """X11 下用全局 grab 把按键收进广播窗口。"""

    backend = "x11-grab"

    def __init__(
        self,
        widget: tk.Misc,
        allow_escape: bool = True,
        on_escape: Optional[Callable[[], None]] = None,
        sequences: Sequence[str] = EMERGENCY_SEQUENCE,
    ) -> None:
        super().__init__(on_escape)
        self.widget = widget
        self.allow_escape = allow_escape
        self.sequences = tuple(sequences)
        self._generation = 0

    def start(self) -> None:
        """不阻塞等待窗口可见：先绑定紧急键，再在事件循环里重试 grab。

        无窗口管理器的环境（部分 Xvfb / 精简桌面）不会发送 VisibilityNotify，
        wait_visibility() 会永久挂起，所以这里改为定时重试。
        """
        self._generation += 1
        self._active = True
        if self.allow_escape and self.on_escape is not None:
            for sequence in self.sequences:
                try:
                    self.widget.bind_all(sequence, self._on_combo)
                except tk.TclError:
                    pass
        try:
            self.widget.update_idletasks()
        except tk.TclError:
            pass
        self._try_grab(self._generation, 6)

    def _try_grab(self, generation: int, attempts: int) -> None:
        if not self._active or generation != self._generation:
            return
        try:
            self.widget.grab_set_global()
            self.backend = "x11-grab"
            try:
                self.widget.focus_force()
            except tk.TclError:
                pass
            return
        except tk.TclError:
            pass
        if attempts <= 0:
            self.backend = "tk-focus"
            try:
                self.widget.focus_force()
            except tk.TclError:
                pass
            return
        try:
            self.widget.after(40, lambda: self._try_grab(generation, attempts - 1))
        except tk.TclError:
            self.backend = "tk-focus"

    def _on_combo(self, _event: "tk.Event") -> str:
        if self.on_escape is not None:
            self.on_escape()
        return "break"

    def stop(self) -> None:
        self._generation += 1
        self._active = False
        for sequence in self.sequences:
            try:
                self.widget.unbind_all(sequence)
            except tk.TclError:
                pass
        try:
            self.widget.grab_release()
        except tk.TclError:
            pass

    def describe(self) -> str:
        if self.backend == "x11-grab":
            return "X11 全局键盘拦截已生效（Ctrl+Alt+Shift+Q 可紧急解锁）"
        return "仅窗口焦点锁定，无法拦截系统级快捷键"


def create_keyboard_lock(
    widget: tk.Misc,
    allow_escape: bool = True,
    on_escape: Optional[Callable[[], None]] = None,
) -> KeyboardLock:
    if sys.platform == "win32":
        try:
            from .keylock_win import WindowsHookLock

            return WindowsHookLock(widget, allow_escape=allow_escape, on_escape=on_escape)
        except Exception:
            return NullLock(on_escape)
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        try:
            return TkGlobalGrabLock(widget, allow_escape=allow_escape, on_escape=on_escape)
        except Exception:
            return NullLock(on_escape)
    return NullLock(on_escape)
