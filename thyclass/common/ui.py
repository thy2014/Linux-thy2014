"""Tk 界面小工具：JPEG → PhotoImage。

不依赖 PIL.ImageTk（不同平台的 Tk/Pillow 组合经常不匹配），
而是用 Pillow 解成 PNG，再交给 Tk 8.6 的 PhotoImage(data=...) 显示。
"""
from __future__ import annotations

import base64
import io
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Optional

try:
    from PIL import Image

    HAS_PIL = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    HAS_PIL = False


# 优先使用带中文字形的字体：否则 Tk 在部分 Linux 上会用西文字体做逐字回退，
# 中文笔画会粘连、发虚（截图和投影上尤其明显）。
PREFERRED_FAMILIES = (
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "WenQuanYi Micro Hei",
    "Droid Sans Fallback",
    # 无 Xft 的精简 X11（部分 Xvfb / 瘦客户端）只有 X core 字体，
    # 其中 helvetica 带中文点阵字形，能正常显示中文。
    "helvetica",
    "song",
)

_NAMED_FONTS = (
    "TkDefaultFont",
    "TkTextFont",
    "TkMenuFont",
    "TkHeadingFont",
    "TkCaptionFont",
    "TkSmallCaptionFont",
    "TkIconFont",
    "TkTooltipFont",
)

_family: Optional[str] = None

# 这些是 X core 字体：没有真正的粗体中文，Tk 会用“双描边”模拟，中文会糊。
_CORE_FAMILIES = ("helvetica", "song", "fixed")


def ui_family(root: Optional[tk.Misc] = None) -> str:
    global _family
    if _family:
        return _family
    try:
        available = set(tkfont.families(root=root))
    except Exception:
        available = set()
    for name in PREFERRED_FAMILIES:
        if name in available:
            _family = name
            return name
    for name in ("helvetica", "song"):
        if name in available:
            _family = name
            return name
    try:
        _family = tkfont.nametofont("TkDefaultFont", root=root).actual("family")
    except Exception:
        _family = "TkDefaultFont"
    return _family


def heading_font(size: int, bold: bool = False) -> tuple:
    family = ui_family()
    if bold and family not in _CORE_FAMILIES:
        return (family, size, "bold")
    return (family, size)


def apply_ui_theme(root: tk.Misc) -> None:
    """统一字体与 ttk 主题，保证中文可读、三平台观感一致。"""
    family = ui_family(root)
    core = family in _CORE_FAMILIES
    # X core 字体小于 12pt 时中文点阵缺字，Tk 会拿西文字形凑，笔画会粘连。
    sizes = {
        "TkDefaultFont": 12,
        "TkTextFont": 12,
        "TkMenuFont": 12,
        "TkHeadingFont": 12,
        "TkCaptionFont": 12,
        "TkSmallCaptionFont": 11,
        "TkIconFont": 12,
        "TkTooltipFont": 11,
    }
    for name in _NAMED_FONTS:
        try:
            font = tkfont.nametofont(name, root=root)
            if core:
                font.configure(family=family, size=sizes.get(name, 12), weight="normal")
            else:
                font.configure(family=family)
        except tk.TclError:
            continue
    try:
        style = ttk.Style(root)
        if style.theme_use() in ("default", "classic") and "clam" in style.theme_names():
            style.theme_use("clam")
    except tk.TclError:
        pass


def jpeg_to_photo(
    data: bytes,
    max_width: int,
    max_height: int,
    master: Optional[tk.Misc] = None,
) -> Optional[tk.PhotoImage]:
    """把 JPEG 字节缩放后转成 Tk 可显示的 PhotoImage。"""
    if not HAS_PIL:
        return None
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((max(1, int(max_width)), max(1, int(max_height))), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payload = base64.b64encode(buffer.getvalue()).decode("ascii")
        return tk.PhotoImage(master=master, data=payload)
    except Exception:
        return None


def png_photo(data: bytes, master: Optional[tk.Misc] = None) -> Optional[tk.PhotoImage]:
    """PNG 字节直接交给 Tk。"""
    try:
        return tk.PhotoImage(master=master, data=base64.b64encode(data).decode("ascii"))
    except Exception:
        return None
