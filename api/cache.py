"""Caching for things that are expensive to load and rarely change.

One mechanism for the whole app, instead of a module-level variable and a
`global` statement in each module that needed one.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def cached(seconds: float | None = None) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Remember what a no-argument loader returns.

    With `seconds`, the value is reloaded once it is older than that; without,
    it is loaded once per process. `loader.clear()` forgets it.
    """

    def wrap(load: Callable[[], T]) -> Callable[[], T]:
        lock = threading.Lock()
        state: dict[str, object] = {}

        @functools.wraps(load)
        def get() -> T:
            with lock:
                fresh = "value" in state and (
                    seconds is None or time.monotonic() - state["at"] < seconds  # type: ignore[operator]
                )
                if not fresh:
                    state["value"] = load()
                    state["at"] = time.monotonic()
                return state["value"]  # type: ignore[return-value]

        get.clear = state.clear  # type: ignore[attr-defined]
        return get

    return wrap
