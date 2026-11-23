"""本机全屏窗口释放的真实验证：另一个进程弹一个全屏窗口，主进程负责释放它。"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
import unittest

from thyclass.common.screen_release import (
    expand_window_ids,
    list_fullscreen_windows,
    release_fullscreen,
)

DISPLAY = os.environ.get("DISPLAY")
WINDOWED = os.name == "nt" or bool(DISPLAY)

_MOCK = textwrap.dedent(
    """
    import time
    import tkinter as tk

    root = tk.Tk()
    root.title("MOCK-BROADCAST")
    root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
    root.configure(bg="black")
    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        root.winfo_screenwidth() // 2, root.winfo_screenheight() // 2,
        text="MOCK BROADCAST", fill="white", font=("Helvetica", 24),
    )
    root.update()
    time.sleep(12)
    """
)


def _wait(predicate, timeout=4.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@unittest.skipUnless(WINDOWED, "需要图形界面（Linux 无头环境可用 xvfb-run）")
class ScreenReleaseTests(unittest.TestCase):
    def setUp(self):
        env = dict(os.environ)
        env.setdefault("DISPLAY", DISPLAY or "")
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _MOCK], env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def test_lists_and_releases_other_process_window(self):
        self.assertTrue(
            _wait(lambda: any("MOCK-BROADCAST" in w["title"] for w in list_fullscreen_windows()), 5.0),
            "另一个进程的全屏窗口没有出现在列表里",
        )
        result = release_fullscreen(repeat=2, interval=0.1)
        self.assertTrue(result.ok, result.message)
        self.assertIn("MOCK-BROADCAST", " ".join(result.released))

        def gone():
            titles = [w["title"] for w in list_fullscreen_windows()]
            return not any("MOCK-BROADCAST" in t for t in titles)

        self.assertTrue(_wait(gone, 3.0), "全屏窗口在释放后仍然可见")

    def test_own_process_windows_are_ignored(self):
        import tkinter as tk

        root = tk.Tk()
        root.title("OWN-WINDOW")
        root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        root.update()
        try:
            titles = [
                w["title"]
                for w in list_fullscreen_windows(
                    exclude_ids=expand_window_ids({root.winfo_id()})
                )
            ]
            self.assertNotIn("OWN-WINDOW", titles)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
