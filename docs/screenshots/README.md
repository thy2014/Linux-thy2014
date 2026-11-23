# 界面截图

README 里的三张图由 `tools/make_screenshots.py` 生成：

| 文件 | 内容 |
|---|---|
| `teacher.png` | 老师端主界面：学生列表、实时预览、广播与锁键工具栏 |
| `student.png` | 学生端主界面：连接状态、屏幕共享、一键断网、解除全屏广播 |
| `student-broadcast.png` | 学生端接收全屏广播（含模拟课堂桌面） |

重新生成（Linux，需要 Xvfb 与 Pillow）：

```bash
xvfb-run -a -s "-screen 0 1280x1024x24" python3 tools/make_screenshots.py
```

生成后可把 PNG 放到本目录并替换 README 中的图片地址。仓库当前通过 CDN
外链展示截图，因为本项目的 GitHub 推送通道只提交文本文件；图片本身可用上面的
脚本随时重建。
