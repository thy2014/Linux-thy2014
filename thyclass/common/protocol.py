"""NDJSON 控制协议：TCP 上每行一个 JSON 对象。

约定一个 socket 只由一个写线程（内嵌写锁）+ 一个读线程使用，
因此不需要额外的消息队列层。
"""
from __future__ import annotations

import json
import socket
import threading
from typing import Any, Optional

MAX_LINE_BYTES = 8 * 1024 * 1024


class ProtocolError(Exception):
    """报文非法（非 JSON 对象或单行超长）。"""


def encode(msg: dict) -> bytes:
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a JSON object")
    text = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


class LineSocket:
    """按行读写 JSON 的 socket 封装。"""

    def __init__(self, sock: socket.socket, max_line: int = MAX_LINE_BYTES) -> None:
        self.sock = sock
        self.max_line = max_line
        self._buf = b""
        self._wlock = threading.Lock()

    def send(self, msg: dict) -> None:
        data = encode(msg)
        with self._wlock:
            self.sock.sendall(data)

    def recv(self, timeout: Optional[float] = None) -> Optional[dict]:
        """返回下一条消息；对端正常关闭返回 None；超时抛 TimeoutError。"""
        self.sock.settimeout(timeout)
        while True:
            while b"\n" not in self._buf:
                try:
                    chunk = self.sock.recv(65536)
                except (socket.timeout, TimeoutError) as exc:
                    raise TimeoutError("recv timeout") from exc
                if not chunk:
                    return None
                self._buf += chunk
                if len(self._buf) > self.max_line:
                    raise ProtocolError(f"line exceeds {self.max_line} bytes")
            line, _, self._buf = self._buf.partition(b"\n")
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError(f"bad json line: {exc}") from exc
            if not isinstance(msg, dict):
                raise ProtocolError("message is not a JSON object")
            return msg

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
