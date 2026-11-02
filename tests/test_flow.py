import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import server
from api import index as vercel_entrypoint
from database_test_support import isolated_database


TEST_INVITE_CODE = "convite-exclusivo-para-testes-1234567890"


class FinanceFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(isolated_database())
        cls.enterClassContext(patch.dict(os.environ, {
            "ALLOWED_EMAILS": ",".join(f"{name}@example.com" for name in ("ana", "bia", "caio", "dani", "eva", "fabio", "gabi", "hugo", "iara", "joana", "kaio")),
            "REGISTRATION_INVITE_CODE": TEST_INVITE_CODE,
        }))
        cls.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.temp.name) / "finance.db"
        server.init_db()
        handler = server.Handler
        if os.environ.get("TEST_VERCEL_HANDLER"):
            cls.enterClassContext(patch.object(vercel_entrypoint, "_database_ready", False))
            handler = vercel_entrypoint.handler
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def call(self, path, method="GET", data=None, cookie=None):
        if path == "/api/register" and isinstance(data, dict):
            data = {"invite_code": TEST_INVITE_CODE, **data}
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

    def test_registration_requires_allowed_email_and_invite(self):
        user = {"name": "Joana", "email": "joana@example.com", "password": "senha-segura"}
        for change in ({"email": "visitante@example.com"}, {"email": "ana@example.com.evil.test"},
                       {"invite_code": None}, {"invite_code": ""}, {"invite_code": "incorreto"},
                       {"invite_code": [TEST_INVITE_CODE]}, {"invite_code": "á" * 32}):
            with self.subTest(change=change):
                status, _, cookie = self.call("/api/register", "POST", {**user, **change})
                self.assertEqual(status, 403)
                self.assertFalse(cookie)
        with server.connect() as db:
            self.assertIsNone(db.execute("SELECT id FROM users WHERE email = ?", (user["email"],)).fetchone())
        with patch.dict(os.environ, {"ALLOWED_EMAILS": " JOANA@EXAMPLE.COM , kaio@example.com "}):
            status, result, cookie = self.call("/api/register", "POST", {**user, "email": " Joana@Example.com "})
            self.assertEqual(status, 201)
            self.assertEqual(result["user"]["email"], user["email"])
            self.assertEqual(self.call("/api/me", cookie=cookie)[0], 200)

    def test_missing_or_invalid_access_configuration_denies_access(self):
        user = {"name": "Kaio", "email": "kaio@example.com", "password": "senha-segura"}
        for value in (None, "", "*", "kaio@example.com,invalid", "kaio@example.com,"):
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("ALLOWED_EMAILS", None)
                else:
                    os.environ["ALLOWED_EMAILS"] = value
                self.assertEqual(self.call("/api/register", "POST", user)[0], 403)
                self.assertEqual(self.call("/api/login", "POST", user)[0], 401)
        for value in (None, "", "curto", "x" * 257):
            with self.subTest(invite=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("REGISTRATION_INVITE_CODE", None)
                else:
                    os.environ["REGISTRATION_INVITE_CODE"] = value
                self.assertEqual(self.call("/api/register", "POST", user)[0], 403)

    def test_removing_email_blocks_login_and_existing_sessions(self):
        user = {"name": "Kaio", "email": "kaio@example.com", "password": "senha-segura"}
        _, _, cookie = self.call("/api/register", "POST", user)
        with patch.dict(os.environ, {"REGISTRATION_INVITE_CODE": ""}):
            # Closing registration must not lock existing authorized users out.
            self.assertEqual(self.call("/api/login", "POST", user)[0], 200)
            self.assertEqual(self.call("/api/me", cookie=cookie)[0], 200)
        with patch.dict(os.environ, {"ALLOWED_EMAILS": "ana@example.com"}):
            self.assertEqual(self.call("/api/login", "POST", user)[0], 401)
            self.assertEqual(self.call("/api/me", cookie=cookie)[0], 401)
            self.assertEqual(self.call("/api/accounts", cookie=cookie)[0], 401)
            self.assertEqual(self.call("/api/expenses?month=2026-10", cookie=cookie)[0], 401)
            expense = {"description": "Fatura", "kind": "Outros", "account": "Cartão", "amount_cents": 100, "due_date": "2026-10-01"}
            self.assertEqual(self.call("/api/expenses", "POST", expense, cookie)[0], 401)
            self.assertEqual(self.call("/api/expenses/1", "PUT", expense, cookie)[0], 401)
            self.assertEqual(self.call("/api/expenses/1", "DELETE", cookie=cookie)[0], 401)
            self.assertEqual(self.call("/api/expenses/1/payment", "PUT", {"is_paid": True}, cookie)[0], 401)
            self.assertEqual(self.call("/api/expenses/order", "PUT", {"month": "2026-10", "ids": []}, cookie)[0], 401)
        # A session rejected while the email was removed remains invalid.
        self.assertEqual(self.call("/api/me", cookie=cookie)[0], 401)
        self.assertEqual(self.call("/api/login", "POST", user)[0], 200)

    def test_duplicate_registration_preserves_original_login(self):
        original = {"name": "Iara", "email": "iara@example.com", "password": "senha-original"}
        self.assertEqual(self.call("/api/register", "POST", original)[0], 201)
        self.assertEqual(self.call("/api/register", "POST", {**original, "password": "outra-senha"})[0], 409)
        self.assertEqual(self.call("/api/login", "POST", original)[0], 200)
        self.assertEqual(self.call("/api/login", "POST", {**original, "password": "outra-senha"})[0], 401)

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
        self.assertEqual(self.call("/api/expenses?month=2026-10", cookie=owner)[1]["expenses"], [{"id": created["id"], **original, "is_paid": False}])
        self.assertEqual(self.call(path, "PUT", updated, owner)[0], 200)
        self.assertEqual(self.call("/api/expenses?month=2026-10", cookie=owner)[1]["expenses"], [])
        self.assertEqual(self.call("/api/expenses?month=2026-11", cookie=owner)[1]["expenses"], [{"id": created["id"], **updated, "is_paid": False}])
        self.assertEqual(self.call("/api/accounts", cookie=owner)[1]["accounts"], ["Banco D"])
        self.assertEqual(self.call(path, "DELETE", cookie=owner)[0], 200)

    def test_payment_is_persisted_reversible_and_isolated(self):
        _, _, owner = self.call("/api/register", "POST", {"name": "Gabi", "email": "gabi@example.com", "password": "senha-segura"})
        _, _, other = self.call("/api/register", "POST", {"name": "Hugo", "email": "hugo@example.com", "password": "senha-segura"})
        expense = {"description": "Fatura", "kind": "Cartão de crédito", "account": "Cartão G", "amount_cents": 10000, "due_date": "2026-10-15"}
        _, created, _ = self.call("/api/expenses", "POST", expense, owner)
        path = f"/api/expenses/{created['id']}"

        def listed_expense():
            return self.call("/api/expenses?month=2026-10", cookie=owner)[1]["expenses"][0]

        self.assertIs(listed_expense()["is_paid"], False)
        self.assertEqual(self.call(path + "/payment", "PUT", {"is_paid": True})[0], 401)
        self.assertEqual(self.call(path + "/payment", "PUT", {"is_paid": True}, other)[0], 404)
        self.assertEqual(self.call("/api/expenses/999999/payment", "PUT", {"is_paid": True}, owner)[0], 404)
        for invalid in (None, {}, {"is_paid": 1}, {"is_paid": "false"}, {"is_paid": None}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.call(path + "/payment", "PUT", invalid, owner)[0], 400)
        self.assertIs(listed_expense()["is_paid"], False)
        self.assertEqual(self.call(path + "/payment", "PUT", {"is_paid": True}, owner)[:2], (200, {"is_paid": True}))
        server.init_db()
        self.assertIs(listed_expense()["is_paid"], True)
        updated = {**expense, "description": "Fatura revisada"}
        self.assertEqual(self.call(path, "PUT", updated, owner)[0], 200)
        self.assertEqual(listed_expense(), {"id": created["id"], **updated, "is_paid": True})
        self.assertEqual(self.call(path + "/payment", "PUT", {"is_paid": False}, owner)[0], 200)
        self.assertIs(listed_expense()["is_paid"], False)

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

    def test_monthly_totals_include_all_expenses_and_are_isolated(self):
        # Use independent accounts so other flow fixtures do not affect totals.
        with patch.dict(os.environ, {"ALLOWED_EMAILS": "totais@example.com,outro-total@example.com"}):
            _, _, owner = self.call("/api/register", "POST", {"name": "Totais", "email": "totais@example.com", "password": "senha-segura"})
            _, _, other = self.call("/api/register", "POST", {"name": "Outro", "email": "outro-total@example.com", "password": "senha-segura"})
            path = "/api/expenses/monthly-totals"
            self.assertEqual(self.call(path)[0], 401)
            self.assertEqual(self.call(path, cookie=owner)[1], {"months": []})
            expense = {"description": "Fatura", "kind": "Cartão de crédito", "account": "Cartão", "amount_cents": 12550, "due_date": "2025-12-15"}
            _, created, _ = self.call("/api/expenses", "POST", expense, owner)
            self.call(f"/api/expenses/{created['id']}/payment", "PUT", {"is_paid": True}, owner)
            self.call("/api/expenses", "POST", {**expense, "kind": "Outros", "amount_cents": 50}, owner)
            self.call("/api/expenses", "POST", {**expense, "amount_cents": 30000, "due_date": "2026-02-01"}, owner)
            self.call("/api/expenses", "POST", expense, other)
            self.assertEqual(self.call(path, cookie=owner)[1], {"months": [
                {"month": "2025-12", "total_cents": 12600, "expense_count": 2},
                {"month": "2026-02", "total_cents": 30000, "expense_count": 1},
            ]})
            self.assertEqual(self.call(path, cookie=other)[1]["months"], [
                {"month": "2025-12", "total_cents": 12550, "expense_count": 1},
            ])
            self.call(f"/api/expenses/{created['id']}", "PUT", {**expense, "due_date": "2026-02-01"}, owner)
            self.assertEqual(self.call(path, cookie=owner)[1]["months"][1]["total_cents"], 42550)
            self.call(f"/api/expenses/{created['id']}", "DELETE", cookie=owner)
            self.assertEqual(self.call(path, cookie=owner)[1]["months"][1]["total_cents"], 30000)

    def test_recurring_month_end_payment_edits_deletion_and_stop(self):
        with patch.dict(os.environ, {"ALLOWED_EMAILS": "recorrente@example.com"}), patch.object(server, "current_month", return_value="2024-03"):
            _, _, owner = self.call("/api/register", "POST", {"name": "Recorrente", "email": "recorrente@example.com", "password": "senha-segura"})
            expense = {"description": "Plano de saúde", "kind": "Outros", "account": "Banco", "amount_cents": 50000, "due_date": "2024-01-31"}
            status, created, _ = self.call("/api/recurring-expenses", "POST", expense, owner)
            self.assertEqual(status, 201)
            rule_path = f"/api/recurring-expenses/{created['id']}"

            def items(month):
                status, result, _ = self.call(f"/api/expenses?month={month}", cookie=owner)
                self.assertEqual(status, 200)
                return result["expenses"]

            january, february, march = [items(f"2024-{month}")[0] for month in ("01", "02", "03")]
            self.assertEqual([item["due_date"] for item in (january, february, march)], ["2024-01-31", "2024-02-29", "2024-03-31"])
            self.assertTrue(all(item["amount_cents"] == 50000 and not item["is_paid"] for item in (january, february, march)))
            self.call(f"/api/expenses/{january['id']}/payment", "PUT", {"is_paid": True}, owner)
            self.assertFalse(items("2024-02")[0]["is_paid"])
            self.call(f"/api/expenses/{january['id']}", "PUT", {**expense, "amount_cents": 60000}, owner)
            self.assertEqual(items("2024-01")[0]["amount_cents"], 60000)
            self.assertEqual(items("2024-02")[0]["amount_cents"], 50000)
            self.call(f"/api/expenses/{february['id']}", "DELETE", cookie=owner)
            server.init_db()
            self.assertEqual(items("2024-02"), [])  # Explicit deletion must not regenerate it.
            totals = self.call("/api/expenses/monthly-totals", cookie=owner)[1]["months"]
            self.assertEqual([item["total_cents"] for item in totals], [60000, 50000])
            self.assertEqual(self.call(rule_path, "DELETE", cookie=owner)[0], 200)
            self.assertEqual(self.call("/api/recurring-expenses", cookie=owner)[1]["recurring_expenses"], [])
            self.assertEqual(items("2024-04"), [])
            self.assertTrue(items("2024-01")[0]["is_paid"])
            self.assertEqual(len(items("2024-03")), 1)

    def test_recurring_catches_up_without_duplicates_during_concurrent_visits(self):
        with patch.dict(os.environ, {"ALLOWED_EMAILS": "automatico@example.com"}), patch.object(server, "current_month", return_value="2025-12"):
            _, _, owner = self.call("/api/register", "POST", {"name": "Automático", "email": "automatico@example.com", "password": "senha-segura"})
            expense = {"description": "Internet", "kind": "Outros", "account": "Banco", "amount_cents": 9990, "due_date": "2025-12-31"}
            self.assertEqual(self.call("/api/recurring-expenses", "POST", expense, owner)[0], 201)
            with patch.object(server, "current_month", return_value="2026-02"):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(lambda _: self.call("/api/expenses/monthly-totals", cookie=owner), range(6)))
                for status, result, _ in results:
                    self.assertEqual(status, 200)
                    self.assertEqual(result["months"], [
                        {"month": month, "total_cents": 9990, "expense_count": 1}
                        for month in ("2025-12", "2026-01", "2026-02")
                    ])
                feb = self.call("/api/expenses?month=2026-02", cookie=owner)[1]["expenses"]
                self.assertEqual(feb[0]["due_date"], "2026-02-28")

    def test_recurring_validation_future_start_and_user_isolation(self):
        with patch.dict(os.environ, {"ALLOWED_EMAILS": "regra@example.com,outra-regra@example.com"}), patch.object(server, "current_month", return_value="2026-11"):
            _, _, owner = self.call("/api/register", "POST", {"name": "Regra", "email": "regra@example.com", "password": "senha-segura"})
            _, _, other = self.call("/api/register", "POST", {"name": "Outra", "email": "outra-regra@example.com", "password": "senha-segura"})
            path = "/api/recurring-expenses"
            expense = {"description": "Aluguel", "kind": "Outros", "account": "Banco", "amount_cents": 100000, "due_date": "2027-01-10"}
            self.assertEqual(self.call(path)[0], 401)
            self.assertEqual(self.call(path, "POST", expense)[0], 401)
            for invalid in ({"amount_cents": 0}, {"amount_cents": True}, {"due_date": "2026-02-30"}, {"due_date": None}, {"description": ""}, {"kind": "Inválido"}):
                self.assertEqual(self.call(path, "POST", {**expense, **invalid}, owner)[0], 400)
            status, created, _ = self.call(path, "POST", expense, owner)
            self.assertEqual(status, 201)
            self.assertEqual(len(self.call(path, cookie=owner)[1]["recurring_expenses"]), 1)
            self.assertEqual(self.call(path, cookie=other)[1]["recurring_expenses"], [])
            self.assertEqual(self.call(path + f"/{created['id']}", "DELETE")[0], 401)
            self.assertEqual(self.call(path + f"/{created['id']}", "DELETE", cookie=other)[0], 404)
            self.assertEqual(self.call("/api/expenses?month=2026-11", cookie=owner)[1]["expenses"], [])
            self.assertEqual(len(self.call("/api/expenses?month=2027-01", cookie=owner)[1]["expenses"]), 1)
            self.assertEqual(self.call("/api/expenses?month=2027-01", cookie=other)[1]["expenses"], [])

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
