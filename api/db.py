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
import threading

import psycopg2

from core import settings

_POOL = None
POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("DB_POOL_MAX", "4"))

# Hard ceiling on every pooled connection, applied at connect time rather than per
# query. Postgres keeps executing a statement even after its client goes away, so a
# server restart during a slow query leaves it running server-side, holding CPU on a
# small instance. Setting this on the connection means no request path can outlive
# it, whatever a caller forgets to set.
STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "20000"))
# Also reap connections whose client has vanished mid-transaction.
IDLE_TX_TIMEOUT_MS = int(os.environ.get("DB_IDLE_TX_TIMEOUT_MS", "30000"))
# How long a request waits for a free connection before giving up.
CHECKOUT_TIMEOUT_S = float(os.environ.get("DB_CHECKOUT_TIMEOUT_S", "15"))

# psycopg2's pool does not wait: when every connection is out, the next request
# fails on the spot with "connection pool exhausted". Turning on a map layer sends
# a burst of tile requests, and a question asked in that moment was simply
# rejected - found by clicking through the app in a browser on 3 Oct. This makes
# a request wait its turn instead, for a bounded time.
_SLOTS = threading.BoundedSemaphore(POOL_MAX)


def _get_pool():
    global _POOL
    if _POOL is None:
        from psycopg2.pool import ThreadedConnectionPool

        opts = (
            f"-c statement_timeout={STATEMENT_TIMEOUT_MS} "
            f"-c idle_in_transaction_session_timeout={IDLE_TX_TIMEOUT_MS}"
        )
        _POOL = ThreadedConnectionPool(POOL_MIN, POOL_MAX, settings.database_url, options=opts)
    return _POOL


def _alive(conn) -> bool:
    """Whether a connection can still answer. Cheap enough to run per checkout."""
    if conn.closed:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


class connection:
    """Context manager yielding a pooled connection, returned to the pool on exit.

    with db.connection() as conn:
        cur = conn.cursor()
    """

    def __enter__(self):
        if not _SLOTS.acquire(timeout=CHECKOUT_TIMEOUT_S):
            raise RuntimeError(
                f"no database connection free after {CHECKOUT_TIMEOUT_S:.0f}s - the service is overloaded"
            )
        try:
            return self._checkout()
        except BaseException:
            _SLOTS.release()
            raise

    def _checkout(self):
        self._pool = _get_pool()
        # A pooled connection can be dead on arrival: the Cloud SQL proxy and the
        # server both drop idle connections, and the pool hands them back anyway.
        # The first query on one raises InterfaceError, which surfaced as a
        # request that returned nothing at all. Check before handing it out, and
        # throw away anything that does not answer.
        for attempt in range(POOL_MAX + 1):
            try:
                conn = self._pool.getconn()
            except psycopg2.OperationalError:
                # Opening a new connection can fail on a dropped network
                # moment; one more try, then the error stands.
                if attempt:
                    raise
                continue
            if _alive(conn):
                self._conn = conn
                return conn
            self._pool.putconn(conn, close=True)
        raise RuntimeError("no usable database connection in the pool")

    def __exit__(self, exc_type, exc, tb):
        broken = False
        try:
            if exc_type is not None:
                self._conn.rollback()
            else:
                self._conn.commit()
        except Exception:
            # The connection died mid-request. Closing it on return stops the pool
            # from handing the same dead one to the next caller.
            broken = True
        finally:
            self._pool.putconn(self._conn, close=broken)
            _SLOTS.release()
        return False
