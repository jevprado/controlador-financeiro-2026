"""Importação única de SQLite para um PostgreSQL vazio, sem copiar sessões."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

import database


def migrate(source_path):
    if not database.database_url():
        raise RuntimeError("Configure DATABASE_URL com o PostgreSQL de destino.")
    source_path = Path(source_path).resolve(strict=True)
    with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        # Read one consistent snapshot, including older SQLite schemas.
        users = [dict(row) for row in source.execute("SELECT id, name, email, password_hash, created_at FROM users")]
        expenses = [dict(row) for row in source.execute("SELECT * FROM expenses")]
        database.init_db(source_path)
        with database.connect(source_path) as target:
            target.execute("LOCK TABLE users, expenses, sessions IN ACCESS EXCLUSIVE MODE")
            for table in ("users", "expenses", "sessions"):
                if target.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    raise RuntimeError("O PostgreSQL de destino deve estar vazio; nenhum registro foi importado.")
            for user in users:
                target.execute(
                    "INSERT INTO users(id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    tuple(user[key] for key in ("id", "name", "email", "password_hash", "created_at")),
                )
            columns = ("id", "user_id", "description", "kind", "account", "amount_cents", "due_date", "created_at", "sort_order", "is_paid")
            for expense in expenses:
                expense.setdefault("sort_order", None)
                expense.setdefault("is_paid", 0)
                target.execute(
                    "INSERT INTO expenses(" + ", ".join(columns) + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(expense[key] for key in columns),
                )
            for table in ("users", "expenses"):
                target.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}"
                )
    return len(users), len(expenses)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Caminho do arquivo SQLite existente")
    args = parser.parse_args()
    users, expenses = migrate(args.source)
    print(f"Importação concluída: {users} usuários e {expenses} lançamentos. Faça login novamente.")
