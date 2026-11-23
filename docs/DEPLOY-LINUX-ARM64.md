# Linux ARM64 部署

适用：麒麟 V10 / 统信 UOS / Debian 12 / Ubuntu 22.04+ / 树莓派 OS 的 **arm64** 机器。

## 1. 依赖

```bash
sudo apt update
sudo apt install -y python3 python3-tk python3-pil network-manager
python3 -m pip install -r requirements.txt   # 若系统已有 python3-pil 可跳过
```

- `python3-tk` 提供 Tkinter 界面；
- `python3-pil` / `Pillow` 负责截屏与 JPEG 解码；
- `network-manager`（`nmcli`）用于一键断网；没有 nmcli 时，root 下回退到 `ip link`。

ARM64 上没有预编译 Pillow 轮子时，用系统包 `python3-pil` 最省事（避免编译）。

自检：

```bash
python3 -m thyclass doctor
```

应看到 `Tk：8.6（可用）`、`Pillow：...（截屏/画面显示可用）`、`DISPLAY：:0`。

## 2. 安装到 /opt

```bash
sudo bash linux/install.sh
```

脚本会：

1. 复制程序到 `/opt/thyclass`；
2. 生成 `/usr/local/bin/thyclass` 启动器；
3. 安装桌面图标 `ThyClass 老师端` / `ThyClass 学生端`；
4. 安装（但不启用）学生端 systemd 用户服务模板。

卸载：`sudo rm -rf /opt/thyclass /usr/local/bin/thyclass`，并删除
`/usr/share/applications/thyclass-*.desktop`。

## 3. 开机自启（学生机）

机房学生机建议用 systemd 用户服务，跟随图形会话启动：

```bash
mkdir -p ~/.config/systemd/user
cp /opt/thyclass/linux/systemd/thyclass-student.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now thyclass-student.service
```

查看日志：

```bash
journalctl --user -u thyclass-student -f
```

> 注意：`systemctl --user` 需要用户已登录图形会话；如果是自动登录的 kiosk，
> 也可以在 `~/.config/autostart/` 放一个 `.desktop`（install.sh 已生成模板）。

## 4. 防火墙

```bash
sudo ufw allow 45678/tcp
sudo ufw allow 45677/udp
```

`firewalld`：

```bash
sudo firewall-cmd --permanent --add-port=45678/tcp --add-port=45677/udp
sudo firewall-cmd --reload
```

## 5. 一键断网的权限

`nmcli networking off` 在普通用户下会失败。三种做法：

1. 给学生账号 `sudo` 免密执行 `nmcli`（最小化：只允许 `nmcli networking on/off`）；
2. 用 `pkexec`（桌面会弹一次密码框）；
3. 学生端以 root 运行（不推荐，界面程序不要 root）。

推荐 `/etc/sudoers.d/thyclass`：

```
thyclass ALL=(root) NOPASSWD: /usr/bin/nmcli networking off, /usr/bin/nmcli networking on
```

断网期间老师端连接会断，恢复后学生端自动重连，不需要重启程序。

## 6. ARM64 注意事项

- 树莓派等设备请确认 `DISPLAY` 指向真实桌面（`:0`），SSH 里跑 GUI 需要 `ssh -X`；
- X11 下“解除本机全屏广播”可用，普通全屏窗口与无边框置顶（override-redirect）的
  课堂广播窗口都已实测可释放；**Wayland 会话不支持**其他应用的窗口操作，
  请在登录界面选择 “X11 / Xorg” 会话；
- 屏幕截图依赖 X11；Wayland 下 Pillow 的 ImageGrab 可能失败，建议用 Xorg。

## 7. 批量部署建议

1. 在一台机器上验证 `run_student.py --teacher-host 老师IP`；
2. 把 `~/.thyclass/config.json` 里的 `teacher_host` 固定为老师 IP，
   避免校园网屏蔽 UDP 广播；
3. 用 Ansible / scp 分发到 `/opt/thyclass`，统一开 systemd 用户服务；
4. 老师端固定 IP，端口 45678 写进防火墙白名单。
