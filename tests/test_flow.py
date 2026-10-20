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

    def test_edit_expense(self):
        _, _, owner = self.call("/api/register", "POST", {"name": "Caio", "email": "caio@example.com", "password": "senha-segura"})
        _, _, other = self.call("/api/register", "POST", {"name": "Dani", "email": "dani@example.com", "password": "senha-segura"})
        original = {"description": "Fatura original", "kind": "Cartão de crédito", "account": "Cartão C", "amount_cents": 12550, "due_date": "2026-10-15"}
        _, created, _ = self.call("/api/expenses", "POST", original, owner)
        path = f"/api/expenses/{created['id']}"
        updated = {"description": "Parcela revisada", "kind": "Empréstimo", "account": "Banco D", "amount_cents": 98765, "due_date": "2026-11-20"}
        self.assertEqual(self.call(path, "PUT", updated)[0], 401)
        self.assertEqual(self.call(path, "PUT", updated, other)[0], 404)
        self.assertEqual(self.call("/api/expenses/999999", "PUT", updated, owner)[0], 404)
        for invalid in ({"amount_cents": 0}, {"amount_cents": 1.5}, {"due_date": "2026-02-30"}, {"description": ""}, {"kind": "Inválido"}, {"account": ""}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.call(path, "PUT", {**updated, **invalid}, owner)[0], 400)
        self.assertEqual(self.call(path, "PUT", None, owner)[0], 400)
        self.assertEqual(self.call("/api/expenses?month=2026-10", cookie=owner)[1]["expenses"], [{"id": created["id"], **original}])
        self.assertEqual(self.call(path, "PUT", updated, owner)[0], 200)
        self.assertEqual(self.call("/api/expenses?month=2026-10", cookie=owner)[1]["expenses"], [])
        self.assertEqual(self.call("/api/expenses?month=2026-11", cookie=owner)[1]["expenses"], [{"id": created["id"], **updated}])
        self.assertEqual(self.call("/api/accounts", cookie=owner)[1]["accounts"], ["Banco D"])
        self.assertEqual(self.call(path, "DELETE", cookie=owner)[0], 200)

    def test_monthly_order_is_persisted_and_isolated(self):
        _, _, owner = self.call("/api/register", "POST", {"name": "Eva", "email": "eva@example.com", "password": "senha-segura"})
        _, _, other = self.call("/api/register", "POST", {"name": "Fabio", "email": "fabio@example.com", "password": "senha-segura"})
        expense = {"description": "Fatura", "kind": "Cartão de crédito", "account": "Cartão E", "amount_cents": 10000, "due_date": "2026-10-15"}
        ids = [self.call("/api/expenses", "POST", expense, owner)[1]["id"] for _ in range(3)]
        november_id = self.call("/api/expenses", "POST", {**expense, "due_date": "2026-11-15"}, owner)[1]["id"]
        other_id = self.call("/api/expenses", "POST", expense, other)[1]["id"]
        order = [ids[1], ids[0], ids[2]]
        payload = {"month": "2026-10", "ids": order}
        path = "/api/expenses/order"
        self.assertEqual(self.call(path, "PUT", payload)[0], 401)
        self.assertEqual(self.call(path, "PUT", payload, other)[0], 409)
        for invalid, status in (({"ids": [ids[0]]}, 409), ({"ids": [ids[0], ids[0], ids[2]]}, 400),
                                ({"ids": [ids[0], ids[1], other_id]}, 409),
                                ({"ids": [ids[0], ids[1], november_id]}, 409),
                                ({"ids": [True]}, 400), ({"month": "2026-13"}, 400)):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.call(path, "PUT", {**payload, **invalid}, owner)[0], status)
        self.assertEqual(self.call(path, "PUT", payload, owner)[0], 200)
        def listed_ids(month="2026-10"):
            return [item["id"] for item in self.call(f"/api/expenses?month={month}", cookie=owner)[1]["expenses"]]
        self.assertEqual(listed_ids(), order)
        server.init_db()  # Startup migration is safe to repeat and preserves the saved order.
        self.assertEqual(listed_ids(), order)
        self.assertEqual(listed_ids("2026-11"), [november_id])
        self.assertEqual(self.call(f"/api/expenses/{ids[1]}", "PUT", {**expense, "due_date": "2026-10-25"}, owner)[0], 200)
        self.assertEqual(listed_ids(), order)
        new_id = self.call("/api/expenses", "POST", expense, owner)[1]["id"]
        self.assertEqual(listed_ids(), order + [new_id])
        self.assertEqual(self.call(f"/api/expenses/{ids[0]}", "PUT", {**expense, "due_date": "2026-11-20"}, owner)[0], 200)
        self.assertEqual(listed_ids(), [ids[1], ids[2], new_id])
        self.assertEqual(self.call(f"/api/expenses/{ids[2]}", "DELETE", cookie=owner)[0], 200)
        self.assertEqual(listed_ids(), [ids[1], new_id])

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
