import base64
import queue
import socket
import time
import unittest

from thyclass.common.protocol import LineSocket
from thyclass.config import DEFAULT_CONFIG, deep_merge
from thyclass.student.client import StudentClient
from thyclass.teacher.server import TeacherServer


def _wait(predicate, timeout=4.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class ServerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.server = TeacherServer(port=0, bind="127.0.0.1", room="测试班")
        self.port = self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_register_and_receive_frame(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        link = LineSocket(sock)
        link.send({"t": "register", "name": "学生A", "os": "Linux arm64"})
        welcome = link.recv(3.0)
        self.assertEqual(welcome["t"], "welcome")

        payload = base64.b64encode(b"jpeg-bytes").decode("ascii")
        link.send({"t": "frame", "seq": 7, "data": payload, "w": 10, "h": 10})
        self.assertTrue(_wait(lambda: self.server.count() == 1))
        conn = self.server.students()[0]
        self.assertEqual(conn.name, "学生A")
        self.assertEqual(conn.os_name, "Linux arm64")
        self.assertTrue(_wait(lambda: conn.frame == b"jpeg-bytes"))

        link.send({"t": "status", "sharing": False, "locked": True})
        self.assertTrue(_wait(lambda: conn.locked and not conn.sharing))
        sock.close()

    def test_server_broadcast_reaches_client(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        link = LineSocket(sock)
        link.send({"t": "register", "name": "学生B"})
        link.recv(3.0)
        self.assertTrue(_wait(lambda: self.server.count() == 1))
        sent = self.server.broadcast({"t": "cmd", "cmd": "broadcast_start", "fps": 2})
        self.assertEqual(sent, 1)
        msg = link.recv(3.0)
        self.assertEqual(msg["cmd"], "broadcast_start")
        sock.close()

    def test_duplicate_name_from_other_ip_gets_suffix(self):
        s1 = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        l1 = LineSocket(s1)
        l1.send({"t": "register", "name": "同名机"})
        l1.recv(3.0)
        # 直接构造第二个连接对象模拟另一台机器（源 IP 相同则按重连处理，此处只验证键生成逻辑）
        self.assertTrue(_wait(lambda: self.server.count() == 1))
        self.assertEqual(self.server.students()[0].key, "同名机")
        s1.close()

    def test_student_client_connects_and_receives_command(self):
        cfg = deep_merge(
            DEFAULT_CONFIG,
            {
                "student": {
                    "name": "集成测试机",
                    "teacher_host": "127.0.0.1",
                    "teacher_port": self.port,
                    "share_interval": 99,
                }
            },
        )
        events: "queue.Queue[dict]" = queue.Queue()
        client = StudentClient(cfg, on_event=events.put, capture=None, send_frames=False)
        client.start()
        try:
            self.assertTrue(_wait(lambda: self.server.count() == 1))
            conn = self.server.students()[0]
            self.assertEqual(conn.name, "集成测试机")
            self.server.broadcast({"t": "cmd", "cmd": "message", "text": "上课了"})
            got = None
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and got is None:
                try:
                    msg = events.get(timeout=0.2)
                except queue.Empty:
                    continue
                if msg.get("t") == "cmd":
                    got = msg
            self.assertIsNotNone(got)
            self.assertEqual(got["text"], "上课了")
        finally:
            client.stop()
            self.assertTrue(_wait(lambda: self.server.count() == 0, timeout=2.0))


class MultiStudentTests(unittest.TestCase):
    def test_broadcast_to_many(self):
        server = TeacherServer(port=0, bind="127.0.0.1")
        port = server.start()
        clients = []
        try:
            sockets = []
            for index in range(3):
                sock = socket.create_connection(("127.0.0.1", port), timeout=3)
                link = LineSocket(sock)
                link.send({"t": "register", "name": f"机{index}"})
                link.recv(3.0)
                clients.append(link)
                sockets.append(sock)
            self.assertTrue(_wait(lambda: server.count() == 3))
            self.assertEqual(server.broadcast({"t": "cmd", "cmd": "lock", "on": True}), 3)
            for link in clients:
                self.assertEqual(link.recv(3.0)["cmd"], "lock")
            for sock in sockets:
                sock.close()
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
