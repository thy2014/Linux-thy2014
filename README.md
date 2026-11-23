# ThyClass — Linux ARM64 / Windows 11 局域网课堂工具

一套自己掌控的课堂工具：老师端广播屏幕、查看学生画面、锁定学生键盘；
学生端接收全屏广播、共享屏幕、一键断网/恢复、解除本机全屏广播。

纯 Python 3 + Tkinter，不依赖任何第三方课堂软件，也不需要服务器：同一局域网内
老师端开一个 TCP 端口，学生端自动发现并连接。

```
┌──────────────────────────┐        TCP 45678 (NDJSON)       ┌──────────────────────────┐
│ 老师端 teacher            │  ───────────────────────────►   │ 学生端 student            │
│ · 在线学生列表            │  ◄───────────────────────────   │ · 自动发现 + 断线重连      │
│ · 实时画面预览            │       帧 / 状态 / 指令           │ · 全屏广播 + 键盘锁        │
│ · 全屏广播 / 锁键盘       │                                 │ · 屏幕共享开关（可暂停）   │
│ · 群发消息                │        UDP 45677 自动发现        │ · 一键断网 / 恢复          │
└──────────────────────────┘                                 │ · 解除本机全屏广播         │
                                                              └──────────────────────────┘
```

## 功能

| 能力 | 老师端 | 学生端 |
|---|---|---|
| 局域网自动发现 / 断线重连 | 监听 UDP 应答 | 广播 HELLO，失败自动重试 |
| 查看学生屏幕 | 列表 + 实时画面预览 | 定时截图上报，可随时暂停 |
| 全屏广播 | 抓取本机屏幕按帧推送 | 全屏接收，覆盖桌面 |
| 广播时锁定键盘 | 一键锁定 / 解除（广播中或单独下发） | 广播期间或老师单独锁定时拦截键盘，安全阀 `Ctrl+Alt+Shift+Q` |
| 群发消息 | 输入文本下发 | 弹窗展示 |
| 一键断网 | — | 断网 / 恢复网络（需要管理员权限） |
| 解除本机全屏广播 | — | 通用“全屏窗口释放”，需本机确认 |

