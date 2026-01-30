"""Hard limits guarding costs/time for report jobs."""

from __future__ import annotations

from typing import Iterable

MAX_COMPETITORS = 10
MAX_REVIEWS_PER_RESTAURANT = 100
MAX_SEARCHES_PER_JOB = 12
MAX_RUNTIME_SECONDS = 1800


class LimitExceededError(RuntimeError):
    """Raised when a cost/time limit is breached."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def enforce_competitors(count: int) -> None:
    if count > MAX_COMPETITORS:
        raise LimitExceededError(
            "COST_CAP",
            f"{count} competitors exceeds the allowed {MAX_COMPETITORS}.",
        )


def enforce_reviews_per_batch(limit: int) -> int:
    return min(limit, MAX_REVIEWS_PER_RESTAURANT)
