import importlib.util
import json
from pathlib import Path
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "app" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


app = module("server")
memory = module("memory_job")


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.create_server(port=0, concurrency=1, version="unit")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get(self, path):
        try:
            response = urllib.request.urlopen(self.url + path, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            payload = response.read()
            return response.code, json.loads(payload) if payload else None

    def test_health_and_identity(self):
        for path in ("/healthz", "/readyz"):
            self.assertEqual(self.get(path), (200, {"status": "ok"}))
        self.assertEqual(self.get("/api/info")[1]["version"], "unit")
        self.assertEqual(self.get("/absent")[0], 404)

    def test_fixed_work(self):
        expected = 0
        for i in range(25):
            expected = (expected * 1664525 + i + 1013904223) & 0xFFFFFFFF
        for _ in range(2):
            code, body = self.get("/api/cpu-load?iterations=25")
            self.assertEqual(code, 200)
            self.assertEqual(body["checksum"], expected)
            self.assertEqual(body["iterations"], 25)

    def test_bad_inputs(self):
        for q in ("iterations=0", "iterations=-1", "iterations=2000001",
                  "iterations=", "iterations=1&iterations=2", "x=2",
                  "iterations=1.5", "iterations=abc", "x" * 130):
            with self.subTest(q=q):
                self.assertEqual(self.get("/api/cpu-load?" + q)[0], 400)

    def test_concurrency_rejection(self):
        self.server.slots.acquire()
        try:
            self.assertEqual(self.get("/api/cpu-load?iterations=1")[0], 503)
        finally:
            self.server.slots.release()

    def test_deadline(self):
        with self.assertRaises(TimeoutError):
            app.cpu_work(2000, time.monotonic() - 1)

    def test_cpu_time_increases(self):
        before = time.process_time()
        app.cpu_work(100_000, time.monotonic() + 5)
        self.assertGreater(time.process_time() - before, 0)

    def test_invalid_server_config(self):
        for kwargs in ({"concurrency": 0}, {"work_timeout": 99}, {"default_iterations": 0}):
            with self.assertRaises(ValueError):
                app.create_server(port=0, **kwargs)

    def test_memory_safe_and_bounds(self):
        self.assertEqual(memory.allocate(2, 1, 0, 2, safe=True), 2)
        for total in (0, 9, 192):
            with self.assertRaises(ValueError):
                memory.allocate(total, 1, 0, 2, safe=True)
        with self.assertRaises(TimeoutError):
            memory.allocate(2, 1, 1, .01, safe=True)


if __name__ == "__main__":
    unittest.main()
