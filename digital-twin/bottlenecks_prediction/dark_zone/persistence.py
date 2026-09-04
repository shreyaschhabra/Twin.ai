"""
Dark Zone Tracking Engine — Persistence & Crash Recovery
=============================================================
Durable, crash-safe storage for in-flight vehicle tracker state.

Design principles:
  1. Persist the FULL particle cloud, not a mean/std summary — otherwise a
     restart silently erases multimodal hypotheses (rework in progress).
  2. Write-ahead discipline: state is persisted to SQLite (atomic, durable)
     BEFORE any upstream event-bus offset/ack is committed. If the process
     dies between "state written" and "offset committed," the event bus
     replays that event on restart; route_event() is naturally idempotent
     enough for TICK/checkpoint events (re-applying a predict+update from
     a slightly-stale dt is harmless — it's not exactly-once, it's
     at-least-once with negligible double-counting error).
  3. SQLite, not flat pickle files: a crash mid-write to a pickle file can
     leave a truncated, corrupt file with no way to detect it. SQLite gives
     us transactional commits — a crash mid-write just loses the
     in-progress transaction, never corrupts the last good row.
"""

from __future__ import annotations

import sqlite3
import json
import time
from contextlib import contextmanager
from typing import Optional

from dark_zone_tracker import DarkZoneParticleFilter, DwellDistribution


SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle_state (
    vehicle_id      TEXT PRIMARY KEY,
    station_id      TEXT NOT NULL,
    variant         TEXT,
    entry_ts        REAL NOT NULL,
    last_event_ts   REAL NOT NULL,
    pf_state_json   TEXT NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id      TEXT,
    reason          TEXT,
    event_json      TEXT,
    logged_at       REAL NOT NULL
);
"""


class SQLitePersistence:
    """
    Thin, dependency-free (stdlib sqlite3) persistence backend.
    One row per in-flight vehicle; row is overwritten (UPSERT) on every
    state change, so the table always reflects "current in-flight state,"
    not a history log. That keeps recovery O(vehicles in flight), not
    O(all events ever).
    """

    def __init__(self, db_path: str = "dark_zone_state.db"):
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # WAL mode: readers don't block writers and vice versa, and commits
            # are append-only rather than rewriting the whole DB file — this is
            # the single biggest throughput lever for write-heavy workloads.
            conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL is safe under WAL (still durable across app crashes; the
            # only risk window is an OS-level power-loss mid-checkpoint, which
            # FULL guards against at a real throughput cost we don't need here).
            conn.execute("PRAGMA synchronous=NORMAL")

    @contextmanager
    def _conn(self):
        # isolation_level=None -> autocommit off, we control transactions
        # explicitly with BEGIN/COMMIT so a crash mid-write can't leave a
        # half-applied row.
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        try:
            yield conn
        finally:
            conn.close()

    def save_vehicle_state(
        self,
        vehicle_id: str,
        station_id: str,
        variant: Optional[str],
        entry_ts: float,
        last_event_ts: float,
        pf: DarkZoneParticleFilter,
    ) -> None:
        pf_state_json = json.dumps(pf.to_state())
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO vehicle_state
                        (vehicle_id, station_id, variant, entry_ts, last_event_ts,
                         pf_state_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vehicle_id) DO UPDATE SET
                        station_id=excluded.station_id,
                        variant=excluded.variant,
                        last_event_ts=excluded.last_event_ts,
                        pf_state_json=excluded.pf_state_json,
                        updated_at=excluded.updated_at
                    """,
                    (vehicle_id, station_id, variant, entry_ts, last_event_ts,
                     pf_state_json, time.time()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def delete_vehicle_state(self, vehicle_id: str) -> None:
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM vehicle_state WHERE vehicle_id = ?", (vehicle_id,))
            conn.execute("COMMIT")

    def save_vehicle_states_batch(
        self,
        states: list[tuple[str, str, Optional[str], float, float, DarkZoneParticleFilter]],
    ) -> None:
        """
        Write multiple vehicles' state in ONE transaction instead of one
        transaction per vehicle. This is the throughput fix: SQLite's cost
        per transaction (fsync/WAL-flush) dominates at high event rates far
        more than the cost per row, so batching N vehicles into 1 commit
        instead of N commits is close to an N-times reduction in write
        overhead, not just a marginal gain.

        Each tuple: (vehicle_id, station_id, variant, entry_ts, last_event_ts, pf)
        """
        if not states:
            return
        now = time.time()
        rows = [
            (vid, station_id, variant, entry_ts, last_event_ts,
             json.dumps(pf.to_state()), now)
            for vid, station_id, variant, entry_ts, last_event_ts, pf in states
        ]
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.executemany(
                    """
                    INSERT INTO vehicle_state
                        (vehicle_id, station_id, variant, entry_ts, last_event_ts,
                         pf_state_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vehicle_id) DO UPDATE SET
                        station_id=excluded.station_id,
                        variant=excluded.variant,
                        last_event_ts=excluded.last_event_ts,
                        pf_state_json=excluded.pf_state_json,
                        updated_at=excluded.updated_at
                    """,
                    rows,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def load_all_vehicle_states(self) -> list[dict]:
        """Returns raw rows; caller (orchestrator) reconstructs PF objects,
        since that requires the dwell_models lookup table which persistence
        itself has no business knowing about."""
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT vehicle_id, station_id, variant, entry_ts, last_event_ts, "
                "pf_state_json FROM vehicle_state"
            )
            rows = cur.fetchall()
        return [
            {
                "vehicle_id": r[0], "station_id": r[1], "variant": r[2],
                "entry_ts": r[3], "last_event_ts": r[4],
                "pf_state": json.loads(r[5]),
            }
            for r in rows
        ]

    def log_rejected_event(self, vehicle_id: str, reason: str, event: dict) -> None:
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO rejected_events (vehicle_id, reason, event_json, logged_at) "
                "VALUES (?, ?, ?, ?)",
                (vehicle_id, reason, json.dumps(event), time.time()),
            )
            conn.execute("COMMIT")
