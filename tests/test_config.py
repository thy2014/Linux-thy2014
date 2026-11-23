import os
import tempfile
import unittest
from pathlib import Path

from thyclass.config import DEFAULT_CONFIG, deep_merge, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_deep_merge_keeps_defaults(self):
        merged = deep_merge(DEFAULT_CONFIG, {"teacher": {"port": 50000}})
        self.assertEqual(merged["teacher"]["port"], 50000)
        self.assertEqual(merged["teacher"]["broadcast_fps"], DEFAULT_CONFIG["teacher"]["broadcast_fps"])
        self.assertEqual(merged["common"]["room"], DEFAULT_CONFIG["common"]["room"])
        # 原对象不被污染
        self.assertEqual(DEFAULT_CONFIG["teacher"]["port"], 45678)

    def test_unknown_keys_are_kept(self):
        merged = deep_merge(DEFAULT_CONFIG, {"custom": {"a": 1}})
        self.assertEqual(merged["custom"]["a"], 1)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            cfg = deep_merge(DEFAULT_CONFIG, {"student": {"name": "机房-01", "teacher_host": "10.0.0.9"}})
            save_config(cfg, str(path))
            loaded = load_config(str(path))
            self.assertEqual(loaded["student"]["name"], "机房-01")
            self.assertEqual(loaded["student"]["teacher_host"], "10.0.0.9")

    def test_broken_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            loaded = load_config(str(path))
            self.assertEqual(loaded["teacher"]["port"], DEFAULT_CONFIG["teacher"]["port"])

    def test_env_home_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["THYCLASS_HOME"] = tmp
            try:
                loaded = load_config(None)
                self.assertEqual(loaded["common"]["discovery"], True)
            finally:
                os.environ.pop("THYCLASS_HOME", None)


if __name__ == "__main__":
    unittest.main()
