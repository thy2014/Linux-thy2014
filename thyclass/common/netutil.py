"""局域网地址小工具。"""
from __future__ import annotations

import ipaddress
import socket
from typing import List


def local_ipv4() -> str:
    """取本机默认出口地址（不会真正发包）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def subnet_broadcast(ip: str | None = None) -> str:
    """按 /24 估算网段广播地址，覆盖不了时退回 255.255.255.255。"""
    address = ip or local_ipv4()
    try:
        network = ipaddress.ip_network(f"{address}/24", strict=False)
        return str(network.broadcast_address)
    except ValueError:
        return "255.255.255.255"


def broadcast_targets() -> List[str]:
    targets = ["255.255.255.255"]
    sub = subnet_broadcast()
    if sub not in targets:
        targets.append(sub)
    return targets


def format_endpoint(host: str, port: int) -> str:
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"
