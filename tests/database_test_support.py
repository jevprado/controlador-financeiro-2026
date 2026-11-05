"""Isola testes do banco configurado para uso normal da aplicação."""

import os
import uuid
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


@contextmanager
def isolated_database():
    test_url = os.environ.get("TEST_DATABASE_URL")
    with patch.dict(os.environ):
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("VERCEL", None)
        if not test_url:
            yield
            return
        import psycopg
        from psycopg import sql

        schema = "odarp_test_" + uuid.uuid4().hex
        parts = urlsplit(test_url)
        query = dict(parse_qsl(parts.query))
        query["options"] = f"-c search_path={schema}"
        with psycopg.connect(test_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            try:
                os.environ["DATABASE_URL"] = urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))
                yield
            finally:
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
