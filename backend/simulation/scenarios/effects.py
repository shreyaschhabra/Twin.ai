"""
StationEffectBundle: the one channel through which active scenarios can
influence a station's processing time and sensor generation. Station code
asks "what's active for me right now" once per visit and applies whatever
comes back — it never checks `if station_id == "S09"` or any scenario
family by name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class StationEffectBundle:
    cycle_time_multiplier: float = 1.0
    variability_multiplier: float = 1.0
    sensor_mean_shift: Dict[str, float] = field(default_factory=dict)
    sensor_noise_multiplier: Dict[str, float] = field(default_factory=dict)
    sensor_dropout_type: Dict[str, str] = field(default_factory=dict)
    sensor_dropout_probability: Dict[str, float] = field(default_factory=dict)
    active_scenario_ids: List[str] = field(default_factory=list)
