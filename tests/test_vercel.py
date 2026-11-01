import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
from api import index
from database_test_support import isolated_database


class VercelEntryPointTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_database())
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.temp) / "finance.db"
        self.enterContext(patch.object(server, "DB_PATH", self.path))
        self.enterContext(patch.object(index, "_database_ready", False))
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), index.handler)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def request(self, path, data=None, cookie=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        request = Request(self.base + path, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            return urlopen(request)
        except HTTPError as error:
            return error

    def test_registration_initializes_a_fresh_database(self):
        invite = "convite-de-teste-12345678901234567890"
        with patch.dict("os.environ", {"ALLOWED_EMAILS": "ana@example.com", "REGISTRATION_INVITE_CODE": invite}):
            with self.request("/api/register", {
                "name": "Ana", "email": "ana@example.com", "password": "senha-segura", "invite_code": invite,
            }) as response:
                self.assertEqual(response.status, 201)
                self.assertEqual(json.load(response)["user"]["email"], "ana@example.com")
                cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            with self.request("/api/me", cookie=cookie) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response)["user"]["email"], "ana@example.com")

    def test_initialization_failure_is_json_and_can_be_retried(self):
        with patch.object(index, "init_db", side_effect=RuntimeError("private-database-password")):
            with self.assertLogs("api.index", level="ERROR") as logs, self.request("/api/me") as response:
                self.assertEqual(response.status, 503)
                self.assertIn("application/json", response.headers["Content-Type"])
                body = json.load(response)
                self.assertIn("indisponível", body["error"])
                self.assertTrue(body["reference"])
                self.assertNotIn("private-database-password", json.dumps(body))
            self.assertNotIn("private-database-password", " ".join(logs.output))
            self.assertFalse(index._database_ready)
        with self.request("/api/me") as response:
            self.assertEqual(response.status, 401)
            self.assertTrue(index._database_ready)

    def test_runtime_database_failure_is_json(self):
        index.ensure_database()
        with patch.object(server, "connect", side_effect=RuntimeError("private-database-password")):
            with self.assertLogs("api.index", level="ERROR"), self.request("/api/me", cookie="session=" + "0" * 64) as response:
                self.assertEqual(response.status, 503)
                self.assertIn("indisponível", json.load(response)["error"])

    def test_static_assets_work_even_when_database_is_unavailable(self):
        with patch.object(index, "init_db", side_effect=RuntimeError("database offline")) as initialize:
            with self.request("/") as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'/api.js', response.read())
            with self.request("/api.js") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("javascript", response.headers["Content-Type"])
            initialize.assert_not_called()
