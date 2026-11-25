import http.server
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import app_health_check as hc  # noqa: E402

CODES = {"/ok": 200, "/slow": 200, "/missing": 404, "/broken": 500, "/unavailable": 503}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        if self.path == "/slow":
            time.sleep(2)
        self.send_response(CODES.get(self.path, 404))
        self.end_headers()
        self.wfile.write(b"hello\n")

    def log_message(self, *args):
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wisecow_like_server():
    """Answers once the way wisecow.sh does: no reason phrase, no headers."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(1024)
        conn.sendall(b"HTTP/1.1 200\n\n\n<pre> moo </pre>\n")
        conn.close()
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{srv.getsockname()[1]}/"


class CheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = QuietServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_200_is_up(self):
        result = hc.check(self.base + "/ok")
        self.assertTrue(result.up)
        self.assertEqual(result.status, 200)

    def test_errors_are_down(self):
        for path in ("/missing", "/broken", "/unavailable"):
            with self.subTest(path=path):
                result = hc.check(self.base + path)
                self.assertFalse(result.up)
                self.assertEqual(result.status, CODES[path])

    def test_redirect_is_followed(self):
        result = hc.check(self.base + "/redirect")
        self.assertTrue(result.up)
        self.assertEqual(result.status, 200)

    def test_custom_expected_codes(self):
        self.assertTrue(hc.check(self.base + "/missing", expected={404}).up)
        self.assertFalse(hc.check(self.base + "/ok", expected={204}).up)

    def test_timeout_is_down(self):
        result = hc.check(self.base + "/slow", timeout=0.5)
        self.assertFalse(result.up)
        self.assertIsNone(result.status)
        self.assertTrue(result.error)

    def test_connection_refused_is_down(self):
        result = hc.check(f"http://127.0.0.1:{free_port()}/")
        self.assertFalse(result.up)
        self.assertIsNone(result.status)

    def test_wisecow_response(self):
        result = hc.check(wisecow_like_server())
        self.assertTrue(result.up)
        self.assertEqual(result.status, 200)

    def test_retries_stop_when_up(self):
        result = hc.check_with_retries(self.base + "/ok", retries=3, delay=0)
        self.assertTrue(result.up)

    def test_exit_code(self):
        self.assertEqual(hc.main([self.base + "/ok"]), 0)
        self.assertEqual(hc.main([self.base + "/ok", self.base + "/broken", "-r", "0"]), 1)


class ParseCodesTest(unittest.TestCase):
    def test_single_and_ranges(self):
        self.assertEqual(hc.parse_codes("200"), {200})
        self.assertEqual(hc.parse_codes("200,204, 300-302"), {200, 204, 300, 301, 302})

    def test_empty_is_rejected(self):
        with self.assertRaises(ValueError):
            hc.parse_codes(" , ")


if __name__ == "__main__":
    unittest.main()
