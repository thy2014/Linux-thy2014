"""在 Xvfb / 真实桌面上生成文档用的界面截图。

用法：
    xvfb-run -a -s "-screen 0 1280x1024x24" python3 tools/make_screenshots.py
"""
from __future__ import annotations

import base64
import copy
import io
import os
import socket
import sys
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageGrab

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thyclass.common.protocol import LineSocket
from thyclass.config import DEFAULT_CONFIG
from thyclass.student.app import StudentApp
from thyclass.teacher.app import TeacherApp

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots")


def pump(root: tk.Misc, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            root.update()
        except tk.TclError:
            return
        time.sleep(0.02)


def crop_window(root: tk.Tk, path: str) -> None:
    root.update_idletasks()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    shot = ImageGrab.grab()
    shot.crop((x, y, x + w, y + h)).save(path)


CJK_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def _font(size: int):
    try:
        return ImageFont.truetype(CJK_FONT, size)
    except OSError:
        return ImageFont.load_default()


def fake_desktop(width: int = 1280, height: int = 720) -> bytes:
    img = Image.new("RGB", (width, height), "#0b1220")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 44], fill="#1f2937")
    draw.text((18, 12), "模拟学生桌面 · 六年级一班", fill="#e5e7eb", font=_font(18))
    for i, (name, color) in enumerate(
        [("浏览器", "#2563eb"), ("文档", "#059669"), ("画图", "#d97706"), ("回收站", "#6b7280")]
    ):
        x = 90 + i * 150
        draw.rounded_rectangle([x, 110, x + 96, 206], radius=12, fill=color)
        draw.text((x + 20, 220), name, fill="#cbd5e1", font=_font(16))
    draw.rectangle([120, 300, 800, 620], fill="#111827", outline="#374151")
    draw.text((150, 330), "课堂练习：分数加减法", fill="#f9fafb", font=_font(22))
    draw.text((150, 380), "1/2 + 1/3 = 5/6", fill="#93c5fd", font=_font(20))
    draw.text((150, 430), "3/4 - 1/4 = 1/2", fill="#93c5fd", font=_font(20))
    draw.text((150, 500), "提交时间：18:20 前", fill="#94a3b8", font=_font(18))
    draw.text((900, 400), "ThyClass 演示画面", fill="#64748b", font=_font(18))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def teacher_shot() -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["common"]["room"] = "六年级一班"
    cfg["teacher"]["port"] = 0
    cfg["teacher"]["broadcast_width"] = 1280
    app = TeacherApp(cfg, autostart=True)
    app.root.geometry("1120x800+24+24")
    pump(app.root, 0.6)

    sock = socket.create_connection(("127.0.0.1", app.server.port), timeout=3)
    link = LineSocket(sock)
    link.send(
        {
            "t": "register",
            "app": "thyclass",
            "ver": "1.0.0",
            "name": "六年级-01",
            "room": "六年级一班",
            "os": "Linux arm64",
        }
    )
    link.recv(3.0)
    link.send({"t": "status", "sharing": True, "locked": False, "net": "online"})
    jpeg = fake_desktop()
    img = Image.open(io.BytesIO(jpeg))
    link.send(
        {
            "t": "frame",
            "seq": 1,
            "mime": "image/jpeg",
            "w": img.width,
            "h": img.height,
            "data": base64.b64encode(jpeg).decode("ascii"),
        }
    )
    pump(app.root, 1.4)
    app._status_var.set("服务已启动：TCP %d，UDP 发现 45677" % app.server.port)
    pump(app.root, 0.3)
    os.makedirs(OUT, exist_ok=True)
    crop_window(app.root, os.path.join(OUT, "teacher.png"))
    link.close()
    app.close()


def student_shot() -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["common"]["room"] = "六年级一班"
    cfg["student"]["name"] = "六年级-01"
    cfg["student"]["teacher_host"] = "192.168.1.10"
    app = StudentApp(cfg, autostart=False)
    app.root.geometry("580x460+40+40")
    pump(app.root, 0.4)
    app._status_var.set("已连接老师端")
    app._detail_var.set("老师端 · 六年级一班")
    pump(app.root, 0.3)
    os.makedirs(OUT, exist_ok=True)
    crop_window(app.root, os.path.join(OUT, "student.png"))

    # 广播遮罩：模拟老师正在广播
    app._start_broadcast()
    pump(app.root, 0.3)
    frame = fake_desktop(1280, 800)
    img = Image.open(io.BytesIO(frame))
    app._render_frame(
        {
            "t": "bcast",
            "seq": 1,
            "mime": "image/jpeg",
            "w": img.width,
            "h": img.height,
            "data": base64.b64encode(frame).decode("ascii"),
        }
    )
    pump(app.root, 0.8)
    shot = ImageGrab.grab()
    shot.save(os.path.join(OUT, "student-broadcast.png"))
    app._stop_broadcast()
    app.close(confirm=False)


if __name__ == "__main__":
    teacher_shot()
    student_shot()
    print("screenshots ->", OUT)
    for name in sorted(os.listdir(OUT)):
        print(" ", name)
