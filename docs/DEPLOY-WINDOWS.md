# Windows 11 使用与打包

同一套 Python 代码，Windows 11 上界面和协议与 Linux 完全一致。
Windows 特有实现：

| 能力 | 实现 |
|---|---|
| 键盘锁 | `SetWindowsHookEx(WH_KEYBOARD_LL)` 低级钩子，广播期间吞掉按键；`Ctrl+Alt+Shift+Q` 放行 |
| 解除全屏广播 | `EnumWindows` 找铺满屏幕的窗口，`ShowWindow(SW_MINIMIZE)` |
| 一键断网 | PowerShell `Disable-NetAdapter` / `Enable-NetAdapter`，非管理员走 UAC 提权 |
| 截屏 | Pillow `ImageGrab`（多显示器取主屏） |

## 1. 直接运行（需要 Python）

1. 安装 Python 3.10+（勾选 “Add python.exe to PATH”）；
2. 双击 `windows\run-student.bat` 或 `windows\run-teacher.bat`；
3. 首次运行会装 Pillow（脚本里已带 `pip install pillow`）。

命令行等价：

```powershell
py -3 run_student.py --teacher-host 192.168.1.10
py -3 run_teacher.py --room 六年级一班
```

## 2. 打包成 exe（不需要学生机装 Python）

```powershell
powershell -ExecutionPolicy Bypass -File windows\build-exe.ps1
```

产物：

```
dist\ThyClass-Teacher.exe
dist\ThyClass-Student.exe
```

把 exe 拷到学生机双击即可。首次启动 Windows 防火墙会询问，允许“专用网络”。

## 3. 键盘锁说明

- 钩子只在 ThyClass 广播窗口激活时安装，广播结束立即卸载；
- 钩子不拦截 `Ctrl+Alt+Shift+Q`，也不拦截 `Ctrl+Alt+Del`（系统级，任何程序都拦不住）；
- 如果程序异常退出，钩子随进程消失，不会残留锁定。

## 4. 一键断网说明

- 需要管理员权限，会弹 UAC；
- 断网会同时断开老师端连接，点“恢复网络”后自动重连；
- 只操作物理网卡（`Get-NetAdapter -Physical`），不会误关虚拟网卡 / VPN。

## 5. 已验证范围

- 代码在 Linux 上完成全部单元测试（38 个用例）；
- Windows 分支（钩子、ShowWindow、PowerShell 断网）为**静态实现，未在 Windows 11 实机验证**；
  首次使用请先在测试机确认：广播锁键、紧急解锁、断网/恢复、全屏释放。
- Windows 11 ARM64 同样适用（Python 与 Pillow 均有 arm64 版本）。
