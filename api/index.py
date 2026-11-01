"""Ponto de entrada HTTP da Vercel, reutilizando a API local."""

import logging
import secrets
from http import HTTPStatus
from threading import Lock
from urllib.parse import urlsplit

from server import Handler, init_db


logger = logging.getLogger(__name__)
_database_ready = False
_database_lock = Lock()


def ensure_database():
    """Initialize once per warm instance; failed initialization can be retried."""
    global _database_ready
    if _database_ready:
        return
    with _database_lock:
        if not _database_ready:
            init_db()
            _database_ready = True


class handler(Handler):
    def dispatch(self, method):
        phase = "database_initialization"
        try:
            if urlsplit(self.path).path.startswith("/api/"):
                ensure_database()
            phase = "request"
            return method()
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as error:
            reference = secrets.token_hex(8)
            # Do not log exception messages: connection errors can contain credentials.
            logger.error(
                "request_failed reference=%s phase=%s error_type=%s sqlstate=%s",
                reference, phase, type(error).__name__, getattr(error, "sqlstate", None),
            )
            return self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "Serviço temporariamente indisponível. Tente novamente em instantes.",
                "reference": reference,
            })

    def do_GET(self):
        return self.dispatch(super().do_GET)

    def do_POST(self):
        return self.dispatch(super().do_POST)

    def do_PUT(self):
        return self.dispatch(super().do_PUT)

    def do_DELETE(self):
        return self.dispatch(super().do_DELETE)
