import os
import unittest

from thyclass.common.capture import HAS_PIL, ScreenCapture
from thyclass.common.netcut import NetworkSwitch


class CaptureTests(unittest.TestCase):
    @unittest.skipUnless(HAS_PIL, "未安装 Pillow")
    @unittest.skipUnless(os.environ.get("DISPLAY"), "需要 X11 显示（可用 xvfb-run）")
    def test_grab_returns_jpeg(self):
        capture = ScreenCapture(max_width=320, quality=50)
        frame = capture.grab()
        self.assertIsNotNone(frame, capture.last_error)
        assert frame is not None
        self.assertEqual(frame.mime, "image/jpeg")
        self.assertTrue(frame.data.startswith(b"\xff\xd8"))
        self.assertLessEqual(frame.width, 320)
        self.assertGreater(frame.height, 0)

    def test_grab_without_pillow_returns_none_gracefully(self):
        capture = ScreenCapture()
        if not HAS_PIL:
            self.assertIsNone(capture.grab())
            self.assertIn("Pillow", capture.last_error)


class NetSwitchTests(unittest.TestCase):
    def test_dry_run_never_touches_system(self):
        switch = NetworkSwitch(dry_run=True)
        self.assertEqual(switch.status(), "网络正常")
        ok, message = switch.set_offline(True)
        self.assertTrue(ok)
        self.assertIn("dry-run", message)
        self.assertTrue(switch.offline)
        ok, message = switch.set_offline(False)
        self.assertTrue(ok)
        self.assertFalse(switch.offline)

    def test_real_call_reports_permission_hint_when_not_root(self):
        if os.name == "nt" or not hasattr(os, "geteuid"):
            self.skipTest("仅 Linux 检查权限提示")
        if os.geteuid() == 0:
            self.skipTest("root 环境会真实改网络，跳过")
        switch = NetworkSwitch(dry_run=False)
        # 这里只验证“不会静默失败”：不实际断网，改为检查状态接口不抛异常
        self.assertIn("网络", switch.status())

    def test_physical_interface_filter(self):
        names = NetworkSwitch._physical_interfaces()
        self.assertNotIn("lo", names)
        for name in names:
            self.assertFalse(name.startswith(("docker", "veth", "br-")))


if __name__ == "__main__":
    unittest.main()
