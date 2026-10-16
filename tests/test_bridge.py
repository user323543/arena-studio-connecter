"""Smoke-Tests: Bridge-Auth, Prompt-Inhalt, Kommando-Roundtrip mit Fake-Plugin."""
import json
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arena_studio_connector import Bridge, build_prompt  # noqa: E402

PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, token=None, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class BridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = Bridge({}, token="test-token")
        cls.bridge.start(PORT)

    @classmethod
    def tearDownClass(cls):
        cls.bridge.stop()

    def test_auth_required(self):
        code, _ = call("GET", "/api/status")
        self.assertEqual(code, 401)
        code, data = call("GET", "/api/status", "test-token")
        self.assertEqual(code, 200)
        self.assertFalse(data["studio_connected"])

    def test_command_roundtrip(self):
        def fake_plugin():
            for _ in range(100):
                code, data = call("GET", "/plugin/poll", "test-token")
                if data.get("command"):
                    cmd = data["command"]
                    call("POST", "/plugin/result", "test-token",
                         {"id": cmd["id"], "ok": True, "result": {"echo": cmd["type"]}})
                    return
        t = threading.Thread(target=fake_plugin)
        t.start()
        code, data = call("POST", "/api/command", "test-token",
                          {"type": "place_info", "args": {}})
        t.join(5)
        self.assertEqual(code, 200)
        self.assertEqual(data["result"]["echo"], "place_info")

    def test_prompt_contains_place_and_instructions(self):
        p = build_prompt("https://x.trycloudflare.com", "TOK",
                         {"name": "Mein Spiel", "placeId": 123, "universeId": 456})
        for needle in ("https://x.trycloudflare.com", "TOK", "123", "456",
                       "/api/status", "/api/command", "/api/roblox/open-cloud",
                       "game-pass", "Authorization: Bearer"):
            self.assertIn(needle, p)


if __name__ == "__main__":
    unittest.main()
