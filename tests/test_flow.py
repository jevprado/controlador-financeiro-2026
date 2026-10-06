import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class FinanceFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.temp.name) / "finance.db"
        server.init_db()
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def call(self, path, method="GET", data=None, cookie=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers.get("Set-Cookie", "").split(";", 1)[0]

    def test_accounts_are_isolated(self):
        status, _, first = self.call("/api/register", "POST", {"name": "Ana", "email": "ana@example.com", "password": "senha-segura"})
        self.assertEqual(status, 201)
        status, _, second = self.call("/api/register", "POST", {"name": "Bia", "email": "bia@example.com", "password": "outra-senha"})
        self.assertEqual(status, 201)
        status, created, _ = self.call("/api/expenses", "POST", {"description": "Fatura", "kind": "Cartão de crédito", "account": "Cartão A", "amount_cents": 12550, "due_date": "2026-10-15"}, first)
        self.assertEqual(status, 201)
        expense_id = created["id"]
        self.assertEqual(self.call("/api/accounts", cookie=first)[1]["accounts"], ["Cartão A"])
        self.assertEqual(self.call("/api/accounts", cookie=second)[1]["accounts"], [])
        self.assertEqual(self.call("/api/accounts")[0], 401)
        self.call("/api/expenses", "POST", {"description": "Outra fatura", "kind": "Cartão de crédito", "account": "Cartão A", "amount_cents": 1000, "due_date": "2026-11-15"}, first)
        self.call("/api/expenses", "POST", {"description": "Empréstimo", "kind": "Empréstimo", "account": "Banco B", "amount_cents": 2000, "due_date": "2026-11-15"}, first)
        self.assertEqual(self.call("/api/accounts", cookie=first)[1]["accounts"], ["Banco B", "Cartão A"])
        self.assertEqual(len(self.call("/api/expenses?month=2026-10", cookie=first)[1]["expenses"]), 1)
        self.assertEqual(self.call("/api/expenses?month=2026-10", cookie=second)[1]["expenses"], [])
        self.assertEqual(self.call(f"/api/expenses/{expense_id}", "DELETE", cookie=second)[0], 404)
        self.assertEqual(self.call("/api/expenses?month=2026-10", cookie=first)[1]["expenses"][0]["id"], expense_id)
        self.assertEqual(self.call("/api/expenses?month=2026-10")[0], 401)
        self.assertEqual(self.call("/api/logout", "POST", {}, first)[0], 200)
        self.assertEqual(self.call("/api/me", cookie=first)[0], 401)
        self.assertEqual(self.call("/api/login", "POST", {"email": "ana@example.com", "password": "senha-errada"})[0], 401)
        self.assertEqual(self.call("/api/login", "POST", {"email": "ana@example.com", "password": "senha-segura"})[0], 200)


if __name__ == "__main__":
    unittest.main()
