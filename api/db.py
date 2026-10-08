"""The database connection pool, shared by everything in the process.

A small pool per container, waited on rather than failed when busy. Every
connection is opened with a statement timeout, so no query can run on after its
request is gone.

    with db.connection() as conn:
        cur = conn.cursor()
        ...
"""

from __future__ import annotations

import threading

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from core import settings

from .cache import cached

# How many requests may hold a connection at once. psycopg2's pool fails at once
# when empty; this makes a request wait its turn, for a bounded time.
_slots = threading.BoundedSemaphore(settings.db_pool_max)


@cached()
def _pool() -> ThreadedConnectionPool:
    options = (
        f"-c statement_timeout={settings.db_statement_timeout_ms} "
        f"-c idle_in_transaction_session_timeout={settings.db_statement_timeout_ms + 10_000}"
    )
    return ThreadedConnectionPool(1, settings.db_pool_max, settings.database_url, options=options)


def _alive(conn) -> bool:
    """Whether a pooled connection still answers. The proxy and the server both
    drop idle connections, and the pool would hand them out anyway."""
    if conn.closed:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


class connection:
    """A pooled connection for the length of a `with` block: committed on success,
    rolled back on error, and always returned."""

    def __enter__(self):
        if not _slots.acquire(timeout=settings.db_checkout_timeout_s):
            raise RuntimeError(
                f"no database connection free after {settings.db_checkout_timeout_s:.0f}s"
            )
        try:
            self._conn = self._checkout()
            return self._conn
        except BaseException:
            _slots.release()
            raise

    def _checkout(self):
        pool = _pool()
        for attempt in range(settings.db_pool_max + 1):
            try:
                conn = pool.getconn()
            except psycopg2.OperationalError:
                if attempt:  # one retry for a dropped network moment
                    raise
                continue
            if _alive(conn):
                return conn
            pool.putconn(conn, close=True)
        raise RuntimeError("no usable database connection in the pool")

    def __exit__(self, exc_type, exc, tb):
        broken = False
        try:
            if exc_type is not None:
                self._conn.rollback()
            else:
                self._conn.commit()
        except Exception:
            broken = True  # closed on return, so it is never handed out again
        finally:
            _pool().putconn(self._conn, close=broken)
            _slots.release()
        return False
