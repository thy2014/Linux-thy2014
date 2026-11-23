"""学生端界面：连接老师、屏幕共享开关、一键断网、接收全屏广播。"""
from __future__ import annotations

import base64
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from .. import __version__
from ..common.capture import ScreenCapture
from ..common.keylock import create_keyboard_lock
from ..common.netcut import NetworkSwitch
from ..common.screen_release import expand_window_ids, release_fullscreen
from ..common.ui import HAS_PIL, apply_ui_theme, heading_font, jpeg_to_photo
from ..config import default_device_name
from .client import StudentClient


class StudentApp:
    def __init__(self, cfg: dict, autostart: bool = True) -> None:
        self.cfg = cfg
        scfg = cfg["student"]
        self.name = str(scfg.get("name") or "").strip() or default_device_name()
        self.allow_escape = bool(scfg.get("allow_keyboard_escape", True))
        self.unlock_code = str(scfg.get("unlock_code") or "")
        self.show_notice = bool(scfg.get("show_sharing_notice", True))
        self.release_enabled = bool(scfg.get("screen_release", True))
        self.release_attempts = max(1, int(scfg.get("release_attempts", 3)))
        self.net = NetworkSwitch()
        self.client = StudentClient(
            cfg,
            on_event=self._on_client_event,
            capture=ScreenCapture(
                max_width=int(scfg.get("share_width", 720)),
                quality=int(scfg.get("jpeg_quality", 55)),
            ),
            autostart_share=bool(scfg.get("share_on_start", True)),
        )
        self.sharing = self.client.sharing
        self.overlay: Optional[tk.Toplevel] = None
        self.overlay_canvas: Optional[tk.Canvas] = None
        self.locker = None
        self._overlay_photo = None
        self._overlay_text = "老师正在广播，请稍候…"
        self._release_busy = False
        self.broadcast_active = False
        self._closing = False
        self._net_busy = False

        self.root = tk.Tk()
        apply_ui_theme(self.root)
        self.root.title(f"ThyClass 学生端 · {self.name}")
        self.root.geometry("580x460")
        self.root.minsize(480, 380)
        self._status_var = tk.StringVar(value="未连接")
        self._detail_var = tk.StringVar(value="正在查找老师端…")
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if autostart:
            self.client.start()
        self._poll_id = self.root.after(500, self._poll)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        root = self.root
        header = ttk.Frame(root, padding=(16, 14, 16, 4))
        header.pack(fill="x")
        ttk.Label(header, text="ThyClass 学生端", font=heading_font(16, bold=True)).pack(
            side="left"
        )
        ttk.Label(header, text=self.name, foreground="#666").pack(side="left", padx=(10, 0))

        card = ttk.LabelFrame(root, text="连接状态", padding=14)
        card.pack(fill="x", padx=16, pady=(10, 8))
        ttk.Label(card, textvariable=self._status_var, font=heading_font(13)).pack(
            anchor="w"
        )
        ttk.Label(
            card, textvariable=self._detail_var, foreground="#666", wraplength=500
        ).pack(anchor="w", pady=(6, 0))

        actions = ttk.Frame(root, padding=(16, 0))
        actions.pack(fill="x")
        self.share_btn = ttk.Button(
            actions, text="屏幕共享：开" if self.sharing else "屏幕共享：暂停",
            command=self.toggle_sharing,
        )
        self.share_btn.pack(side="left", padx=(0, 8))
        self.net_btn = ttk.Button(actions, text="一键断网", command=self.toggle_network)
        self.net_btn.pack(side="left", padx=8)
        self.stop_btn = ttk.Button(
            actions, text="结束广播", command=self.request_escape, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=8)
        self.release_btn = None
        if self.release_enabled:
            self.release_btn = ttk.Button(
                actions, text="解除全屏广播", command=self.release_fullscreen_broadcast
            )
            self.release_btn.pack(side="left", padx=8)

        if self.show_notice:
            ttk.Label(
                root,
                text="提示：老师端可查看本机屏幕，随时点“屏幕共享”即可暂停。",
                foreground="#777",
                wraplength=520,
                padding=(16, 12, 16, 0),
            ).pack(anchor="w")
        ttk.Label(
            root,
            text=f"广播时可长按紧急组合键 Ctrl+Alt+Shift+Q 解锁 · v{__version__}",
            foreground="#999",
            wraplength=520,
            padding=(16, 8, 16, 0),
        ).pack(anchor="w")

        footer = ttk.Frame(root, padding=(16, 12))
        footer.pack(fill="x", side="bottom")
        ttk.Button(footer, text="退出程序", command=self.close).pack(side="right")

    # ------------------------------------------------------------------ 事件
    def _on_client_event(self, msg: dict) -> None:
        if self._closing:
            return
        try:
            self.root.after(0, lambda: self._handle_event(msg))
        except (tk.TclError, RuntimeError):
            pass

    def _handle_event(self, msg: dict) -> None:
        if self._closing:
            return
        kind = msg.get("t")
        if kind == "local":
            what = msg.get("what")
            if what == "connected":
                teacher = msg.get("teacher", {})
                self._status_var.set("已连接老师端")
                self._detail_var.set(
                    f"{teacher.get('teacher', '老师')} · {teacher.get('room', '')}"
                )
                self.client.notify(
                    {
                        "t": "status",
                        "sharing": self.sharing,
                        "net": "offline" if self.net.offline else "online",
                    }
                )
            elif what == "discovery_failed":
                self._status_var.set("未找到老师端")
                self._detail_var.set(
                    "正在自动重试；也可以在 ~/.thyclass/config.json 里填写 teacher_host"
                )
            elif what == "connect_failed":
                self._status_var.set("连接失败，正在重试")
                self._detail_var.set(str(msg.get("error", "")))
            elif what == "disconnected":
                self._status_var.set("与老师端断开，正在重连")
                if self.broadcast_active:
                    self._stop_broadcast(auto=True)
        elif kind == "bcast":
            if not self.broadcast_active:
                self._start_broadcast()
            self._render_frame(msg)
        elif kind == "cmd":
            self._handle_cmd(msg)

    def _handle_cmd(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "broadcast_start":
            self._start_broadcast()
        elif cmd == "broadcast_stop":
            self._stop_broadcast()
        elif cmd == "lock":
            locked = bool(msg.get("on"))
            self._detail_var.set(
                "老师已锁定键盘（按 Ctrl+Alt+Shift+Q 可解锁）"
                if locked
                else "老师已解除键盘锁定"
            )
        elif cmd == "message":
            messagebox.showinfo(
                "老师消息", str(msg.get("text", "")), parent=self.overlay or self.root
            )
        elif cmd == "share":
            self.set_sharing(bool(msg.get("on")), from_teacher=True)

    # ------------------------------------------------------------------ 广播
    def _start_broadcast(self) -> None:
        if self.overlay is not None:
            return
        top = tk.Toplevel(self.root)
        top.title("老师广播")
        top.overrideredirect(True)
        width = top.winfo_screenwidth()
        height = top.winfo_screenheight()
        top.geometry(f"{width}x{height}+0+0")
        top.configure(bg="#000000")
        canvas = tk.Canvas(top, bg="#000000", highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", lambda _event: self._overlay_draw())
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass
        top.lift()
        top.focus_force()
        self.overlay = top
        self.overlay_canvas = canvas
        self._overlay_photo = None
        self._overlay_text = "老师正在广播，请稍候…"
        self._overlay_draw()
        self.locker = create_keyboard_lock(
            top, allow_escape=self.allow_escape, on_escape=self.request_escape
        )
        self.locker.start()
        self.broadcast_active = True
        self.stop_btn.configure(state="normal")
        detail = "全屏广播接收中"
        if self.locker is not None and self.locker.active:
            detail += f" · {self.locker.describe()}"
        self._detail_var.set(detail)

    def _overlay_draw(self) -> None:
        canvas = self.overlay_canvas
        if canvas is None:
            return
        try:
            canvas.delete("all")
            width = max(2, canvas.winfo_width())
            height = max(2, canvas.winfo_height())
            if self._overlay_photo is not None:
                canvas.create_image(width // 2, height // 2, image=self._overlay_photo)
            else:
                canvas.create_text(
                    width // 2,
                    height // 2,
                    text=self._overlay_text,
                    fill="#e5e7eb",
                    font=heading_font(20),
                )
        except tk.TclError:
            pass

    def _render_frame(self, msg: dict) -> None:
        if self.overlay is None or self.overlay_canvas is None:
            return
        data = msg.get("data")
        if not isinstance(data, str):
            return
        if not HAS_PIL:
            self._overlay_text = "收到广播画面（安装 Pillow 后可显示）"
            self._overlay_draw()
            return
        try:
            raw = base64.b64decode(data)
        except (ValueError, TypeError):
            return
        width = max(320, self.overlay.winfo_screenwidth())
        height = max(240, self.overlay.winfo_screenheight())
        photo = jpeg_to_photo(raw, width, height, master=self.root)
        if photo is None:
            return
        self._overlay_photo = photo
        self._overlay_draw()

    def _stop_broadcast(self, auto: bool = False) -> None:
        if self.locker is not None:
            try:
                self.locker.stop()
            except Exception:
                pass
            self.locker = None
        if self.overlay is not None:
            try:
                self.overlay.destroy()
            except tk.TclError:
                pass
        self.overlay = None
        self.overlay_canvas = None
        self._overlay_photo = None
        self.broadcast_active = False
        if not self._closing:
            try:
                self.stop_btn.configure(state="disabled")
                self._detail_var.set("广播已结束" if auto else "已退出广播")
            except tk.TclError:
                pass

    def request_escape(self) -> None:
        if not self.broadcast_active:
            return
        parent = self.overlay or self.root
        locker = self.locker
        if locker is not None:
            locker.stop()  # 临时放行键盘，否则对话框收不到输入
        released = True
        try:
            if self.unlock_code:
                entered = simpledialog.askstring(
                    "解除广播", "请输入老师提供的解锁码：", show="*", parent=parent
                )
                if entered != self.unlock_code:
                    if entered is not None:
                        messagebox.showwarning("解锁失败", "解锁码不正确。", parent=parent)
                    return
            else:
                if not messagebox.askyesno(
                    "解除广播",
                    "确定退出全屏广播吗？\n退出事件会记录并显示在老师端。",
                    parent=parent,
                ):
                    return
            self._stop_broadcast()
            self.client.notify(
                {"t": "event", "what": "escape", "at": time.time(), "name": self.name}
            )
            released = False
        finally:
            if released and self.broadcast_active and self.locker is not None:
                self.locker.start()

    # ------------------------------------------------------------------ 操作
    def set_sharing(self, sharing: bool, from_teacher: bool = False) -> None:
        self.sharing = bool(sharing)
        self.client.set_sharing(self.sharing)
        try:
            self.share_btn.configure(
                text="屏幕共享：开" if self.sharing else "屏幕共享：暂停"
            )
        except tk.TclError:
            pass
        if from_teacher:
            self._detail_var.set(
                "老师已恢复查看你的屏幕" if self.sharing else "老师已暂停查看你的屏幕"
            )

    def toggle_sharing(self) -> None:
        self.set_sharing(not self.sharing)

    def toggle_network(self) -> None:
        if self._net_busy:
            return
        target_offline = not self.net.offline
        prompt = (
            "断网后本机将无法上网，也会与老师端断开，确定继续吗？"
            if target_offline
            else "恢复网络连接？"
        )
        if not messagebox.askyesno("网络切换", prompt, parent=self.root):
            return
        self._net_busy = True
        self.net_btn.configure(state="disabled", text="处理中…")

        def worker() -> None:
            ok, message = self.net.set_offline(target_offline)
            self.root.after(0, lambda: self._net_done(ok, message))

        threading.Thread(target=worker, daemon=True).start()

    def _net_done(self, ok: bool, message: str) -> None:
        self._net_busy = False
        try:
            self.net_btn.configure(
                state="normal",
                text="恢复网络" if self.net.offline else "一键断网",
            )
        except tk.TclError:
            pass
        self.client.notify(
            {
                "t": "status",
                "sharing": self.sharing,
                "net": "offline" if self.net.offline else "online",
            }
        )
        (messagebox.showinfo if ok else messagebox.showwarning)(
            "网络切换", message, parent=self.root
        )

    # ------------------------------------------------------------------ 全屏释放
    def release_fullscreen_broadcast(self) -> None:
        """把本机当前铺满屏幕的窗口（例如第三方课堂广播）取消显示。"""
        if self.broadcast_active:
            self._stop_broadcast()
            self._detail_var.set("已退出 ThyClass 广播")
            self.client.notify(
                {"t": "event", "what": "broadcast_exit", "at": time.time(), "name": self.name}
            )
            return
        if not self.release_enabled or self.release_btn is None or self._release_busy:
            return
        if not messagebox.askyesno(
            "解除全屏广播",
            "将把本机当前铺满屏幕的窗口取消显示。\n"
            "只影响本机显示，不修改任何软件；老师端重新广播后会再次出现。继续吗？",
            parent=self.root,
        ):
            return
        self._release_busy = True
        self.release_btn.configure(state="disabled", text="处理中…")
        exclude = self._own_window_ids()

        def worker() -> None:
            result = release_fullscreen(
                repeat=self.release_attempts, exclude_ids=exclude
            )
            self.root.after(0, lambda: self._release_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _own_window_ids(self) -> set:
        ids = set()
        try:
            ids.add(int(self.root.winfo_id()))
            for child in self.root.winfo_children():
                try:
                    ids.add(int(child.winfo_id()))
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
        return expand_window_ids(ids)

    def _release_done(self, result) -> None:
        self._release_busy = False
        if self.release_btn is not None:
            try:
                self.release_btn.configure(state="normal", text="解除全屏广播")
            except tk.TclError:
                pass
        self._detail_var.set(result.message)
        messagebox.showinfo("解除全屏广播", result.message, parent=self.root)
        if result.ok:
            self.client.notify(
                {
                    "t": "event",
                    "what": "screen_release",
                    "at": time.time(),
                    "name": self.name,
                    "backend": result.backend,
                }
            )

    # ------------------------------------------------------------------ 生命周期
    def _poll(self) -> None:
        if self._closing:
            return
        try:
            if self.client.connected:
                if self._status_var.get() in ("未连接", "与老师端断开，正在重连"):
                    self._status_var.set("已连接老师端")
            if self.broadcast_active and self.locker is not None:
                if not self.locker.active:
                    self.locker.start()
        except tk.TclError:
            return
        self._poll_id = self.root.after(500, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    def close(self, confirm: bool = True) -> None:
        if self._closing:
            return
        if confirm and not messagebox.askyesno(
            "退出", "确定退出 ThyClass 学生端吗？", parent=self.root
        ):
            return
        self._closing = True
        try:
            self.root.after_cancel(self._poll_id)
        except (tk.TclError, AttributeError):
            pass
        self._stop_broadcast(auto=True)
        self.client.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self._status_var = None
        self._detail_var = None


def main(cfg: dict) -> None:
    StudentApp(cfg).run()
