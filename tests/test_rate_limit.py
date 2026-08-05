import sqlite3
from datetime import datetime, timezone

import pytest

from dungeon_crawler.rate_limit import DailyRunLimitExceeded, DailyRunLimiter


def _limiter(limit: int = 2) -> DailyRunLimiter:
    return DailyRunLimiter(sqlite3.connect(":memory:", check_same_thread=False), limit=limit)


def test_allows_up_to_the_limit_then_blocks():
    limiter = _limiter(limit=2)
    limiter.check_and_increment("client-a")
    limiter.check_and_increment("client-a")
    with pytest.raises(DailyRunLimitExceeded):
        limiter.check_and_increment("client-a")


def test_clients_have_independent_quotas():
    limiter = _limiter(limit=1)
    limiter.check_and_increment("client-a")
    limiter.check_and_increment("client-b")  # does not raise - separate quota


def test_quota_resets_on_a_new_day(monkeypatch):
    limiter = _limiter(limit=1)
    limiter.check_and_increment("client-a")

    class _FixedTomorrow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2099, 1, 2, tzinfo=timezone.utc)

    monkeypatch.setattr("dungeon_crawler.rate_limit.datetime", _FixedTomorrow)
    limiter.check_and_increment("client-a")  # does not raise - new UTC day, fresh quota
