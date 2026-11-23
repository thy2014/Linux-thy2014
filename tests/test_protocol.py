import socket
import unittest

from thyclass.common.protocol import LineSocket, ProtocolError, encode


class ProtocolTests(unittest.TestCase):
    def test_roundtrip_over_socketpair(self):
        a, b = socket.socketpair()
        try:
            la, lb = LineSocket(a), LineSocket(b)
            la.send({"t": "cmd", "cmd": "lock", "on": True, "备注": "中文不乱码"})
            msg = lb.recv(2.0)
            self.assertEqual(msg["cmd"], "lock")
            self.assertTrue(msg["on"])
            self.assertEqual(msg["备注"], "中文不乱码")
        finally:
            a.close()
            b.close()

    def test_multiple_messages_in_one_chunk(self):
        a, b = socket.socketpair()
        try:
            la, lb = LineSocket(a), LineSocket(b)
            la.send({"n": 1})
            la.send({"n": 2})
            self.assertEqual(lb.recv(2.0)["n"], 1)
            self.assertEqual(lb.recv(2.0)["n"], 2)
        finally:
            a.close()
            b.close()

    def test_peer_close_returns_none(self):
        a, b = socket.socketpair()
        lb = LineSocket(b)
        a.close()
        self.assertIsNone(lb.recv(1.0))
        b.close()

    def test_bad_json_raises(self):
        a, b = socket.socketpair()
        try:
            a.sendall(b"not-json\n")
            with self.assertRaises(ProtocolError):
                LineSocket(b).recv(2.0)
        finally:
            a.close()
            b.close()

    def test_encode_rejects_non_dict(self):
        with self.assertRaises(ProtocolError):
            encode(["a"])  # type: ignore[arg-type]

    def test_oversized_line_raises(self):
        a, b = socket.socketpair()
        try:
            a.sendall(b"x" * 64)
            with self.assertRaises(ProtocolError):
                LineSocket(b, max_line=32).recv(2.0)
        finally:
            a.close()
            b.close()


if __name__ == "__main__":
    unittest.main()
