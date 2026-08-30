"""
Quality vehicle-history snapshots (Section 15). Five meaningful production
checkpoints chosen sensibly from the locked 45-station route -- never a
row after every single event:

    stage 1: S12  Body-Out Dimensional Check      (zone-1 body_joining exit gate)
    stage 2: S20  Paint Cure + Paint Inspection    (zone-2 paint_surface exit gate)
    stage 3: S27  Powertrain/Battery Mounting      (just after the S26 marriage step)
    stage 4: S38  Final Trim / Manual Inspection   (zone-3 final_assembly exit gate)
    stage 5: S44  Final Quality Inspection         (last station before S45 -- pre-EOL)

All five stations are on every variant's route (the one route skip in this
factory, S35, is not one of them), so every vehicle gets exactly 5
snapshots. No post-QC (S45) snapshot is ever created.
"""

from __future__ import annotations

from typing import List

import pandas as pd

CHECKPOINT_STATIONS: List[str] = ["S12", "S20", "S27", "S38", "S44"]
QC_STATION_ID = "S45"


def build_vehicle_snapshots(events_df: pd.DataFrame) -> pd.DataFrame:
    """One row per (vehicle, checkpoint) with the snapshot time = the
    moment that checkpoint station's processing completed for that
    vehicle. Returns: vehicle_id, shift_id, vehicle_variant,
    checkpoint_station_id, production_stage (1-5), snapshot_time.

    vehicle_variant is never populated on STATION_PROCESSING_STARTED/
    COMPLETED events (a simulator design choice, not a bug -- other event
    types carry it), so it's sourced separately from VEHICLE_ENTERED_STATION,
    which is populated on every vehicle's very first route step."""
    completed = events_df[
        (events_df.event_type == "STATION_PROCESSING_COMPLETED")
        & (events_df.station_id.isin(CHECKPOINT_STATIONS))
    ][["vehicle_id", "shift_id", "station_id", "simulation_time"]]

    variant_lookup = (
        events_df[events_df.event_type == "VEHICLE_ENTERED_STATION"]
        [["vehicle_id", "vehicle_variant"]].drop_duplicates("vehicle_id").set_index("vehicle_id").vehicle_variant
    )

    stage_of = {sid: i + 1 for i, sid in enumerate(CHECKPOINT_STATIONS)}
    completed = completed.copy()
    completed["vehicle_variant"] = completed.vehicle_id.map(variant_lookup)
    completed["production_stage"] = completed.station_id.map(stage_of)
    completed = completed.rename(columns={"station_id": "checkpoint_station_id", "simulation_time": "snapshot_time"})
    return completed.sort_values(["vehicle_id", "production_stage"]).reset_index(drop=True)
