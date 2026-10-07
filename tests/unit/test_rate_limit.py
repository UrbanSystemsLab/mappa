"""The rate limit on /ask.

The app is public with no sign-in. These assert the two things that make the
limit worth having: that a loop is stopped, and that a person is not - a
classroom behind one address still has to be able to ask.
"""

from __future__ import annotations

import pytest
from starlette.datastructures import Headers

from api import limits


@pytest.fixture(autouse=True)
def clean():
    limits.reset()
    yield
    limits.reset()


class Fake:
    """Just enough of a Request for the client-identity rules."""

    def __init__(self, forwarded: str | None = None, host: str | None = "10.0.0.1"):
        headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.headers = Headers(headers)
        self.client = type("C", (), {"host": host})() if host else None


def test_a_person_asking_questions_is_not_stopped():
    """One question every twenty seconds for an hour - a long research session."""
    for i in range(100):
        ok, _ = limits.allow("reader", now=i * 20.0)
        assert ok, f"a reader was blocked on question {i + 1}"


def test_a_loop_is_stopped_within_the_minute():
    allowed = sum(limits.allow("loop", now=1000.0 + i * 0.01)[0] for i in range(200))
    assert allowed == limits.PER_MINUTE


def test_the_wait_is_a_real_number():
    for i in range(limits.PER_MINUTE):
        limits.allow("loop", now=1000.0 + i)
    ok, retry = limits.allow("loop", now=1000.0 + limits.PER_MINUTE)
    assert not ok
    assert 0 < retry <= 61


def test_the_burst_clears_after_a_minute():
    for i in range(limits.PER_MINUTE):
        limits.allow("loop", now=1000.0 + i * 0.1)
    assert not limits.allow("loop", now=1001.0)[0]
    assert limits.allow("loop", now=1070.0)[0], "a minute later it should be allowed again"


def test_the_hourly_limit_holds_when_the_pace_is_slow_enough_to_pass_the_minute():
    """A script asking once every five seconds never trips the per-minute limit,
    which is the whole reason there is a second window."""
    allowed = sum(limits.allow("slow", now=i * 5.0)[0] for i in range(400))
    assert allowed == limits.PER_HOUR


def test_one_client_does_not_spend_anothers_allowance():
    for i in range(limits.PER_MINUTE):
        limits.allow("loop", now=1000.0 + i * 0.1)
    assert not limits.allow("loop", now=1001.0)[0]
    assert limits.allow("someone-else", now=1001.0)[0]


class TestWhoIsCounted:
    def test_the_caller_is_the_first_entry_not_the_last(self):
        # The last entry is Google's proxy. Counting that would put every request
        # in the world into one bucket and shut the service off.
        assert limits._client(Fake("203.0.113.9, 35.191.8.2, 130.211.0.1")) == "203.0.113.9"

    def test_falls_back_to_the_socket(self):
        assert limits._client(Fake(None, "198.51.100.7")) == "198.51.100.7"

    def test_an_unknown_caller_is_still_counted(self):
        assert limits._client(Fake(None, None)) == "unknown"


def test_only_the_expensive_routes_are_limited():
    """Tiles and the catalogue are cached and cheap. Limiting them would break
    the map for a classroom on one connection."""
    assert "/api/v1/ask".startswith(limits.LIMITED_PATHS)
    assert "/api/v1/ask/stream".startswith(limits.LIMITED_PATHS)
    assert not "/tiles/layer/8/70/110.mvt".startswith(limits.LIMITED_PATHS)
    assert not "/catalog/layers".startswith(limits.LIMITED_PATHS)
    assert not "/health".startswith(limits.LIMITED_PATHS)


def test_idle_clients_are_forgotten():
    """The dict must not grow for the life of the container."""
    for i in range(50):
        limits.allow(f"visitor-{i}", now=100.0 + i)
    limits.allow("current", now=100_000.0)
    limits._evict(100_000.0)
    assert list(limits._hits) == ["current"]
