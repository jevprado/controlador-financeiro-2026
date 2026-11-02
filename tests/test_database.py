import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import migrate_sqlite
import server
from database_test_support import isolated_database


class DatabaseTest(unittest.TestCase):
    def test_recurring_generation_rolls_back_expense_if_occurrence_cannot_be_saved(self):
        with patch.dict(os.environ, {}, clear=True), tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "recurring.db"
            database.init_db(path)
            with database.connect(path) as db:
                db.execute("INSERT INTO users(id, name, email, password_hash, created_at) VALUES(1, 'Ana', 'ana@example.com', 'hash', '2026-11-01')")
                db.execute("INSERT INTO recurring_expenses(user_id, description, kind, account, amount_cents, first_due_date, created_at) VALUES(1, 'Plano', 'Outros', 'Banco', 50000, '2026-11-10', '2026-11-01')")
            original_execute = database.Database.execute

            def fail_occurrence(db, sql, params=()):
                if "INSERT INTO recurring_occurrences" in sql:
                    raise RuntimeError("Falha simulada ao salvar ocorrência")
                return original_execute(db, sql, params)

            with patch.object(server, "DB_PATH", path), patch.object(server, "current_month", return_value="2026-11"):
                with patch.object(database.Database, "execute", fail_occurrence):
                    with self.assertRaisesRegex(RuntimeError, "Falha simulada"):
                        server.generate_recurring(1)
                with database.connect(path) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"], 0)
                    self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM recurring_occurrences").fetchone()["n"], 0)
                server.generate_recurring(1)
                server.generate_recurring(1)
                with database.connect(path) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"], 1)

    def test_vercel_requires_external_database(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "missing" / "finance.db"
                with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                    database.init_db(path)
                self.assertFalse(path.parent.exists())

    def test_invalid_url_never_falls_back_to_sqlite(self):
        for url in ("", "sqlite:///tmp/finance.db", "postgresql://host/"):
            with self.subTest(url=url), patch.dict(os.environ, {"DATABASE_URL": url}, clear=True):
                with self.assertRaises(RuntimeError):
                    database.database_url()

    def test_vercel_requires_tls(self):
        with patch.dict(os.environ, {"VERCEL": "1", "DATABASE_URL": "postgresql://host/db?sslmode=disable"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TLS"):
                database.database_url()

    def test_sqlite_legacy_migration_and_rollback(self):
        with patch.dict(os.environ, {}, clear=True), tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE expenses(id INTEGER PRIMARY KEY, user_id INTEGER, due_date TEXT)")
                db.execute("INSERT INTO expenses VALUES(1, 1, '2026-10-01')")
            database.init_db(path)
            database.init_db(path)
            with database.connect(path) as db:
                row = db.execute("SELECT sort_order, is_paid FROM expenses").fetchone()
                self.assertEqual(tuple(row), (None, 0))
            with self.assertRaises(ValueError):
                with database.connect(path) as db:
                    db.execute("DELETE FROM expenses")
                    raise ValueError("rollback")
            with database.connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses").fetchone()[0], 1)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Configure TEST_DATABASE_URL para testar PostgreSQL")
class PostgresMigrationTest(unittest.TestCase):
    def test_remote_persistence_without_local_directory(self):
        with isolated_database(), tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "must-not-be-created" / "finance.db"
            database.init_db(path)
            database.init_db(path)
            with database.connect(path) as db:
                db.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES('Ana','ana@example.com','hash','2026-10-01')")
            with self.assertRaises(ValueError):
                with database.connect(path) as db:
                    db.execute("DELETE FROM users")
                    raise ValueError("rollback")
            with database.connect(path) as db:
                self.assertEqual(db.execute("SELECT name FROM users").fetchone()["name"], "Ana")
            self.assertFalse(path.parent.exists())

    def test_migration_preserves_data_and_sequences_and_refuses_nonempty_target(self):
        with isolated_database(), tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.db"
            original_hash = server.password_hash("senha-original")
            with patch.dict(os.environ):
                os.environ.pop("DATABASE_URL")
                database.init_db(path)
                with database.connect(path) as source:
                    source.execute("INSERT INTO users VALUES(10, 'Ana', 'ana@example.com', ?, '2026-10-01')", (original_hash,))
                    source.execute("INSERT INTO expenses VALUES(20, 10, 'Fatura', 'Outros', 'Cartão', 1234, '2026-10-01', '2026-10-01', 3, 1)")
                    source.execute("INSERT INTO sessions VALUES('old-token-hash', 10, '2099-01-01')")
                    source.execute("INSERT INTO recurring_expenses VALUES(30, 10, 'Plano', 'Outros', 'Banco', 50000, '2026-10-31', 1, '2026-10-01')")
                    source.execute("INSERT INTO recurring_occurrences VALUES(30, '2026-10')")
            self.assertEqual(migrate_sqlite.migrate(path), (1, 1))
            with database.connect(path) as db:
                stored = db.execute("SELECT password_hash FROM users").fetchone()["password_hash"]
                self.assertEqual(stored, original_hash)
                self.assertTrue(server.verify_password("senha-original", stored))
                expense = db.execute("SELECT * FROM expenses").fetchone()
                self.assertEqual((expense["id"], expense["user_id"], expense["amount_cents"], expense["sort_order"], expense["is_paid"]), (20, 10, 1234, 3, 1))
                self.assertIsNone(db.execute("SELECT * FROM sessions").fetchone())
                self.assertEqual(db.execute("SELECT first_due_date FROM recurring_expenses WHERE id = 30").fetchone()["first_due_date"], "2026-10-31")
                self.assertEqual(db.execute("SELECT month FROM recurring_occurrences WHERE recurring_id = 30").fetchone()["month"], "2026-10")
                rule_id = db.execute("INSERT INTO recurring_expenses(user_id, description, kind, account, amount_cents, first_due_date, created_at) VALUES(10, 'Internet', 'Outros', 'Banco', 10000, '2026-11-01', '2026-10-01') RETURNING id").fetchone()["id"]
                self.assertGreater(rule_id, 30)
                new_id = db.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES('Bia','bia@example.com','hash','2026-10-01') RETURNING id").fetchone()["id"]
                self.assertGreater(new_id, 10)
                new_expense = db.execute("INSERT INTO expenses(user_id,description,kind,account,amount_cents,due_date,created_at) VALUES(10,'Nova','Outros','Cartão',100,'2026-10-01','2026-10-01') RETURNING id").fetchone()["id"]
                self.assertGreater(new_expense, 20)
            with self.assertRaisesRegex(RuntimeError, "vazio"):
                migrate_sqlite.migrate(path)

    def test_failed_import_rolls_back_all_rows(self):
        with isolated_database(), tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "invalid.db"
            with patch.dict(os.environ):
                os.environ.pop("DATABASE_URL")
                database.init_db(path)
            # Simulate an invalid legacy file with an orphaned expense.
            with sqlite3.connect(path) as db:
                db.execute("INSERT INTO users VALUES(1,'Ana','ana@example.com','hash','2026-10-01')")
                db.execute("INSERT INTO expenses VALUES(1,999,'Fatura','Outros','Cartão',100,'2026-10-01','2026-10-01',NULL,0)")
            import psycopg
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                migrate_sqlite.migrate(path)
            with database.connect(path) as db:
                self.assertIsNone(db.execute("SELECT * FROM users").fetchone())
                self.assertIsNone(db.execute("SELECT * FROM expenses").fetchone())
