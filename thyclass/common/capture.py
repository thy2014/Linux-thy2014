"""截屏并压缩成 JPEG。

优先 Pillow（Windows / X11 都可用），Wayland 下依次尝试 grim、scrot、
ImageMagick 的 import。没有可用后端时返回 None，不会抛异常打断广播。
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

try:
    from PIL import Image, ImageGrab

    HAS_PIL = True
except Exception:  # pragma: no cover - 取决于目标机是否装了 Pillow
    Image = None  # type: ignore[assignment]
    ImageGrab = None  # type: ignore[assignment]
    HAS_PIL = False


@dataclass
class Frame:
    data: bytes
    width: int
    height: int
    mime: str = "image/jpeg"


class ScreenCapture:
    def __init__(self, max_width: int = 1280, quality: int = 60) -> None:
        self.max_width = max(160, int(max_width))
        self.quality = max(20, min(90, int(quality)))
        self.last_error = ""

    def grab(self) -> Optional[Frame]:
        image = self._grab_image()
        if image is None:
            return None
        try:
            width, height = image.size
            if width > self.max_width:
                ratio = self.max_width / float(width)
                image = image.resize(
                    (self.max_width, max(1, int(height * ratio))), Image.LANCZOS
                )
            buffer = io.BytesIO()
            image.convert("RGB").save(
                buffer, format="JPEG", quality=self.quality, optimize=True
            )
            return Frame(buffer.getvalue(), image.size[0], image.size[1])
        except Exception as exc:
            self.last_error = f"JPEG 编码失败：{exc}"
            return None

    def _grab_image(self):
        if not HAS_PIL:
            self.last_error = "缺少 Pillow，无法截屏（请安装 python3-pil / pillow）"
            return None
        try:
            if os.name == "nt":
                return ImageGrab.grab(all_screens=True)
            return ImageGrab.grab()
        except Exception as exc:
            self.last_error = f"Pillow 截屏失败：{exc}"

        for command, suffix in (
            (["grim", "-t", "png"], ".png"),  # Wayland
            (["scrot", "-o", "-t", "png"], ".png"),  # X11
            (["import", "-window", "root"], ".png"),  # ImageMagick
        ):
            if shutil.which(command[0]) is None:
                continue
            path = os.path.join(
                tempfile.gettempdir(), f"thyclass-shot-{int(time.time() * 1000)}{suffix}"
            )
            try:
                subprocess.run(
                    command + [path],
                    check=False,
                    timeout=10,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    image = Image.open(path)
                    image.load()
                    return image.convert("RGB")
            except Exception as exc:
                self.last_error = f"{command[0]} 截屏失败：{exc}"
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return None


def jpeg_size(data: bytes) -> tuple[int, int]:
    """从 JPEG 读尺寸，失败返回 (0, 0)。"""
    if not HAS_PIL:
        return 0, 0
    try:
        image = Image.open(io.BytesIO(data))
        return image.size
    except Exception:
        return 0, 0
