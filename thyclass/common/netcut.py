"""一键断网 / 恢复网络。

Linux：优先 NetworkManager（nmcli networking off/on），没有则用 ip link
把物理网卡 down/up。需要 root；普通用户会尝试 sudo -n 与 pkexec。
Windows：用 PowerShell 的 Disable-NetAdapter / Enable-NetAdapter，需要管理员
权限，未提权时通过 runas 弹出 UAC。

所有实际系统调用都能用 dry_run=True 关闭，便于测试与演示。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

_VIRTUAL_PREFIXES = (
    "lo",
    "docker",
    "veth",
    "br-",
    "virbr",
    "tun",
    "tap",
    "wg",
    "bond",
    "dummy",
)


class NetworkSwitch:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.offline = False
        self._downed: List[str] = []
        self.last_message = ""

    # ------------------------------------------------------------------ 公共 API
    def status(self) -> str:
        if self.offline:
            return "已断网（再次点击可恢复）"
        return "网络正常"

    def set_offline(self, offline: bool) -> Tuple[bool, str]:
        if self.dry_run:
            self.offline = offline
            action = "断网" if offline else "恢复网络"
            self.last_message = f"[dry-run] 将执行{action}（未实际修改系统网络）"
            return True, self.last_message
        if os.name == "nt":
            ok, msg = self._windows(offline)
        elif sys.platform.startswith("linux"):
            ok, msg = self._linux(offline)
        else:
            return False, "当前系统不支持一键断网"
        if ok:
            self.offline = offline
        self.last_message = msg
        return ok, msg

    # ------------------------------------------------------------------ 内部工具
    @staticmethod
    def _run(command: List[str], timeout: int = 20) -> Tuple[bool, str]:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return False, f"缺少命令：{command[0]}"
        except subprocess.TimeoutExpired:
            return False, "命令执行超时"
        except OSError as exc:
            return False, f"命令执行失败：{exc}"
        output = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode == 0, output

    def _maybe_dry(self, command: List[str]) -> Tuple[bool, str]:
        if self.dry_run:
            return True, "[dry-run] " + " ".join(command)
        return self._run(command)

    # ------------------------------------------------------------------ Linux
    def _linux(self, offline: bool) -> Tuple[bool, str]:
        action = "off" if offline else "on"
        if shutil.which("nmcli"):
            if os.geteuid() == 0:
                ok, out = self._maybe_dry(["nmcli", "networking", action])
                if ok:
                    return True, f"已通过 NetworkManager {'断开' if offline else '恢复'}网络"
                return False, out or "nmcli 执行失败"
            for prefix in (["sudo", "-n"], ["pkexec"]):
                if shutil.which(prefix[0]) is None:
                    continue
                ok, out = self._run(prefix + ["nmcli", "networking", action])
                if ok:
                    return True, f"已通过 {' '.join(prefix)} 切换网络状态"
            return False, (
                "需要管理员权限才能断网。可用 sudo 启动，"
                "或让机房管理员把本工具加入允许策略。"
            )
        if os.geteuid() == 0:
            return self._ip_link_all(offline)
        return False, (
            "未找到 NetworkManager，且当前不是 root。请用 sudo 启动本工具，"
            "或安装 nmcli 后重试。"
        )

    def _ip_link_all(self, offline: bool) -> Tuple[bool, str]:
        names = self._physical_interfaces()
        if not names:
            return False, "没有找到可操作的物理网卡"
        if offline:
            downed = []
            for name in names:
                ok, _ = self._maybe_dry(["ip", "link", "set", name, "down"])
                if ok:
                    downed.append(name)
            self._downed = downed
            if not downed:
                return False, "网卡 down 失败，请检查权限"
            return True, "已关闭网卡：" + "、".join(downed)
        targets = self._downed or names
        failed = []
        for name in targets:
            ok, _ = self._maybe_dry(["ip", "link", "set", name, "up"])
            if not ok:
                failed.append(name)
        self._downed = []
        if failed:
            return False, "部分网卡恢复失败：" + "、".join(failed)
        return True, "已恢复网卡：" + "、".join(targets)

    @staticmethod
    def _physical_interfaces() -> List[str]:
        base = "/sys/class/net"
        if not os.path.isdir(base):
            return []
        names = []
        for name in sorted(os.listdir(base)):
            if name.startswith(_VIRTUAL_PREFIXES):
                continue
            device = os.path.join(base, name, "device")
            if os.path.isdir(device) or name.startswith(("eth", "en", "wl")):
                names.append(name)
        return names

    # ------------------------------------------------------------------ Windows
    def _windows(self, offline: bool) -> Tuple[bool, str]:
        if offline:
            script = (
                "Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' } | "
                "Disable-NetAdapter -Confirm:$false"
            )
            verb = "断开"
        else:
            script = (
                "Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Disabled' } | "
                "Enable-NetAdapter -Confirm:$false"
            )
            verb = "恢复"
        if not self._windows_is_admin():
            if self._windows_elevate(script):
                return True, f"已请求管理员权限{verb}网络（请在 UAC 窗口确认）"
            return False, "需要管理员权限才能切换网络，且提权请求被取消"
        ok, out = self._maybe_dry(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        )
        if ok:
            return True, f"已通过 PowerShell {verb}网络"
        return False, out or "PowerShell 执行失败"

    @staticmethod
    def _windows_is_admin() -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.IsUserAnAdmin.argtypes = []
            shell32.IsUserAnAdmin.restype = wintypes.BOOL
            return bool(shell32.IsUserAnAdmin())
        except Exception:
            return False

    @staticmethod
    def _windows_elevate(script: str) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.ShellExecuteW.argtypes = [
                wintypes.HWND,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                ctypes.c_int,
            ]
            # 返回 HINSTANCE：64 位下必须用指针宽度接收，c_int 会被截断
            shell32.ShellExecuteW.restype = ctypes.c_void_p
            result = shell32.ShellExecuteW(
                None, "runas", "powershell.exe",
                f'-NoProfile -NonInteractive -Command "{script}"', None, 1,
            )
            return bool(result) and int(result) > 32
        except Exception:
            return False


def toggle_offline(current: bool, dry_run: bool = False) -> Tuple[bool, str]:
    """便捷函数：传当前状态，返回切换结果。"""
    switch = NetworkSwitch(dry_run=dry_run)
    switch.offline = current
    return switch.set_offline(not current)


__all__ = ["NetworkSwitch", "toggle_offline", "Optional"]
