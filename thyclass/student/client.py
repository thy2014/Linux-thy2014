"""学生端连接逻辑：发现老师 → 连接 → 收指令、发画面。"""
from __future__ import annotations

import base64
import socket
import threading
import time
from typing import Callable, Optional

from .. import __version__
from ..common.capture import ScreenCapture
from ..common.discovery import DiscoveryBeacon
from ..common.protocol import LineSocket, ProtocolError

_TIMEOUT = object()


class StudentClient:
    def __init__(
        self,
        cfg: dict,
        on_event: Optional[Callable[[dict], None]] = None,
        capture: Optional[ScreenCapture] = None,
        send_frames: bool = True,
        autostart_share: bool = True,
    ) -> None:
        self.cfg = cfg
        scfg = cfg["student"]
        common = cfg["common"]
        self.name = str(scfg.get("name") or "").strip()
        self.room = str(scfg.get("room") or common.get("room") or "")
        self.teacher_host = str(scfg.get("teacher_host") or "").strip()
        self.teacher_port = int(scfg.get("teacher_port", 45678))
        self.share_interval = max(0.5, float(scfg.get("share_interval", 3.0)))
        self.discovery_port = int(common.get("discovery_port", 45677))
        self.discovery_enabled = bool(common.get("discovery", True))
        self.on_event = on_event
        self.capture = capture
        self.send_frames = send_frames
        self.sharing = bool(autostart_share)
        self.connected = False
        self.teacher_info: dict = {}
        self.last_error = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._link: Optional[LineSocket] = None
        self._seq = 0

    # ------------------------------------------------------------------ 控制
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        link = self._link
        if link is not None:
            try:
                link.send({"t": "bye"})
            except OSError:
                pass
            link.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def set_sharing(self, sharing: bool) -> None:
        self.sharing = sharing
        self.notify({"t": "status", "sharing": sharing})

    def notify(self, msg: dict) -> bool:
        link = self._link
        if link is None:
            return False
        try:
            link.send(msg)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ 内部
    def _emit(self, msg: dict) -> None:
        if self.on_event is not None:
            try:
                self.on_event(msg)
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            endpoint = self._find_teacher()
            if endpoint is None:
                self._emit({"t": "local", "what": "discovery_failed"})
                self._stop.wait(2.0)
                continue
            sock = None
            try:
                sock = socket.create_connection(endpoint, timeout=4.0)
                sock.settimeout(5.0)
                link = LineSocket(sock)
                link.send(
                    {
                        "t": "register",
                        "app": "thyclass",
                        "ver": __version__,
                        "name": self.name,
                        "room": self.room,
                        "os": _os_label(),
                    }
                )
                welcome = link.recv(5.0)
                if not welcome or welcome.get("t") != "welcome":
                    raise OSError("握手失败：对方不是 ThyClass 老师端")
                self._link = link
                self.connected = True
                self.teacher_info = welcome
                self.last_error = ""
                self._emit({"t": "local", "what": "connected", "teacher": welcome,
                            "endpoint": endpoint})
                self._serve(link)
            except (OSError, TimeoutError, ProtocolError) as exc:
                self.last_error = str(exc)
                self._emit({"t": "local", "what": "connect_failed", "error": str(exc)})
            finally:
                self.connected = False
                self._link = None
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            if not self._stop.is_set():
                self._emit({"t": "local", "what": "disconnected"})
                self._stop.wait(1.5)

    def _find_teacher(self) -> Optional[tuple]:
        if self.teacher_host:
            return self.teacher_host, self.teacher_port
        if not self.discovery_enabled:
            return None
        beacon = DiscoveryBeacon(
            tcp_port=0,
            name=self.name,
            room=self.room,
            discovery_port=self.discovery_port,
        )
        return beacon.find_teacher(timeout=3.0)

    def _serve(self, link: LineSocket) -> None:
        assert link.sock is not None
        link.sock.settimeout(0.2)
        next_frame = time.monotonic()
        while not self._stop.is_set():
            try:
                msg = link.recv(0.2)
            except TimeoutError:
                msg = _TIMEOUT
            except (OSError, ProtocolError):
                break
            if msg is None:
                break
            if msg is not _TIMEOUT:
                if msg.get("t") == "cmd" and msg.get("cmd") == "bye":
                    break
                self._emit(msg)
            now = time.monotonic()
            if (
                self.send_frames
                and self.sharing
                and self.capture is not None
                and now >= next_frame
            ):
                self._send_frame(link)
                next_frame = time.monotonic() + self.share_interval

    def _send_frame(self, link: LineSocket) -> None:
        frame = self.capture.grab() if self.capture is not None else None
        if frame is None:
            return
        self._seq += 1
        try:
            link.sock.settimeout(5.0)
            link.send(
                {
                    "t": "frame",
                    "seq": self._seq,
                    "mime": frame.mime,
                    "w": frame.width,
                    "h": frame.height,
                    "data": base64.b64encode(frame.data).decode("ascii"),
                }
            )
        except OSError:
            pass
        finally:
            try:
                link.sock.settimeout(0.2)
            except OSError:
                pass


def _os_label() -> str:
    import os
    import platform

    system = platform.system() or os.name
    machine = platform.machine() or ""
    return f"{system} {machine}".strip()
