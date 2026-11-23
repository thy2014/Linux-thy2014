"""本机全屏窗口释放（Linux/X11 与 Windows 11）。

用途：当本机屏幕上出现一个铺满全屏的窗口（例如课堂广播）而使用者希望
回到桌面时，把这类窗口取消映射（X11）或最小化（Win32）。

边界：
- 只调用操作系统标准的窗口管理接口，不注入任何进程、不修改软件文件、
  不 hook 输入、不绕过任何鉴权；
- 只影响本机显示，老师端重新广播即可恢复；
- 每次操作都需要本机使用者确认，并把事件上报老师端（可配置关闭）；
- 使用独占全屏/DirectX 覆盖层的软件无法用窗口接口释放。

实现注意：不同发行版的 Xlib 对 XWindowAttributes 布局不一致（有的多一个
Colormap 字段），因此这里只用稳定的 XGetGeometry 取几何尺寸，不碰该结构体。
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

_DESKTOP_TITLES = {
    "",
    "desktop",
    "desktop window",
    "xfdesktop",
    "gnome-shell",
    "plasmashell",
    "program manager",
}


@dataclass
class ReleaseResult:
    ok: bool
    backend: str
    released: List[str] = field(default_factory=list)
    message: str = ""


class _Unsupported(Exception):
    pass


# --------------------------------------------------------------------- Linux X11
def _load_x11():
    import ctypes
    import ctypes.util

    name = ctypes.util.find_library("X11") or "libX11.so.6"
    try:
        xlib = ctypes.CDLL(name)
    except OSError as exc:
        raise _Unsupported(f"无法加载 libX11：{exc}")

    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XCloseDisplay.restype = ctypes.c_int
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xlib.XDefaultRootWindow.restype = ctypes.c_ulong
    xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    xlib.XDefaultScreen.restype = ctypes.c_int
    xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
    xlib.XDisplayWidth.restype = ctypes.c_int
    xlib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XDisplayHeight.restype = ctypes.c_int
    xlib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XQueryTree.restype = ctypes.c_int
    xlib.XQueryTree.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    xlib.XGetGeometry.restype = ctypes.c_int
    xlib.XGetGeometry.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]
    # XWindowAttributes 的布局随 Xlib 版本不同，统一用 256 字节缓冲 + 哨兵探测，
    # 不直接映射结构体字段，避免越界。
    xlib.XGetWindowAttributes.restype = ctypes.c_int
    xlib.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
    xlib.XUnmapWindow.restype = ctypes.c_int
    xlib.XUnmapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xlib.XFlush.restype = ctypes.c_int
    xlib.XFlush.argtypes = [ctypes.c_void_p]
    xlib.XSync.restype = ctypes.c_int
    xlib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XFree.restype = ctypes.c_int
    xlib.XFree.argtypes = [ctypes.c_void_p]
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    xlib.XFetchName.restype = ctypes.c_int
    xlib.XFetchName.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_char_p),
    ]
    xlib.XGetWindowProperty.restype = ctypes.c_int
    xlib.XGetWindowProperty.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    return ctypes, xlib


def _x11_geometry(xlib, display, window):
    import ctypes

    root = ctypes.c_ulong()
    x = ctypes.c_int()
    y = ctypes.c_int()
    width = ctypes.c_uint()
    height = ctypes.c_uint()
    border = ctypes.c_uint()
    depth = ctypes.c_uint()
    ok = xlib.XGetGeometry(
        display,
        window,
        ctypes.byref(root),
        ctypes.byref(x),
        ctypes.byref(y),
        ctypes.byref(width),
        ctypes.byref(height),
        ctypes.byref(border),
        ctypes.byref(depth),
    )
    if ok != 1:
        return None
    return (x.value, y.value, width.value, height.value, depth.value)


def _x11_map_state(xlib, display, window) -> Optional[int]:
    """安全读取 map_state（2 = IsViewable）。

    先把 256 字节缓冲填成哨兵值，调用 XGetWindowAttributes，再用“最后被写入
    的位置”推断结构体大小（128=经典布局，136=带 Colormap 的新布局），
    据此选择正确偏移，不依赖编译期结构体定义。
    """
    import ctypes

    size = 256
    buffer = (ctypes.c_ubyte * size)()
    ctypes.memset(buffer, 0xAA, size)
    if xlib.XGetWindowAttributes(display, window, ctypes.byref(buffer)) != 1:
        return None
    used = 0
    for index in range(size - 1, -1, -1):
        if buffer[index] != 0xAA:
            used = index + 1
            break
    if used >= 136:
        offset = 92
    elif used >= 128:
        offset = 80
    else:
        return None
    return int(ctypes.cast(ctypes.byref(buffer, offset), ctypes.POINTER(ctypes.c_int))[0])


def _x11_pid(xlib, display, window) -> Optional[int]:
    import ctypes

    atom = xlib.XInternAtom(display, b"_NET_WM_PID", 1)
    if not atom:
        return None
    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    nitems = ctypes.c_ulong()
    bytes_after = ctypes.c_ulong()
    prop = ctypes.c_void_p()
    status = xlib.XGetWindowProperty(
        display, window, atom, 0, 4, 0, 6,  # 6 = XA_CARDINAL
        ctypes.byref(actual_type), ctypes.byref(actual_format),
        ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop),
    )
    if status != 0 or not prop or nitems.value == 0:
        return None
    try:
        return int(ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong))[0])
    finally:
        xlib.XFree(prop)


def _x11_title(xlib, display, window) -> str:
    import ctypes

    name = ctypes.c_char_p()
    title = ""
    if xlib.XFetchName(display, window, ctypes.byref(name)) == 1 and name.value:
        title = name.value.decode("utf-8", "replace")
    if name:
        xlib.XFree(ctypes.cast(name, ctypes.c_void_p))
    return title


def _x11_windows(exclude_ids: Optional[set] = None) -> List[dict]:
    """枚举 root 的直接子窗口，返回铺满屏幕的可见窗口。"""
    import ctypes

    ctypes_mod, xlib = _load_x11()
    display = xlib.XOpenDisplay(None)
    if not display:
        raise _Unsupported("无法连接 X11（DISPLAY 未设置）")
    windows: List[dict] = []
    children = ctypes_mod.POINTER(ctypes_mod.c_ulong)()
    try:
        root = xlib.XDefaultRootWindow(display)
        screen = xlib.XDefaultScreen(display)
        screen_w = xlib.XDisplayWidth(display, screen)
        screen_h = xlib.XDisplayHeight(display, screen)
        root_return = ctypes_mod.c_ulong()
        parent_return = ctypes_mod.c_ulong()
        count = ctypes_mod.c_uint()
        if xlib.XQueryTree(
            display, root,
            ctypes_mod.byref(root_return), ctypes_mod.byref(parent_return),
            ctypes_mod.byref(children), ctypes_mod.byref(count),
        ) != 1:
            raise _Unsupported("XQueryTree 失败")
        own_pid = os.getpid()
        for index in range(int(count.value)):
            window = int(children[index])
            geometry = _x11_geometry(xlib, display, window)
            if geometry is None:
                continue
            width, height = geometry[2], geometry[3]
            if width < screen_w - 2 or height < screen_h - 2:
                continue
            if _x11_map_state(xlib, display, window) != 2:
                continue
            if exclude_ids and window in exclude_ids:
                continue
            pid = _x11_pid(xlib, display, window)
            if pid == own_pid:
                continue
            title = _x11_title(xlib, display, window)
            if not title and pid is None:
                continue  # 桌面/图标层等无主窗口，不动
            if title.strip().lower() in _DESKTOP_TITLES:
                continue
            windows.append(
                {
                    "id": window,
                    "title": title or f"全屏窗口 {window}",
                    "pid": pid,
                    "width": width,
                    "height": height,
                }
            )
    finally:
        try:
            if children:
                xlib.XFree(ctypes_mod.cast(children, ctypes_mod.c_void_p))
        finally:
            xlib.XSync(display, 0)
            xlib.XCloseDisplay(display)
    return windows


def _x11_unmap(windows: List[dict]) -> List[str]:
    ctypes_mod, xlib = _load_x11()
    display = xlib.XOpenDisplay(None)
    if not display:
        return []
    released = []
    try:
        for item in windows:
            if xlib.XUnmapWindow(display, item["id"]) == 1:
                released.append(item["title"])
        xlib.XSync(display, 0)
    finally:
        xlib.XCloseDisplay(display)
    return released


# ------------------------------------------------------------------ Windows 11
def _windows_windows(exclude_ids: Optional[set] = None) -> List[dict]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    screen_w = int(user32.GetSystemMetrics(0))
    screen_h = int(user32.GetSystemMetrics(1))
    own_pid = int(kernel32.GetCurrentProcessId())
    found: List[dict] = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    skip_classes = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

    def class_name(hwnd) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def window_title(hwnd) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buffer, 512)
        return buffer.value

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if exclude_ids and int(hwnd) in exclude_ids:
                return True
            if class_name(hwnd) in skip_classes:
                return True
            title = window_title(hwnd)
            if title.strip().lower() in _DESKTOP_TITLES:
                return True
            rect = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)) != 1:
                return True
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width < screen_w - 2 or height < screen_h - 2:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) == own_pid:
                return True
            found.append(
                {
                    "id": int(hwnd),
                    "title": title or f"全屏窗口 {int(hwnd)}",
                    "pid": int(pid.value),
                    "width": width,
                    "height": height,
                }
            )
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumProc(callback), 0)
    return found


def _windows_minimize(windows: List[dict]) -> List[str]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    released = []
    for item in windows:
        hwnd = wintypes.HWND(item["id"])
        try:
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            if not user32.IsIconic(hwnd):
                user32.SetWindowPos(hwnd, wintypes.HWND(1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
            released.append(item["title"])
        except Exception:
            continue
    return released


# ------------------------------------------------------------------------ 公共
def expand_window_ids(window_ids) -> set:
    """把窗口 id 扩展到它的父窗口链。

    Tk 普通窗口外面会有一层 wrapper（由 Tk 或窗口管理器创建），
    `winfo_id()` 拿到的是内层窗口，枚举时看到的是外层，因此需要一起排除。
    """
    try:
        ids = {int(w) for w in window_ids}
    except (TypeError, ValueError):
        return set()
    if not sys.platform.startswith("linux") or not (os.environ.get("DISPLAY") or "").strip():
        return ids
    try:
        ctypes_mod, xlib = _load_x11()
    except _Unsupported:
        return ids
    display = xlib.XOpenDisplay(None)
    if not display:
        return ids
    try:
        for start in list(ids):
            current = start
            for _ in range(8):
                root_return = ctypes_mod.c_ulong()
                parent_return = ctypes_mod.c_ulong()
                children = ctypes_mod.POINTER(ctypes_mod.c_ulong)()
                count = ctypes_mod.c_uint()
                ok = xlib.XQueryTree(
                    display, current,
                    ctypes_mod.byref(root_return), ctypes_mod.byref(parent_return),
                    ctypes_mod.byref(children), ctypes_mod.byref(count),
                )
                if children:
                    xlib.XFree(ctypes_mod.cast(children, ctypes_mod.c_void_p))
                if ok != 1:
                    break
                parent = int(parent_return.value)
                if not parent or parent == current:
                    break
                ids.add(parent)
                current = parent
    finally:
        xlib.XCloseDisplay(display)
    return ids


def list_fullscreen_windows(exclude_ids: Optional[set] = None) -> List[dict]:
    """列出本机铺满屏幕的窗口（排除本进程与 exclude_ids 中的窗口）。"""
    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or "").strip():
            return []
        try:
            return _x11_windows(exclude_ids)
        except _Unsupported:
            return []
    if sys.platform == "win32":
        try:
            return _windows_windows(exclude_ids)
        except Exception:
            return []
    return []


def release_fullscreen(
    repeat: int = 3,
    interval: float = 0.15,
    exclude_ids: Optional[set] = None,
) -> ReleaseResult:
    """把当前全屏窗口取消映射/最小化，可重复几次以处理“刚关又重开”。"""
    repeats = max(1, int(repeat))
    released_all: List[str] = []
    backend = "none"

    for attempt in range(repeats):
        if sys.platform.startswith("linux"):
            if not (os.environ.get("DISPLAY") or "").strip():
                return ReleaseResult(
                    False, "wayland", [],
                    "当前没有 X11 DISPLAY：Wayland 会话下无法枚举其他应用的窗口",
                )
            try:
                windows = _x11_windows(exclude_ids)
                backend = "x11"
            except _Unsupported as exc:
                return ReleaseResult(False, "x11", [], str(exc))
            if windows:
                released_all.extend(_x11_unmap(windows))
        elif sys.platform == "win32":
            backend = "win32"
            windows = _windows_windows(exclude_ids)
            if windows:
                released_all.extend(_windows_minimize(windows))
        else:
            return ReleaseResult(False, "none", [], "当前系统不支持本机全屏窗口释放")

        if released_all:
            break
        if attempt < repeats - 1:
            time.sleep(max(0.02, float(interval)))

    unique: List[str] = []
    for title in released_all:
        if title not in unique:
            unique.append(title)

    if unique:
        return ReleaseResult(True, backend, unique, "已释放全屏窗口：" + "、".join(unique))
    return ReleaseResult(
        False,
        backend or ("x11" if sys.platform.startswith("linux") else "win32"),
        [],
        "没有检测到可释放的全屏窗口（部分软件使用图形覆盖层，窗口接口无法处理）",
    )


__all__ = ["ReleaseResult", "expand_window_ids", "list_fullscreen_windows", "release_fullscreen"]
