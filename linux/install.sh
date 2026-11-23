#!/usr/bin/env bash
# ThyClass Linux 安装脚本（Debian / Ubuntu / 麒麟 / 统信，arm64 与 x86_64 通用）
# 用法：sudo bash linux/install.sh [安装目录]
set -euo pipefail

APP_DIR="${1:-/opt/thyclass}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/5] 安装目录：$APP_DIR"
install -d "$APP_DIR"

echo "[2/5] 复制程序 ..."
rm -rf "$APP_DIR/thyclass"
cp -a "$SRC_DIR/thyclass" "$APP_DIR/"
cp -a "$SRC_DIR/run_teacher.py" "$SRC_DIR/run_student.py" "$APP_DIR/"
cp -a "$SRC_DIR/requirements.txt" "$APP_DIR/"
[ -f "$SRC_DIR/LICENSE" ] && cp -a "$SRC_DIR/LICENSE" "$APP_DIR/"
install -d "$APP_DIR/linux"
cp -a "$SRC_DIR/linux/systemd" "$APP_DIR/linux/"

echo "[3/5] 安装 Python 依赖（可选，失败可手动装 python3-tk python3-pil）..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-tk python3-pil network-manager || true
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q python3-tkinter python3-pillow NetworkManager || true
elif command -v pacman >/dev/null 2>&1; then
    pacman -S --noconfirm --needed tk python-pillow networkmanager || true
fi

echo "[4/5] 生成启动器 ..."
cat > /usr/local/bin/thyclass <<'EOF'
#!/usr/bin/env bash
cd /opt/thyclass
exec python3 -m thyclass "$@"
EOF
chmod +x /usr/local/bin/thyclass

echo "[5/5] 安装桌面图标 ..."
install -d /usr/share/applications
for role in teacher student; do
    sed "s|/opt/thyclass|$APP_DIR|g" "$SRC_DIR/linux/thyclass-$role.desktop" \
        > "/usr/share/applications/thyclass-$role.desktop"
done
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true

cat <<MSG

安装完成。

  老师端： thyclass teacher --room 六年级一班
  学生端： thyclass student
  自检：   thyclass doctor

开机自启（学生机，当前用户）：
  mkdir -p ~/.config/systemd/user
  cp $APP_DIR/linux/systemd/thyclass-student.service ~/.config/systemd/user/
  systemctl --user daemon-reload && systemctl --user enable --now thyclass-student

防火墙：放行 TCP 45678 与 UDP 45677。
MSG
