"""API do controlador financeiro com SQLite local ou PostgreSQL externo."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import database
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("FINANCE_DB", ROOT / "data" / "finance.db"))
SESSION_DAYS = 30
MAX_BODY = 16_384
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
KINDS = {"Cartão de crédito", "Cheque especial", "Empréstimo", "Outros"}


def connect():
    return database.connect(DB_PATH)


def init_db():
    database.init_db(DB_PATH)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def current_month():
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m")


def valid_month(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value)) and value[:4] != "0000"


def generate_recurring(user_id, requested_month=None):
    """Materialize each monthly occurrence once, including months missed between visits."""
    with connect() as db:
        db.lock_expense_order(user_id)
        materialize_recurring(db, user_id, requested_month)


def materialize_recurring(db, user_id, requested_month=None):
    through = current_month()
    rules = db.execute("SELECT * FROM recurring_expenses WHERE user_id = ? AND is_active = 1", (user_id,)).fetchall()
    for rule in rules:
        first = date.fromisoformat(rule["first_due_date"])
        existing = {row["month"] for row in db.execute(
            "SELECT month FROM recurring_occurrences WHERE recurring_id = ?", (rule["id"],))}
        first_index = first.year * 12 + first.month - 1
        last_index = int(through[:4]) * 12 + int(through[5:]) - 1
        periods = {f"{index // 12:04d}-{index % 12 + 1:02d}" for index in range(first_index, last_index + 1)}
        if requested_month and requested_month >= rule["first_due_date"][:7]:
            periods.add(requested_month)
        for period in sorted(periods - existing):
            year, month = map(int, period.split("-"))
            due = date(year, month, min(first.day, monthrange(year, month)[1])).isoformat()
            db.execute("""
                INSERT INTO expenses(user_id, description, kind, account, amount_cents, due_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, rule["description"], rule["kind"], rule["account"], rule["amount_cents"], due, utc_now()))
            db.execute("INSERT INTO recurring_occurrences(recurring_id, month) VALUES (?, ?)", (rule["id"], period))


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


def allowed_emails():
    """Missing or malformed configuration never enables public access."""
    emails = {email.strip().lower() for email in os.environ.get("ALLOWED_EMAILS", "").split(",")}
    if any(not EMAIL_RE.fullmatch(email) or len(email) > 254 for email in emails):
        return frozenset()
    return frozenset(emails)


