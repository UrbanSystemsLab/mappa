"""Shared fixtures.

Integration tests run against the real database. They only read, except where a
test says otherwise, so they are safe against a working instance - but they need
DATABASE_URL, and skip rather than fail when it is absent so the unit tests still
run anywhere.
"""

import os

import pytest


@pytest.fixture(scope="session")
def db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    import psycopg2

    conn = psycopg2.connect(url, connect_timeout=30)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def cur(db):
    c = db.cursor()
    c.execute("SET statement_timeout='120s'")
    yield c
    c.close()
