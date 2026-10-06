"""Servidor local do controlador financeiro, usando apenas a biblioteca padrão."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("FINANCE_DB", ROOT / "data" / "finance.db"))
SESSION_DAYS = 30
MAX_BODY = 16_384
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
KINDS = {"Cartão de crédito", "Cheque especial", "Empréstimo", "Outros"}


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                description TEXT NOT NULL,
                kind TEXT NOT NULL,
                account TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                due_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS expenses_user_date ON expenses(user_id, due_date);
        """)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password, stored):
    try:
        salt_hex, _ = stored.split(":", 1)
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt_hex)), stored)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Handler(BaseHTTPRequestHandler):
    server_version = "FinanceiroLocal/1.0"

    def send_json(self, status, data, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def cookie_header(self, token, max_age):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return f"session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}"

    def current_user(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["session"].value if "session" in cookie else ""
        except Exception:
            return None
        if not token or len(token) != 64:
            return None
        with connect() as db:
            row = db.execute("""
                SELECT users.id, users.name, users.email FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """, (token_hash(token), utc_now())).fetchone()
        return dict(row) if row else None

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return None
            value = json.loads(self.rfile.read(length))
            return value if isinstance(value, dict) else None
        except (ValueError, json.JSONDecodeError):
            return None

    def mutation_allowed(self):
        # Cookies are restricted to the same site; also reject cross-origin writes.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        return not origin or urlsplit(origin).netloc == host

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/me":
            user = self.current_user()
            return self.send_json(HTTPStatus.OK if user else HTTPStatus.UNAUTHORIZED, {"user": user})
        if path == "/api/accounts":
            user = self.current_user()
            if not user:
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
            with connect() as db:
                rows = db.execute("""
                    SELECT account FROM expenses WHERE user_id = ?
                    GROUP BY account COLLATE NOCASE
                    ORDER BY account COLLATE NOCASE
                """, (user["id"],)).fetchall()
            return self.send_json(HTTPStatus.OK, {"accounts": [row["account"] for row in rows]})
        if path == "/api/expenses":
            user = self.current_user()
            if not user:
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
            month = dict(parse_qsl(urlsplit(self.path).query)).get("month", "")
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Mês inválido."})
            with connect() as db:
                rows = db.execute("""
                    SELECT id, description, kind, account, amount_cents, due_date
                    FROM expenses WHERE user_id = ? AND substr(due_date, 1, 7) = ?
                    ORDER BY due_date DESC, id DESC
                """, (user["id"], month)).fetchall()
            return self.send_json(HTTPStatus.OK, {"expenses": [dict(row) for row in rows]})
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8")}
        if path not in files:
            return self.send_error(HTTPStatus.NOT_FOUND)
        filename, content_type = files[path]
        body = (ROOT / "static" / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in {"/api/register", "/api/login", "/api/logout", "/api/expenses"}:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
        if not self.mutation_allowed():
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "Origem não permitida."})
        data = self.read_json()
        if data is None:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Envie um JSON válido."})
        if path == "/api/register":
            name = str(data.get("name", "")).strip()
            email = str(data.get("email", "")).strip().lower()
            password = data.get("password", "")
            if not 2 <= len(name) <= 80 or not EMAIL_RE.fullmatch(email) or len(email) > 254 or not isinstance(password, str) or not 8 <= len(password) <= 128:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Confira nome, e-mail e senha (mínimo de 8 caracteres)."})
            try:
                with connect() as db:
                    cursor = db.execute("INSERT INTO users(name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                                        (name, email, password_hash(password), utc_now()))
                    user = {"id": cursor.lastrowid, "name": name, "email": email}
            except sqlite3.IntegrityError:
                return self.send_json(HTTPStatus.CONFLICT, {"error": "Este e-mail já está cadastrado."})
            return self.start_session(user, HTTPStatus.CREATED)
        if path == "/api/login":
            email = str(data.get("email", "")).strip().lower()
            password = data.get("password", "")
            with connect() as db:
                row = db.execute("SELECT id, name, email, password_hash FROM users WHERE email = ?", (email,)).fetchone()
            if not row or not isinstance(password, str) or not verify_password(password, row["password_hash"]):
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "E-mail ou senha incorretos."})
            return self.start_session({key: row[key] for key in ("id", "name", "email")}, HTTPStatus.OK)
        user = self.current_user()
        if not user:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
        if path == "/api/logout":
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["session"].value if "session" in cookie else ""
            with connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
            return self.send_json(HTTPStatus.OK, {"ok": True}, self.cookie_header("", 0))
        description = str(data.get("description", "")).strip()
        kind = data.get("kind")
        account = str(data.get("account", "")).strip()
        amount_cents = data.get("amount_cents")
        due_date = data.get("due_date")
        try:
            valid_date = date.fromisoformat(due_date).isoformat() == due_date
        except (TypeError, ValueError):
            valid_date = False
        if (not 2 <= len(description) <= 120 or kind not in KINDS or not 2 <= len(account) <= 80
                or type(amount_cents) is not int or not 0 < amount_cents <= 1_000_000_000 or not valid_date):
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Confira os dados do lançamento."})
        with connect() as db:
            cursor = db.execute("""
                INSERT INTO expenses(user_id, description, kind, account, amount_cents, due_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user["id"], description, kind, account, amount_cents, due_date, utc_now()))
        return self.send_json(HTTPStatus.CREATED, {"id": cursor.lastrowid})

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if not self.mutation_allowed():
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "Origem não permitida."})
        match = re.fullmatch(r"/api/expenses/(\d+)", path)
        if not match:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
        user = self.current_user()
        if not user:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
        with connect() as db:
            result = db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (int(match.group(1)), user["id"]))
        return self.send_json(HTTPStatus.OK if result.rowcount else HTTPStatus.NOT_FOUND,
                              {"ok": True} if result.rowcount else {"error": "Lançamento não encontrado."})

    def start_session(self, user, status):
        token = secrets.token_hex(32)
        expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
        with connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),))
            db.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                       (token_hash(token), user["id"], expires))
        self.send_json(status, {"user": user}, self.cookie_header(token, SESSION_DAYS * 86400))


def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Acesse http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
