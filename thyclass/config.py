"""配置读写：内置默认值 + 用户配置深合并。

配置文件默认位于 ~/.thyclass/config.json，可用环境变量 THYCLASS_HOME
或命令行 --config 指向别处，便于班级统一分发。
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import socket
from typing import Any, Optional

APP_NAME = "thyclass"

DEFAULT_CONFIG: dict[str, Any] = {
    "common": {
        "room": "默认班级",
        "discovery_port": 45677,
        "discovery": True,
    },
    "teacher": {
        "name": "老师端",
        "port": 45678,
        "bind": "0.0.0.0",
        "broadcast_fps": 2,
        "broadcast_width": 1280,
        "jpeg_quality": 60,
        "thumb_width": 480,
    },
    "student": {
        "name": "",
        "room": "",
        "teacher_host": "",
        "teacher_port": 45678,
        "share_interval": 3.0,
        "share_width": 720,
        "jpeg_quality": 55,
        "share_on_start": True,
        "allow_keyboard_escape": True,
        "unlock_code": "",
        "show_sharing_notice": True,
        "screen_release": True,
        "release_attempts": 3,
    },
}


def config_dir() -> pathlib.Path:
    base = os.environ.get("THYCLASS_HOME")
    if base:
        return pathlib.Path(base)
    return pathlib.Path.home() / ".thyclass"


def config_path() -> pathlib.Path:
    return config_dir() / "config.json"


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: Optional[str] = None) -> dict:
    file_path = pathlib.Path(path).expanduser() if path else config_path()
    data: Any = {}
    if file_path.is_file():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[thyclass] 配置读取失败，改用默认值：{exc}")
            data = {}
    if not isinstance(data, dict):
        data = {}
    return deep_merge(DEFAULT_CONFIG, data)


def save_config(cfg: dict, path: Optional[str] = None) -> pathlib.Path:
    file_path = pathlib.Path(path).expanduser() if path else config_path()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return file_path


def default_device_name() -> str:
    """默认用主机名作为学生端显示名。"""
    try:
        return socket.gethostname() or "未命名终端"
    except OSError:
        return "未命名终端"
