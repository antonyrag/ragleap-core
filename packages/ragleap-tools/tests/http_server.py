"""A tiny local HTTP server whose misbehaviour is selected per test (not a test module)."""

import http.server
import threading


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self._serve()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        self._serve()

    def _head(self, status, length=None, chunked=False):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if length is not None:
            self.send_header("Content-Length", str(length))
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()

    def _serve(self):
        owner = self.server.owner
        owner.requests.append((self.command, self.path, dict(self.headers)))
        mode, status = owner.mode, owner.status
        try:
            if mode == "ok":
                self._head(status, len(owner.payload))
                self.wfile.write(owner.payload)
            elif mode == "big":
                body = b"x" * (2 * 1024 * 1024)
                self._head(status, len(body))
                self.wfile.write(body)
            elif mode == "bigchunked":
                self._head(status, chunked=True)
                for _ in range(32):
                    self.wfile.write(b"%x\r\n" % 65536 + b"y" * 65536 + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            elif mode == "drip":
                self._head(status, 1000)
                for _ in range(1000):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    if owner.stop.wait(0.2):
                        break
            elif mode == "stall":
                self._head(status, 10)
                owner.stop.wait(30)
            elif mode == "declared_big_stall":
                self._head(status, 2 * 1024 * 1024)
                owner.stop.wait(30)
            elif mode == "headdelay":
                owner.stop.wait(30)
            elif mode == "trunc":
                self._head(status, 100)
                self.wfile.write(b"x" * 10)
        except OSError:
            pass


class LocalServer:
    def __init__(self):
        self.mode = "ok"
        self.status = 200
        self.payload = b"{}"
        self.requests = []
        self.stop = threading.Event()
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.owner = self
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    @property
    def url(self):
        return "http://127.0.0.1:%d/" % self._httpd.server_address[1]

    def start(self):
        self._thread.start()
        return self

    def shutdown(self):
        self.stop.set()
        self._httpd.shutdown()
        self._httpd.server_close()
