"""老师端 TCP 服务：维护学生连接、下发指令、接收学生画面。"""
from __future__ import annotations

import base64
import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..common.protocol import LineSocket, ProtocolError


@dataclass
class StudentConn:
    key: str
    sock: socket.socket
    link: LineSocket
    addr: tuple
    name: str = "未命名"
    room: str = ""
    os_name: str = ""
    version: str = ""
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    frame: Optional[bytes] = None
    frame_seq: int = -1
    frame_ts: float = 0.0
    sharing: bool = True
    locked: bool = False
    net: str = "online"

    @property
    def ip(self) -> str:
        return str(self.addr[0])


class TeacherServer:
    """线程模型：1 个 accept 线程 + 每个学生 1 个读线程。"""

    def __init__(
        self,
        port: int = 45678,
        bind: str = "0.0.0.0",
        room: str = "默认班级",
        name: str = "老师端",
    ) -> None:
        self.requested_port = int(port)
        self.port = int(port)
        self.bind = bind
        self.room = room
        self.name = name
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self._students: Dict[str, StudentConn] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._lsock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None

    # -------------------------------------------------------------- 生命周期
    def start(self) -> int:
        lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lsock.bind((self.bind, self.requested_port))
        lsock.listen(64)
        lsock.settimeout(0.5)
        self._lsock = lsock
        self.port = int(lsock.getsockname()[1])
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._lsock is not None:
            try:
                self._lsock.close()
            except OSError:
                pass
        with self._lock:
            conns = list(self._students.values())
            self._students.clear()
        for conn in conns:
            conn.link.close()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1.0)

    # -------------------------------------------------------------- 对外操作
    def students(self) -> List[StudentConn]:
        with self._lock:
            return list(self._students.values())

    def get(self, key: str) -> Optional[StudentConn]:
        with self._lock:
            return self._students.get(key)

    def count(self) -> int:
        with self._lock:
            return len(self._students)

    def send(self, key: str, msg: dict) -> bool:
        conn = self.get(key)
        if conn is None:
            return False
        try:
            conn.link.send(msg)
            return True
        except OSError:
            self._drop(conn)
            return False

    def broadcast(self, msg: dict, keys: Optional[List[str]] = None) -> int:
        """返回成功发送的人数。"""
        if keys is None:
            targets = self.students()
        else:
            targets = [c for c in self.students() if c.key in set(keys)]
        sent = 0
        for conn in targets:
            try:
                conn.link.send(msg)
                sent += 1
            except OSError:
                self._drop(conn)
        return sent

    def drain_events(self) -> List[tuple]:
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                break
        return items

    # ---------------------------------------------------------------- 内部实现
    def _accept_loop(self) -> None:
        assert self._lsock is not None
        while not self._stop.is_set():
            try:
                sock, addr = self._lsock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(10.0)
            threading.Thread(
                target=self._serve, args=(sock, addr), daemon=True
            ).start()

    def _serve(self, sock: socket.socket, addr: tuple) -> None:
        link = LineSocket(sock)
        conn: Optional[StudentConn] = None
        try:
            first = link.recv(10.0)
            if not first or first.get("t") != "register":
                return
            conn = self._register(link, sock, addr, first)
            while not self._stop.is_set():
                try:
                    msg = link.recv(1.0)
                except TimeoutError:
                    continue
                if msg is None:
                    break
                if not self._dispatch(conn, msg):
                    break
        except (TimeoutError, ProtocolError, OSError):
            pass
        finally:
            if conn is not None:
                self._drop(conn)
            link.close()

    def _register(
        self, link: LineSocket, sock: socket.socket, addr: tuple, msg: dict
    ) -> StudentConn:
        name = str(msg.get("name") or "未命名").strip()[:40] or "未命名"
        with self._lock:
            existing = self._students.get(name)
            if existing is not None and existing.addr[0] != addr[0]:
                key = f"{name}#{addr[0]}"
            else:
                key = name
            old = self._students.get(key)
            if old is not None and old.link is not link:
                try:
                    old.link.close()
                except OSError:
                    pass
                self._students.pop(key, None)
                self.events.put(("student_left", old))
            conn = StudentConn(
                key=key,
                sock=sock,
                link=link,
                addr=addr,
                name=name,
                room=str(msg.get("room", self.room)),
                os_name=str(msg.get("os", ""))[:40],
                version=str(msg.get("ver", ""))[:20],
            )
            self._students[key] = conn
        try:
            link.send(
                {
                    "t": "welcome",
                    "app": "thyclass",
                    "teacher": self.name,
                    "room": self.room,
                    "server_time": time.time(),
                }
            )
        except OSError:
            pass
        self.events.put(("student_joined", conn))
        return conn

    def _dispatch(self, conn: StudentConn, msg: dict) -> bool:
        kind = msg.get("t")
        conn.last_seen = time.time()
        if kind == "frame":
            data = msg.get("data")
            if not isinstance(data, str):
                return True
            try:
                raw = base64.b64decode(data)
            except (ValueError, TypeError):
                return True
            if len(raw) > 6 * 1024 * 1024:
                return True
            conn.frame = raw
            try:
                conn.frame_seq = int(msg.get("seq", conn.frame_seq + 1))
            except (TypeError, ValueError):
                conn.frame_seq += 1
            conn.frame_ts = time.time()
            self.events.put(("frame", conn.key))
        elif kind == "status":
            conn.sharing = bool(msg.get("sharing", conn.sharing))
            conn.locked = bool(msg.get("locked", conn.locked))
            conn.net = str(msg.get("net", conn.net))
            self.events.put(("status", conn.key))
        elif kind == "event":
            self.events.put(("event", (conn.key, msg)))
        elif kind == "bye":
            return False
        return True

    def _drop(self, conn: StudentConn) -> None:
        removed = False
        with self._lock:
            if self._students.get(conn.key) is conn:
                self._students.pop(conn.key, None)
                removed = True
        conn.link.close()
        if removed:
            self.events.put(("student_left", conn))
