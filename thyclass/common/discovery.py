"""UDP 自动发现。

学生端周期性广播 HELLO（UDP:45677），老师端监听后回一条 teacher 应答，
内含老师端 TCP 端口。学生端也可以用配置里的 teacher_host 直接连，
不依赖广播——有些校园网会屏蔽组播/广播。
"""
from __future__ import annotations

import json
import socket
import threading
import time
from typing import Callable, List, Optional, Tuple

from .. import __version__
from .netutil import broadcast_targets

DISCOVERY_PORT = 45677
HELLO_INTERVAL = 1.0


class DiscoveryBeacon:
    """学生端使用：找一个在线老师端。"""

    def __init__(
        self,
        tcp_port: int,
        name: str,
        room: str = "",
        discovery_port: int = DISCOVERY_PORT,
        hosts: Optional[List[str]] = None,
    ) -> None:
        self.tcp_port = tcp_port
        self.name = name
        self.room = room
        self.discovery_port = discovery_port
        self.hosts = hosts

    def _targets(self) -> List[str]:
        return list(self.hosts) if self.hosts else broadcast_targets()

    def find_teacher(self, timeout: float = 4.0) -> Optional[Tuple[str, int]]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        deadline = time.monotonic() + timeout
        try:
            sock.bind(("", 0))
            next_hello = 0.0
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_hello:
                    payload = json.dumps(
                        {
                            "t": "hello",
                            "app": "thyclass",
                            "ver": __version__,
                            "name": self.name,
                            "room": self.room,
                            "port": self.tcp_port,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                    for host in self._targets():
                        try:
                            sock.sendto(payload, (host, self.discovery_port))
                        except OSError:
                            continue
                    next_hello = now + HELLO_INTERVAL
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    msg = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if msg.get("t") == "teacher":
                    try:
                        port = int(msg.get("port", 45678))
                    except (TypeError, ValueError):
                        continue
                    return addr[0], port
        finally:
            sock.close()
        return None


class TeacherDiscovery:
    """老师端使用：应答学生 HELLO。"""

    def __init__(
        self,
        tcp_port: int,
        room: str = "",
        name: str = "",
        discovery_port: int = DISCOVERY_PORT,
        host: str = "0.0.0.0",
        on_hello: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        self.tcp_port = tcp_port
        self.room = room
        self.name = name
        self.discovery_port = discovery_port
        self.host = host
        self.on_hello = on_hello
        self.port = discovery_port
        self.error = ""
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> int:
        """绑定端口并启动应答线程，返回实际监听端口（失败返回 0）。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.discovery_port))
        except OSError as exc:
            self.error = str(exc)
            sock.close()
            return 0
        sock.settimeout(0.5)
        self._sock = sock
        self.port = sock.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self.port

    def _run(self) -> None:
        assert self._sock is not None
        reply = json.dumps(
            {
                "t": "teacher",
                "app": "thyclass",
                "ver": __version__,
                "port": self.tcp_port,
                "room": self.room,
                "name": self.name,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if msg.get("t") != "hello":
                continue
            try:
                self._sock.sendto(reply, addr)
            except OSError:
                continue
            if self.on_hello is not None:
                try:
                    self.on_hello(addr[0], msg)
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