def registration_allowed(email, invite_code):
    expected = os.environ.get("REGISTRATION_INVITE_CODE", "")
    return (
        email in allowed_emails()
        and 32 <= len(expected) <= 256
        and isinstance(invite_code, str)
        and hmac.compare_digest(invite_code.encode(), expected.encode())
    )


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
            if row and row["email"].strip().lower() not in allowed_emails():
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
                return None
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
                    SELECT MIN(account) AS account FROM expenses WHERE user_id = ?
                    GROUP BY lower(account)
                    ORDER BY lower(MIN(account))
                """, (user["id"],)).fetchall()
            return self.send_json(HTTPStatus.OK, {"accounts": [row["account"] for row in rows]})
        if path == "/api/recurring-expenses":
            user = self.current_user()
            if not user:
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
            generate_recurring(user["id"])
            with connect() as db:
                rows = db.execute("SELECT * FROM recurring_expenses WHERE user_id = ? AND is_active = 1 ORDER BY id DESC", (user["id"],)).fetchall()
            return self.send_json(HTTPStatus.OK, {"recurring_expenses": [dict(row) for row in rows]})
        if path == "/api/expenses/monthly-totals":
            user = self.current_user()
            if not user:
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
            generate_recurring(user["id"])
            with connect() as db:
                rows = db.execute("""
                    SELECT account, substr(due_date, 1, 7) AS month, SUM(amount_cents) AS total_cents,
                        COUNT(*) AS expense_count
                    FROM expenses WHERE user_id = ?
                    GROUP BY account, substr(due_date, 1, 7) ORDER BY month, account
                """, (user["id"],)).fetchall()
            months = {}
            accounts = {}
            for row in rows:
                name = " ".join(row["account"].split())
                key = name.casefold()
                account = accounts.setdefault(key, {"account": name, "months": {}})
                for totals in (months, account["months"]):
                    item = totals.setdefault(row["month"], {"month": row["month"], "total_cents": 0, "expense_count": 0})
                    item["total_cents"] += row["total_cents"]
                    item["expense_count"] += row["expense_count"]
            return self.send_json(HTTPStatus.OK, {
                "months": list(months.values()),
                "accounts": [{"account": item["account"], "months": list(item["months"].values())}
                             for _, item in sorted(accounts.items())],
            })
        if path == "/api/expenses":
            user = self.current_user()
            if not user:
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
            month = dict(parse_qsl(urlsplit(self.path).query)).get("month", "")
            if not valid_month(month):
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Mês inválido."})
            generate_recurring(user["id"], month)
            with connect() as db:
                rows = db.execute("""
                    SELECT id, description, kind, account, amount_cents, due_date, is_paid
                    FROM expenses WHERE user_id = ? AND substr(due_date, 1, 7) = ?
                    ORDER BY sort_order IS NULL, sort_order, due_date DESC, id DESC
                """, (user["id"], month)).fetchall()
            return self.send_json(HTTPStatus.OK, {"expenses": [{**dict(row), "is_paid": bool(row["is_paid"])} for row in rows]})
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                 "/api.js": ("api.js", "text/javascript; charset=utf-8"),
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
        if path not in {"/api/register", "/api/login", "/api/logout", "/api/expenses", "/api/recurring-expenses"}:
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
            if not registration_allowed(email, data.get("invite_code")):
                return self.send_json(HTTPStatus.FORBIDDEN, {"error": "Cadastro restrito. Confira seu e-mail e código de convite com o responsável."})
            with connect() as db:
                cursor = db.execute("INSERT INTO users(name, email, password_hash, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(email) DO NOTHING RETURNING id",
                                    (name, email, password_hash(password), utc_now()))
                row = cursor.fetchone()
                if row is None:
                    return self.send_json(HTTPStatus.CONFLICT, {"error": "Este e-mail já está cadastrado."})
                user = {"id": row["id"], "name": name, "email": email}
            return self.start_session(user, HTTPStatus.CREATED)
        if path == "/api/login":
            email = str(data.get("email", "")).strip().lower()
            password = data.get("password", "")
            if email not in allowed_emails():
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "E-mail ou senha incorretos."})
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
        return self.save_expense(data, user, recurring=path == "/api/recurring-expenses")

    def do_PUT(self):
        if not self.mutation_allowed():
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "Origem não permitida."})
        if urlsplit(self.path).path == "/api/expenses/order":
            return self.save_expense_order()
        payment_match = re.fullmatch(r"/api/expenses/(\d+)/payment", urlsplit(self.path).path)
        if payment_match:
            return self.save_expense_payment(int(payment_match.group(1)))
        match = re.fullmatch(r"/api/expenses/(\d+)", urlsplit(self.path).path)
        if not match:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
        user = self.current_user()
        if not user:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
        data = self.read_json()
        if data is None:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Envie um JSON válido."})
        return self.save_expense(data, user, int(match.group(1)))

    def save_expense_payment(self, expense_id):
        user = self.current_user()
        if not user:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
        data = self.read_json()
        if data is None or type(data.get("is_paid")) is not bool:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Informe um estado de pagamento válido."})
        with connect() as db:
            result = db.execute("UPDATE expenses SET is_paid = ? WHERE id = ? AND user_id = ?",
                                (int(data["is_paid"]), expense_id, user["id"]))
        return self.send_json(HTTPStatus.OK if result.rowcount else HTTPStatus.NOT_FOUND,
                              {"is_paid": data["is_paid"]} if result.rowcount else {"error": "Lançamento não encontrado."})

    def save_expense_order(self):
        user = self.current_user()
        if not user:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
        data = self.read_json()
        if data is None:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Envie um JSON válido."})
        month, ids = data.get("month"), data.get("ids")
        if (not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month)
                or not isinstance(ids, list) or any(type(item) is not int for item in ids)
                or len(ids) != len(set(ids))):
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Ordem de lançamentos inválida."})
        with connect() as db:
            db.lock_expense_order(user["id"])
            existing = {row["id"] for row in db.execute(
                "SELECT id FROM expenses WHERE user_id = ? AND substr(due_date, 1, 7) = ?",
                (user["id"], month))}
            if existing != set(ids):
                return self.send_json(HTTPStatus.CONFLICT, {"error": "A lista mudou. Atualize os lançamentos e tente novamente."})
            db.executemany("UPDATE expenses SET sort_order = ? WHERE id = ? AND user_id = ?",
                           [(position, expense_id, user["id"]) for position, expense_id in enumerate(ids)])
        return self.send_json(HTTPStatus.OK, {"ok": True})

    def save_expense(self, data, user, expense_id=None, recurring=False):
        description = str(data.get("description", "")).strip()
        kind = data.get("kind")
        account = str(data.get("account", "")).strip()
        amount_cents = data.get("amount_cents")
        due_date = data.get("due_date")
        try:
            valid_date = date.fromisoformat(due_date).isoformat() == due_date
        except (TypeError, ValueError):
            valid_date = False
        if (not 2 <= len(description) <= 120 or not isinstance(kind, str) or kind not in KINDS or not 2 <= len(account) <= 80
                or type(amount_cents) is not int or not 0 < amount_cents <= 1_000_000_000 or not valid_date):
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Confira os dados do lançamento."})
        if recurring:
            with connect() as db:
                db.lock_expense_order(user["id"])
                created_id = db.execute("""
                    INSERT INTO recurring_expenses(user_id, description, kind, account, amount_cents, first_due_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
                """, (user["id"], description, kind, account, amount_cents, due_date, utc_now())).fetchone()["id"]
                materialize_recurring(db, user["id"], due_date[:7])
            return self.send_json(HTTPStatus.CREATED, {"id": created_id})
        with connect() as db:
            if expense_id is not None:
                result = db.execute("""
                    UPDATE expenses SET description = ?, kind = ?, account = ?, amount_cents = ?,
                        sort_order = CASE WHEN substr(due_date, 1, 7) = substr(?, 1, 7) THEN sort_order ELSE NULL END,
                        due_date = ?
                    WHERE id = ? AND user_id = ?
                """, (description, kind, account, amount_cents, due_date, due_date, expense_id, user["id"]))
            else:
                cursor = db.execute("""
                    INSERT INTO expenses(user_id, description, kind, account, amount_cents, due_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
                """, (user["id"], description, kind, account, amount_cents, due_date, utc_now()))
                created_id = cursor.fetchone()["id"]
        if expense_id is not None:
            return self.send_json(HTTPStatus.OK if result.rowcount else HTTPStatus.NOT_FOUND,
                                  {"id": expense_id} if result.rowcount else {"error": "Lançamento não encontrado."})
        return self.send_json(HTTPStatus.CREATED, {"id": created_id})

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if not self.mutation_allowed():
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "Origem não permitida."})
        match = re.fullmatch(r"/api/(expenses|recurring-expenses)/(\d+)", path)
        if not match:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
        user = self.current_user()
        if not user:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Faça login para continuar."})
        with connect() as db:
            if match.group(1) == "recurring-expenses":
                db.lock_expense_order(user["id"])
                result = db.execute("UPDATE recurring_expenses SET is_active = 0 WHERE id = ? AND user_id = ? AND is_active = 1", (int(match.group(2)), user["id"]))
            else:
                result = db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (int(match.group(2)), user["id"]))
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
