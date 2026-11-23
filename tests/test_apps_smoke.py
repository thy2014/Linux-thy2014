"""GUI 冒烟测试：无头环境用 xvfb-run 跑，验证界面能建起来、广播遮罩能开关。"""
import base64
import io
import os
import tkinter as tk
import unittest

from thyclass.config import DEFAULT_CONFIG, deep_merge

DISPLAY = os.environ.get("DISPLAY")


@unittest.skipUnless(DISPLAY, "需要 X11 显示（可用 xvfb-run）")
class TeacherAppSmokeTests(unittest.TestCase):
    def setUp(self):
        from thyclass.teacher.app import TeacherApp

        cfg = deep_merge(
            DEFAULT_CONFIG,
            {"teacher": {"port": 0}, "common": {"discovery": False}},
        )
        self.app = TeacherApp(cfg, autostart=True)

    def tearDown(self):
        self.app.close()

    def test_window_builds_and_server_listens(self):
        self.app.root.update()
        self.assertGreater(self.app.server.port, 0)
        self.assertIn("TCP", self.app._endpoint_label.cget("text"))

    def test_broadcast_without_students_is_refused(self):
        from unittest import mock

        with mock.patch("thyclass.teacher.app.messagebox.showinfo") as mocked:
            self.app.start_broadcast()
        mocked.assert_called_once()
        self.assertFalse(self.app._broadcasting)


@unittest.skipUnless(DISPLAY, "需要 X11 显示（可用 xvfb-run）")
class StudentAppSmokeTests(unittest.TestCase):
    def setUp(self):
        from thyclass.student.app import StudentApp

        cfg = deep_merge(
            DEFAULT_CONFIG,
            {
                "student": {"name": "冒烟测试机", "teacher_host": "127.0.0.1",
                            "teacher_port": 1, "share_on_start": False},
                "common": {"discovery": False},
            },
        )
        self.app = StudentApp(cfg, autostart=False)

    def tearDown(self):
        self.app.close(confirm=False)

    def test_window_builds(self):
        self.app.root.update()
        self.assertIn("ThyClass 学生端", self.app.root.title())

    def test_broadcast_overlay_locks_and_unlocks(self):
        self.app.root.update()
        self.app._start_broadcast()
        self.app.root.update()
        self.assertIsNotNone(self.app.overlay)
        self.assertTrue(self.app.broadcast_active)
        self.assertIsNotNone(self.app.locker)
        try:
            from thyclass.teacher.app import HAS_PIL
        except Exception:
            HAS_PIL = False
        if HAS_PIL:
            frame = b"\xff\xd8\xff\xe0fake-jpeg"
            self.app._render_frame(
                {"t": "bcast", "data": base64.b64encode(frame).decode("ascii")}
            )
        self.app._stop_broadcast()
        self.app.root.update()
        self.assertIsNone(self.app.overlay)
        self.assertFalse(self.app.broadcast_active)

    def test_frame_callback_from_client_thread_is_marshalled(self):
        # 模拟客户端线程回调：只允许走 root.after，不应崩
        self.app._on_client_event({"t": "local", "what": "disconnected"})
        self.app.root.update()
        self.assertIn("断开", self.app._status_var.get())


if __name__ == "__main__":
    unittest.main()
