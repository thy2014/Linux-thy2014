"""老师端界面：学生列表、实时画面、全屏广播、锁键盘、群发消息。"""
from __future__ import annotations

import base64
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Dict, List, Optional

from ..common.capture import ScreenCapture
from ..common.discovery import TeacherDiscovery
from ..common.netutil import local_ipv4
from ..common.ui import HAS_PIL, apply_ui_theme, heading_font, jpeg_to_photo
from .server import TeacherServer


class TeacherApp:
    def __init__(self, cfg: dict, autostart: bool = True) -> None:
        self.cfg = cfg
        self.room = str(cfg["common"].get("room") or "默认班级")
        tcfg = cfg["teacher"]
        self.server = TeacherServer(
            port=int(tcfg.get("port", 45678)),
            bind=str(tcfg.get("bind", "0.0.0.0")),
            room=self.room,
            name=str(tcfg.get("name", "老师端")),
        )
        self.discovery: Optional[TeacherDiscovery] = None
        self.capture = ScreenCapture(
            max_width=int(tcfg.get("broadcast_width", 1280)),
            quality=int(tcfg.get("jpeg_quality", 60)),
        )
        self.fps = max(1, int(tcfg.get("broadcast_fps", 2)))
        self.selected_key: Optional[str] = None
        self._iids: Dict[str, str] = {}
        self._preview_photo = None
        self._preview_key: Optional[str] = None
        self._preview_seq = -1
        self._broadcasting = False
        self._broadcast_stop = threading.Event()
        self._broadcast_thread: Optional[threading.Thread] = None
        self._locked = False
        self._running = False

        self.root = tk.Tk()
        apply_ui_theme(self.root)
        self.root.title(f"ThyClass 老师端 · {self.room}")
        self.root.geometry("1120x720")
        self.root.minsize(900, 600)
        self._only_selected = tk.BooleanVar(master=self.root, value=False)
        self._status_var = tk.StringVar(value="正在启动…")
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._running = True
        if autostart:
            self.start_network()
        self._poll_id = self.root.after(200, self._poll)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        root = self.root
        header = ttk.Frame(root, padding=(16, 14, 16, 4))
        header.pack(fill="x")
        ttk.Label(header, text="ThyClass 老师端", font=heading_font(16, bold=True)).pack(
            side="left"
        )
        ttk.Label(header, text=f"班级：{self.room}", foreground="#666").pack(
            side="left", padx=(12, 0)
        )
        self._endpoint_label = ttk.Label(header, text="", foreground="#666")
        self._endpoint_label.pack(side="right")

        body = ttk.Panedwindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(6, 8))

        left = ttk.Frame(body)
        body.add(left, weight=1)
        ttk.Label(left, text="在线学生").pack(anchor="w", pady=(0, 4))
        holder = ttk.Frame(left)
        holder.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            holder, columns=("name", "ip", "state"), show="headings", selectmode="browse"
        )
        for column, title, width in (
            ("name", "姓名", 180),
            ("ip", "IP 地址", 130),
            ("state", "状态", 110),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(body, padding=(12, 0, 0, 0))
        body.add(right, weight=3)
        ttk.Label(right, text="画面预览").pack(anchor="w", pady=(0, 4))
        self.preview_frame = tk.Frame(right, bg="#111827")
        self.preview_frame.pack(fill="both", expand=True)
        self.preview_frame.pack_propagate(False)
        self.preview = tk.Canvas(
            self.preview_frame, bg="#111827", highlightthickness=0, bd=0
        )
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Configure>", self._on_preview_resize)
        self._preview_info = ttk.Label(right, text="", foreground="#666")
        self._preview_info.pack(anchor="w", pady=(6, 0))

        toolbar = ttk.Frame(root, padding=(16, 0, 16, 6))
        toolbar.pack(fill="x")
        self.btn_broadcast = ttk.Button(toolbar, text="开始广播", command=self.start_broadcast)
        self.btn_broadcast.pack(side="left")
        self.btn_stop = ttk.Button(
            toolbar, text="结束广播", command=self.stop_broadcast, state="disabled"
        )
        self.btn_stop.pack(side="left", padx=6)
        self.btn_lock = ttk.Button(toolbar, text="锁定学生键盘", command=lambda: self.set_lock(True))
        self.btn_lock.pack(side="left", padx=(16, 0))
        self.btn_unlock = ttk.Button(
            toolbar, text="解除锁定", command=lambda: self.set_lock(False), state="disabled"
        )
        self.btn_unlock.pack(side="left", padx=6)
        ttk.Button(toolbar, text="发送消息", command=self.send_message).pack(
            side="left", padx=(16, 0)
        )
        ttk.Checkbutton(
            toolbar, text="只发给选中的学生", variable=self._only_selected
        ).pack(side="right")

        status = ttk.Frame(root, padding=(16, 0, 16, 8))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self._status_var, foreground="#444").pack(anchor="w")

    # ------------------------------------------------------------------ 网络
    def start_network(self) -> None:
        try:
            port = self.server.start()
        except OSError as exc:
            self._status_var.set(f"服务启动失败：{exc}")
            return
        self._endpoint_label.configure(text=f"本机 {local_ipv4()} · TCP {port}")
        dcfg = self.cfg["common"]
        if dcfg.get("discovery", True):
            self.discovery = TeacherDiscovery(
                tcp_port=port,
                room=self.room,
                name=str(self.cfg["teacher"].get("name", "老师端")),
                discovery_port=int(dcfg.get("discovery_port", 45677)),
            )
            dport = self.discovery.start()
            if dport:
                self._status_var.set(f"服务已启动：TCP {port}，UDP 发现 {dport}")
            else:
                self._status_var.set(
                    f"服务已启动：TCP {port}；UDP 发现失败（{self.discovery.error}），"
                    "学生端请直接填老师 IP"
                )
        else:
            self._status_var.set(f"服务已启动：TCP {port}（已关闭自动发现）")

    # ------------------------------------------------------------------ 广播
    def _target_keys(self) -> Optional[List[str]]:
        if self._only_selected.get() and self.selected_key:
            return [self.selected_key]
        return None

    def start_broadcast(self) -> None:
        if self._broadcasting:
            return
        if self.server.count() == 0:
            messagebox.showinfo("开始广播", "当前还没有学生端在线。", parent=self.root)
            return
        keys = self._target_keys()
        self._broadcasting = True
        self._broadcast_stop = threading.Event()
        self.server.broadcast(
            {"t": "cmd", "cmd": "broadcast_start", "fps": self.fps}, keys
        )
        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop,
            args=(self._broadcast_stop, keys),
            daemon=True,
        )
        self._broadcast_thread.start()
        self.btn_broadcast.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._status_var.set(f"正在广播（{self.fps} 帧/秒）…")

    def _broadcast_loop(self, stop: threading.Event, keys: Optional[List[str]]) -> None:
        interval = 1.0 / max(1, self.fps)
        seq = 0
        while not stop.is_set():
            started = time.monotonic()
            frame = self.capture.grab()
            if frame is not None:
                seq += 1
                self.server.broadcast(
                    {
                        "t": "bcast",
                        "seq": seq,
                        "mime": frame.mime,
                        "w": frame.width,
                        "h": frame.height,
                        "data": base64.b64encode(frame.data).decode("ascii"),
                    },
                    keys,
                )
            stop.wait(max(0.05, interval - (time.monotonic() - started)))
        self.server.broadcast({"t": "cmd", "cmd": "broadcast_stop"}, keys)

    def stop_broadcast(self) -> None:
        if not self._broadcasting:
            return
        self._broadcasting = False
        self._broadcast_stop.set()
        self.server.broadcast({"t": "cmd", "cmd": "broadcast_stop"}, self._target_keys())
        if self._broadcast_thread is not None:
            self._broadcast_thread.join(timeout=1.0)
            self._broadcast_thread = None
        self.btn_broadcast.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._status_var.set("已结束广播")

    def set_lock(self, locked: bool) -> None:
        if self.server.count() == 0:
            messagebox.showinfo("键盘锁定", "当前还没有学生端在线。", parent=self.root)
            return
        self._locked = locked
        self.server.broadcast(
            {"t": "cmd", "cmd": "lock", "on": locked}, self._target_keys()
        )
        self.btn_lock.configure(state="disabled" if locked else "normal")
        self.btn_unlock.configure(state="normal" if locked else "disabled")
        self._status_var.set("已锁定学生键盘" if locked else "已解除学生键盘锁定")

    def send_message(self) -> None:
        text = simpledialog.askstring("发送消息", "要发送给学生的消息：", parent=self.root)
        if not text:
            return
        sent = self.server.broadcast(
            {"t": "cmd", "cmd": "message", "text": text}, self._target_keys()
        )
        self._status_var.set(f"消息已发送给 {sent} 名学生")

    # ------------------------------------------------------------------ 轮询
    def _poll(self) -> None:
        if not self._running:
            return
        try:
            self._drain_events()
            self._sync_tree()
            self._refresh_preview()
        except tk.TclError:
            return
        self._poll_id = self.root.after(300, self._poll)

    def _sync_tree(self) -> None:
        conns = self.server.students()
        alive = set()
        for conn in conns:
            alive.add(conn.key)
            state = "共享中" if conn.sharing else "已暂停"
            if conn.locked:
                state += " · 锁键"
            if conn.net == "offline":
                state += " · 断网"
            iid = self._iids.get(conn.key)
            if iid is None:
                iid = self.tree.insert("", "end", values=(conn.name, conn.ip, state))
                self._iids[conn.key] = iid
            else:
                self.tree.item(iid, values=(conn.name, conn.ip, state))
        for key, iid in list(self._iids.items()):
            if key not in alive:
                try:
                    self.tree.delete(iid)
                except tk.TclError:
                    pass
                self._iids.pop(key, None)
        if self.selected_key and self.selected_key not in alive:
            self.selected_key = None
            self._preview_key = None
            self._preview_seq = -1
        if self.selected_key is None and self._iids:
            first = next(iter(self._iids))
            self.selected_key = first
            self.tree.selection_set(self._iids[first])
        self._endpoint_label.configure(
            text=f"本机 {local_ipv4()} · TCP {self.server.port} · 在线 {len(conns)}"
        )

    def _drain_events(self) -> None:
        for kind, payload in self.server.drain_events():
            if kind == "event":
                key, msg = payload
                conn = self.server.get(key)
                name = conn.name if conn is not None else key
                what = msg.get("what")
                if what == "escape":
                    self._status_var.set(f"{name} 通过紧急解锁退出了广播")
                elif what == "screen_release":
                    self._status_var.set(f"{name} 释放了本机全屏窗口")
                elif what == "broadcast_exit":
                    self._status_var.set(f"{name} 退出了 ThyClass 广播")
            elif kind == "student_joined":
                self._status_var.set(f"{payload.name} 已上线（{payload.ip}）")
            elif kind == "student_left":
                self._status_var.set(f"{payload.name} 已下线（{payload.ip}）")

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        for key, iid in self._iids.items():
            if iid == selection[0]:
                self.selected_key = key
                self._preview_seq = -1
                return

    def _on_preview_resize(self, _event=None) -> None:
        if self._preview_photo is None:
            self._preview_clear()

    def _preview_clear(self) -> None:
        self._preview_photo = None
        self._preview_key = None
        self._preview_seq = -1
        try:
            self.preview.delete("all")
            width = max(2, self.preview.winfo_width())
            height = max(2, self.preview.winfo_height())
            self.preview.create_text(
                width // 2, height // 2, text="选择左侧学生即可查看其屏幕", fill="#9ca3af"
            )
        except tk.TclError:
            pass

    def _refresh_preview(self) -> None:
        conn = self.server.get(self.selected_key) if self.selected_key else None
        if conn is None or conn.frame is None:
            if self._preview_key is not None:
                self._preview_clear()
                self._preview_info.configure(text="")
            return
        if conn.key == self._preview_key and conn.frame_seq == self._preview_seq:
            return
        if not HAS_PIL:
            self._preview_clear()
            self._preview_info.configure(text="需要安装 Pillow 才能显示学生画面")
            return
        width = max(320, self.preview.winfo_width()) - 16
        height = max(220, self.preview.winfo_height()) - 16
        photo = jpeg_to_photo(conn.frame, width, height, master=self.root)
        if photo is None:
            return
        self._preview_photo = photo
        try:
            self.preview.delete("all")
            self.preview.create_image(
                max(2, self.preview.winfo_width()) // 2,
                max(2, self.preview.winfo_height()) // 2,
                image=photo,
            )
        except tk.TclError:
            return
        self._preview_key = conn.key
        self._preview_seq = conn.frame_seq
        stamp = time.strftime("%H:%M:%S", time.localtime(conn.frame_ts))
        self._preview_info.configure(
            text=f"{conn.name} · {conn.ip} · {conn.os_name or '未知系统'} · 画面 {stamp}"
        )

    # ------------------------------------------------------------------ 生命周期
    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        self._running = False
        self._broadcast_stop.set()
        try:
            self.root.after_cancel(self._poll_id)
        except (tk.TclError, AttributeError):
            pass
        if self.discovery is not None:
            self.discovery.stop()
            self.discovery = None
        self.server.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self._status_var = None
        self._only_selected = None


def main(cfg: dict) -> None:
    TeacherApp(cfg).run()
