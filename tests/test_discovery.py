import unittest

from thyclass.common.discovery import DiscoveryBeacon, TeacherDiscovery


class DiscoveryTests(unittest.TestCase):
    def test_student_finds_teacher(self):
        discovery = TeacherDiscovery(tcp_port=45678, room="测试班", host="127.0.0.1")
        port = discovery.start()
        if not port:
            self.skipTest(f"UDP 端口不可用：{discovery.error}")
        try:
            beacon = DiscoveryBeacon(
                tcp_port=9999, name="测试学生", hosts=["127.0.0.1"], discovery_port=port
            )
            found = beacon.find_teacher(timeout=2.0)
            self.assertIsNotNone(found)
            self.assertEqual(found[0], "127.0.0.1")
            self.assertEqual(found[1], 45678)
        finally:
            discovery.stop()

    def test_timeout_returns_none(self):
        beacon = DiscoveryBeacon(
            tcp_port=9999, name="无老师", hosts=["127.0.0.1"], discovery_port=9
        )
        start = __import__("time").monotonic()
        self.assertIsNone(beacon.find_teacher(timeout=0.6))
        self.assertLess(__import__("time").monotonic() - start, 3.0)


if __name__ == "__main__":
    unittest.main()
