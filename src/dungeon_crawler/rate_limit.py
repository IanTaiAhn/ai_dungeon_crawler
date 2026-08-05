"""Per-client daily cap on starting new games.

Starting a game is the expensive operation to spam on a public deployment -
every turn within it drives a real narrator + embedder call (see
serving-compute.md's "no auth or rate limiting" gap). Each run is already
bounded in turns (GameState.max_turns), so capping runs/day bounds worst-case
daily cost per client.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone


class DailyRunLimitExceeded(Exception):
    def __init__(self, client_key: str, limit: int) -> None:
        self.client_key = client_key
        self.limit = limit
        super().__init__(f"{client_key!r} already started {limit} game(s) today")


class DailyRunLimiter:
    """Caps how many games a single client can start per UTC day.

    Backed by the same SQLite connection as the checkpointer, so the count
    persists exactly as long as the save-game DB does - ephemeral on a free
    Render instance that resets on spin-down, durable once a disk is mounted.
    """

    def __init__(self, conn: sqlite3.Connection, limit: int = 2) -> None:
        self._conn = conn
        self._limit = limit
        self._lock = threading.Lock()
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_run_counts ("
                "client_key TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL, "
                "PRIMARY KEY (client_key, day))"
            )

    def check_and_increment(self, client_key: str) -> None:
        """Raise DailyRunLimitExceeded if `client_key` is already at the
        limit for today (UTC), otherwise record one more run for them.
        """
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT count FROM daily_run_counts WHERE client_key = ? AND day = ?",
                (client_key, day),
            ).fetchone()
            if row is not None and row[0] >= self._limit:
                raise DailyRunLimitExceeded(client_key, self._limit)
            self._conn.execute(
                "INSERT INTO daily_run_counts (client_key, day, count) VALUES (?, ?, 1) "
                "ON CONFLICT(client_key, day) DO UPDATE SET count = count + 1",
                (client_key, day),
            )
