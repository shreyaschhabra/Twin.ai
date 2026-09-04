"""SQLite schema for the dashboard's own persistence.

Boundary note: this database belongs to the dashboard alone. Nothing in the simulator,
the bottleneck model, the defect model, or the coordinated runtime reads it, and
deleting the file only costs the dashboard its cached run history -- which
:mod:`dashboard.ingestion.run_ingestor` can rebuild from completed run artifacts.

Only the base run-history concept is defined here. Later work extends the schema by
appending a new version to :data:`dashboard.storage.migrations.MIGRATIONS` rather than
editing these statements in place.
"""

from __future__ import annotations

#: Current schema version. Bump only alongside a new MIGRATIONS entry.
SCHEMA_VERSION = 1

CREATE_SCHEMA_VERSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""

# One row per completed production run. `run_id` is the dashboard's internal identity;
# `artifact_path` points at the completed simulator run directory, and
# `predictions_path` at the coordinated runtime output directory holding
# bottleneck_predictions.jsonl / defect_predictions.jsonl / system_health.json /
# system_run_manifest.json. The dashboard stores references, never copies of those
# streams -- the artifacts on disk stay authoritative.
CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id               TEXT    PRIMARY KEY,
    production_day       INTEGER NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'PENDING',
    scenario_name        TEXT,
    scenario_reference   TEXT,
    scenario_description TEXT,
    multiplier           REAL    NOT NULL DEFAULT 60.0,
    seed                 INTEGER,
    duration_ms          INTEGER,
    factory_path         TEXT    NOT NULL,
    factory_fingerprint  TEXT,
    artifact_path        TEXT,
    predictions_path     TEXT,
    started_at           TEXT,
    completed_at         TEXT,
    is_demo              INTEGER NOT NULL DEFAULT 0,
    metadata_json        TEXT,
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL
)
"""

CREATE_RUNS_PRODUCTION_DAY_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_production_day
    ON runs (production_day)
"""

CREATE_RUNS_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status)
"""

INITIAL_SCHEMA: tuple[str, ...] = (
    CREATE_SCHEMA_VERSIONS_TABLE,
    CREATE_RUNS_TABLE,
    CREATE_RUNS_PRODUCTION_DAY_INDEX,
    CREATE_RUNS_STATUS_INDEX,
)

#: Tables the dashboard owns. Used by reset/rebuild.
OWNED_TABLES: tuple[str, ...] = ("runs", "schema_versions")