平台：**Linux ARM64**（麒麟、统信、Debian/Ubuntu ARM64、树莓派等）与
**Windows 11** 共用同一套 Python 代码，界面一致。
Windows 11 已在实机验证键盘钩子、紧急解锁、全屏窗口释放、截屏与广播链路，
详见 [Windows 说明](docs/DEPLOY-WINDOWS.md#5-已验证范围)。

## 界面预览

| 老师端 | 学生端 |
|---|---|
| ![老师端](https://aka.doubaocdn.com/s/DNYhLp0HJV) | ![学生端](https://aka.doubaocdn.com/s/gaVXeWWQqV) |

学生端收到广播后全屏显示，广播期间键盘被锁定：

![广播接收](https://aka.doubaocdn.com/s/XGcn9CQpbz)

## 边界与安全说明（请先读）

- 本项目**不读取、不修改、不终止任何第三方软件**，包括极域电子教室等商业课堂软件。
- “解除全屏广播”不是破解：它只做**本机窗口管理**——枚举当前铺满屏幕的窗口，
  取消映射（X11）或最小化（Win32）。需要本机使用者确认，并把一次事件上报老师端；
  老师重新广播即可恢复。
  - 支持：普通 X11 全屏窗口（多数 Linux 课堂广播、视频全屏）；Windows 上是普通顶层窗口。
  - 不支持：Wayland 会话下其他应用的窗口、独占全屏 / DirectX 覆盖层的软件。
  - 不做：杀进程、注入、hook、改配置文件、绕过鉴权。
- 广播/老师锁键期间，Linux 用 X11 全局 grab，Windows 用低级键盘钩子拦截按键；
  两端都保留 `Ctrl+Alt+Shift+Q` 紧急解锁，避免机器被永久锁死（可在配置里关闭）。
- 一键断网会同时断开与老师端的连接，按钮可恢复；Linux 需要 root / nmcli 权限，
  Windows 会弹 UAC。
- 屏幕共享默认有可见提示，学生随时可以暂停。
- 请在**自己有权管理的设备**上使用；课堂上请遵守学校规定。

## 快速开始

### 1. 装依赖

```bash
python3 -m pip install -r requirements.txt        # Pillow，用来截屏和显示画面
```

Linux ARM64 额外需要 Tk：

```bash
sudo apt install python3-tk python3-pil          # Debian / Ubuntu / 麒麟 / 统信
sudo dnf install python3-tkinter python3-pillow   # Fedora 系
```

### 2. 老师端

```bash
python3 run_teacher.py --room 六年级一班
# 或者：python3 -m thyclass teacher
```

- 启动后状态栏会显示 `TCP 45678 · UDP 发现 45677`。
- 学生上线后出现在左侧列表，选中即可看到实时画面。
- 点“开始广播”把当前屏幕推给所有学生（可勾选“只发给选中的学生”）。

### 3. 学生端

```bash
python3 run_student.py
# 指定老师 IP（校园网屏蔽广播时）：
python3 run_student.py --teacher-host 192.168.1.10 --teacher-port 45678
```

- 自动搜索同网段的老师端；找不到会每 2 秒重试。
- 老师广播时进入全屏并锁定键盘；`Ctrl+Alt+Shift+Q` 可紧急解锁。

### 4. Windows 11

双击 `windows\run-student.bat` / `windows\run-teacher.bat`，或打包成 exe：

```powershell
powershell -ExecutionPolicy Bypass -File windows\build-exe.ps1
# 产物：dist\ThyClass-Student.exe、dist\ThyClass-Teacher.exe
```

详见 [Windows 说明](docs/DEPLOY-WINDOWS.md)。

## 配置

默认配置文件 `~/.thyclass/config.json`（Windows 为 `%USERPROFILE%\.thyclass\config.json`），
不存在时使用内置默认值；也可以 `--config 路径` 指定。

```json
{
  "common":  { "room": "六年级一班", "discovery_port": 45677, "discovery": true },
  "teacher": { "port": 45678, "broadcast_fps": 2, "broadcast_width": 1280, "jpeg_quality": 60 },
  "student": {
    "name": "机房-01",
    "teacher_host": "",
    "teacher_port": 45678,
    "share_interval": 3.0,
    "share_width": 720,
    "jpeg_quality": 55,
    "share_on_start": true,
    "allow_keyboard_escape": true,
    "unlock_code": "",
    "show_sharing_notice": true,
    "screen_release": true,
    "release_attempts": 3
  }
}
```

- `student.teacher_host` 留空 = UDP 自动发现；填 IP = 直连（推荐机房统一配置）。
- `student.unlock_code` 非空时，紧急解锁要输入老师给的解锁码。
- `student.screen_release=false` 可以彻底关掉“解除全屏广播”入口。
- `common.discovery=false` 关闭 UDP 发现，只允许 `--teacher-host` 直连。

## 运维

- 端口：TCP `45678`（控制与画面）、UDP `45677`（发现）。防火墙放行即可。
- 机房批量部署见 [Linux ARM64 部署](docs/DEPLOY-LINUX-ARM64.md)。
- 自检：`python3 -m thyclass doctor` 检查 Tk / Pillow / DISPLAY / nmcli / root。
- 协议细节见 [docs/PROTOCOL.md](docs/PROTOCOL.md)。

## 开发与测试

无头环境用 Xvfb 跑完整测试（40 个用例，覆盖协议、发现、连接、键盘锁、截屏、断网 dry-run、
GUI 冒烟、跨进程全屏释放、Windows 钩子）：

```bash
# Linux（无桌面时加 xvfb-run）
xvfb-run -a python3 -m unittest discover -s tests -v
# Ran 40 tests ... OK (skipped=2，Windows 专属用例跳过)

# Windows 11
py -3 -m unittest discover -s tests -v
# Ran 40 tests ... OK (skipped=3，X11 / root 专属用例跳过)
```

截图由 `tools/make_screenshots.py` 在 Xvfb 下生成（`docs/screenshots/`）。

目录结构：

```
thyclass/
├── common/        协议、发现、截屏、键盘锁（X11 + Win32）、断网、全屏窗口释放、UI 小工具
├── teacher/       老师端服务（server.py）与界面（app.py）
├── student/       学生端连接（client.py）与界面（app.py）
└── cli.py         teacher / student / net / doctor 子命令
run_teacher.py     老师端入口
run_student.py     学生端入口
linux/             安装脚本、desktop、systemd
windows/           bat 启动器、PyInstaller 打包脚本
docs/              协议、部署、Windows 说明
tests/              unittest 套件
```

## 许可证

MIT，见 [LICENSE](LICENSE)。
