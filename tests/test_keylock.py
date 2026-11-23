import os
import time
import tkinter as tk
import unittest

DISPLAY = os.environ.get("DISPLAY")
WINDOWED = os.name == "nt" or bool(DISPLAY)


def _pump(root, rounds=12):
    for _ in range(rounds):
        try:
            root.update()
        except tk.TclError:
            break
        time.sleep(0.03)


from thyclass.common.keylock import (
    NullLock,
    TkGlobalGrabLock,
    create_keyboard_lock,
)


class KeyLockTests(unittest.TestCase):
    def test_factory_without_display_returns_null_lock(self):
        old = os.environ.pop("DISPLAY", None)
        try:
            class FakeWidget:
                pass

            lock = create_keyboard_lock(FakeWidget(), allow_escape=True)  # type: ignore[arg-type]
            if os.name != "nt":
                self.assertIsInstance(lock, NullLock)
                self.assertFalse(lock.active)
        finally:
            if old is not None:
                os.environ["DISPLAY"] = old

    @unittest.skipUnless(os.environ.get("DISPLAY"), "需要 X11（可用 xvfb-run 运行）")
    def test_global_grab_blocks_and_releases(self):
        root = tk.Tk()
        top = tk.Toplevel(root)
        top.geometry("200x100+0+0")
        root.update()
        fired = {"count": 0}

        def on_escape():
            fired["count"] += 1

        lock = TkGlobalGrabLock(top, allow_escape=True, on_escape=on_escape)
        lock.start()
        _pump(root)
        try:
            self.assertTrue(lock.active)
            self.assertIsNotNone(top.grab_current())
            try:
                top.event_generate("<Control-Alt-Shift-q>")
                root.update()
            except tk.TclError:
                pass
            self.assertEqual(fired["count"], 1)
        finally:
            lock.stop()
            self.assertFalse(lock.active)
            self.assertIsNone(top.grab_current())
            root.destroy()

    @unittest.skipUnless(os.environ.get("DISPLAY"), "需要 X11（可用 xvfb-run 运行）")
    def test_escape_can_be_disabled(self):
        root = tk.Tk()
        top = tk.Toplevel(root)
        top.geometry("200x100+0+0")
        root.update()
        lock = TkGlobalGrabLock(top, allow_escape=False, on_escape=lambda: None)
        lock.start()
        self.assertEqual(lock.describe().startswith(("X11", "仅窗口")), True)
        lock.stop()
        root.destroy()

    @unittest.skipUnless(os.name == "nt", "仅在 Windows 上验证低级键盘钩子")
    def test_windows_hook_installs_and_reports(self):
        root = tk.Tk()
        root.withdraw()
        lock = create_keyboard_lock(root, allow_escape=True)
        self.assertEqual(type(lock).__name__, "WindowsHookLock")
        lock.start()
        try:
            self.assertTrue(lock.active, lock.describe())
            self.assertIn("钩子", lock.describe())
            _pump(root)
            self.assertTrue(lock.active, lock.describe())
        finally:
            lock.stop()
            root.destroy()
        self.assertFalse(lock.active)


if __name__ == "__main__":
    unittest.main()
