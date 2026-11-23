"""命令行入口：python -m thyclass teacher / student / net / doctor。"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys

from . import __version__
from .config import config_path, default_device_name, load_config


def _teacher(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.port:
        cfg["teacher"]["port"] = int(args.port)
    if args.room:
        cfg["common"]["room"] = args.room
    if args.no_discovery:
        cfg["common"]["discovery"] = False
    from .teacher.app import TeacherApp

    TeacherApp(cfg).run()
    return 0


def _student(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.name:
        cfg["student"]["name"] = args.name
    if args.teacher_host:
        cfg["student"]["teacher_host"] = args.teacher_host
    if args.teacher_port:
        cfg["student"]["teacher_port"] = int(args.teacher_port)
    if args.room:
        cfg["common"]["room"] = args.room
    if not cfg["student"].get("name"):
        cfg["student"]["name"] = default_device_name()
    from .student.app import StudentApp

    StudentApp(cfg).run()
    return 0


def _net(args: argparse.Namespace) -> int:
    from .common.netcut import NetworkSwitch

    if args.off and args.on:
        print("--off 与 --on 不能同时使用")
        return 2
    switch = NetworkSwitch(dry_run=args.dry_run)
    if args.status or not (args.off or args.on):
        print(switch.status())
        return 0
    ok, message = switch.set_offline(bool(args.off))
    print(("成功：" if ok else "失败：") + message)
    return 0 if ok else 1


def _doctor() -> int:
    print(f"ThyClass {__version__}")
    print(f"平台：{platform.system()} {platform.release()} / {platform.machine()}")
    print(f"Python：{platform.python_version()}")
    try:
        import tkinter

        print(f"Tk：{tkinter.TkVersion}（可用）")
    except Exception as exc:  # pragma: no cover - 环境相关
        print(f"Tk：不可用（{exc}）—— Linux 请安装 python3-tk")
    try:
        import PIL

        print(f"Pillow：{PIL.__version__}（截屏/画面显示可用）")
    except Exception:
        print("Pillow：未安装 —— 请安装 python3-pil 或 pillow")
    print(
        f"配置：{config_path()}（"
        + ("已存在" if config_path().is_file() else "不存在，使用默认值")
        + "）"
    )
    if sys.platform.startswith("linux"):
        print(f"DISPLAY：{os.environ.get('DISPLAY') or '无（纯命令行/无桌面）'}")
        for tool in ("nmcli", "ip", "pkexec", "sudo"):
            print(f"{tool}：{'已安装' if shutil.which(tool) else '缺失'}")
        print(f"root：{'是' if os.geteuid() == 0 else '否（一键断网需要管理员权限'}")
    if sys.platform == "win32":
        print("Windows：一键断网会请求管理员权限（UAC）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thyclass",
        description="ThyClass —— 局域网课堂广播 / 屏幕查看 / 课堂管控工具",
    )
    parser.add_argument("--version", action="version", version=f"ThyClass {__version__}")
    sub = parser.add_subparsers(dest="role")

    p_teacher = sub.add_parser("teacher", help="启动老师端（广播、看学生屏幕）")
    p_teacher.add_argument("--config", help="配置文件路径")
    p_teacher.add_argument("--port", type=int, help="TCP 服务端口，默认 45678")
    p_teacher.add_argument("--room", help="班级名称")
    p_teacher.add_argument("--no-discovery", action="store_true", help="关闭 UDP 自动发现")

    p_student = sub.add_parser("student", help="启动学生端（接收广播、共享屏幕）")
    p_student.add_argument("--config", help="配置文件路径")
    p_student.add_argument("--name", help="学生机显示名")
    p_student.add_argument("--room", help="班级名称")
    p_student.add_argument("--teacher-host", help="老师端 IP（不填则自动发现）")
    p_student.add_argument("--teacher-port", type=int, help="老师端 TCP 端口")

    p_net = sub.add_parser("net", help="断网 / 恢复网络（无界面）")
    p_net.add_argument("--off", action="store_true", help="断开网络")
    p_net.add_argument("--on", action="store_true", help="恢复网络")
    p_net.add_argument("--status", action="store_true", help="查看当前状态")
    p_net.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")

    sub.add_parser("doctor", help="检查运行环境")
    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "role", None):
        parser.print_help()
        return 0
    if args.role == "teacher":
        return _teacher(args)
    if args.role == "student":
        return _student(args)
    if args.role == "net":
        return _net(args)
    if args.role == "doctor":
        return _doctor()
    parser.print_help()
    return 2
