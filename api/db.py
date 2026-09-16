"""Shared Postgres connection pool.

One pool per process, used by every module that talks to the database. This is
deliberate: Cloud SQL (db-custom-1-3840) allows max_connections=100, and Cloud Run
runs many instances at once, so the real ceiling is (instances x pool size). A
second pool in another module would silently double that budget.

Keep the per-instance pool small and let Cloud Run scale out horizontally. A large
pool per instance exhausts Postgres under load and takes the whole service down,
not just the endpoint that opened the connections.
"""

from __future__ import annotations

import os

DB_URL = os.environ.get("DATABASE_URL")

_POOL = None
POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("DB_POOL_MAX", "4"))


def _get_pool():
    global _POOL
    if _POOL is None:
        from psycopg2.pool import ThreadedConnectionPool

        _POOL = ThreadedConnectionPool(POOL_MIN, POOL_MAX, DB_URL)
    return _POOL


class connection:
    """Context manager yielding a pooled connection, returned to the pool on exit.

        with db.connection() as conn:
            cur = conn.cursor()
    """

    def __enter__(self):
        self._pool = _get_pool()
        self._conn = self._pool.getconn()
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                self._conn.rollback()
            else:
                self._conn.commit()
        finally:
            self._pool.putconn(self._conn)
        return False
