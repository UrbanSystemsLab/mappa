"""A rate limit on the question routes.

The app is public with no sign-in, so this is what stands between a script and
both the model bill and the database the map is served from. Two windows, because
two things are protected: the cost adds up over an hour, the database cares about
the next few seconds. A request has to clear both.

The count is per container. Cloud Run runs several, so the real allowance is this
times however many are up: it stops a loop from one machine, not a distributed
flood. Doing better needs a shared counter - a database round trip per question.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse

from core import settings

# Generous for a person, immediately in the way of a script.
PER_MINUTE = settings.rate_limit_per_minute
PER_HOUR = settings.rate_limit_per_hour

# Only the routes that cost money. Tiles and the catalogue are cached and cheap,
# and limiting them would break the map for a classroom on one connection.
LIMITED_PATHS = (f"{settings.api_prefix}/ask",)

# A bound on what this can hold, so the limiter cannot itself become the leak.
MAX_CLIENTS = 20_000

_hits: dict[str, deque[float]] = {}


def _client(request: Request) -> str:
    """Who to count against.

    Cloud Run puts the caller at the front of X-Forwarded-For and appends its own
    proxies, so the first entry is the one to use. Reading the last would count
    every request in the world against a single Google address.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _evict(now: float) -> None:
    """Drop clients that have not been seen in an hour.

    Without this the dict grows for the life of the container, which on a service
    that stays up for days is a slow leak with no upper bound.
    """
    stale = [key for key, seen in _hits.items() if not seen or now - seen[-1] > 3600]
    for key in stale:
        del _hits[key]
    if len(_hits) > MAX_CLIENTS:  # pathological; keep the most recent
        for key in sorted(_hits, key=lambda k: _hits[k][-1])[: len(_hits) - MAX_CLIENTS]:
            del _hits[key]


def _retry_after(seen: deque[float], now: float) -> int:
    """How long until the oldest hit in the window falls out of it.

    An honest number, so a well-behaved caller can wait exactly that long rather
    than guessing or hammering.
    """
    waits = []
    if len(seen) >= PER_MINUTE:
        waits.append(60 - (now - seen[-PER_MINUTE]))
    if len(seen) >= PER_HOUR:
        waits.append(3600 - (now - seen[-PER_HOUR]))
    return max(1, int(max(waits, default=1)) + 1)


def allow(key: str, now: float | None = None) -> tuple[bool, int]:
    """Whether this client may ask now, and how long to wait if not."""
    now = time.monotonic() if now is None else now
    seen = _hits.setdefault(key, deque(maxlen=PER_HOUR))
    while seen and now - seen[0] > 3600:
        seen.popleft()

    recent = sum(1 for t in seen if now - t <= 60)
    if recent >= PER_MINUTE or len(seen) >= PER_HOUR:
        return False, _retry_after(seen, now)

    seen.append(now)
    return True, 0


def reset() -> None:
    """Forget every client - for tests."""
    _hits.clear()


async def middleware(request: Request, call_next):
    if not request.url.path.startswith(LIMITED_PATHS):
        return await call_next(request)

    now = time.monotonic()
    if len(_hits) > 1000:
        _evict(now)

    ok, retry_after = allow(_client(request), now)
    if ok:
        return await call_next(request)

    # A message a person might actually read, in both languages, because the
    # person who hits this is usually a classroom on one connection rather than
    # an attacker.
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        content={
            "detail": (
                f"Too many questions at once. Please wait {retry_after} seconds. / "
                f"Demasiadas preguntas a la vez. Espere {retry_after} segundos."
            ),
            "retry_after": retry_after,
        },
    )
