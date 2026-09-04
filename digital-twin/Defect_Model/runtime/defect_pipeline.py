"""End-to-end finalized V5 defect runtime pipeline with optional SHAP."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

try:
    from .defect_feature_runtime import DefectRuntimeFeatureBuilder, DefectFeaturePacket
    from .dark_zone_adapter import DefectDarkZoneAdapter, DarkInferredArrival
    from ..ml.defect_model_runtime import DefectModelRuntime, DefectPrediction
except ImportError:  # direct legacy execution with Defect_Model on sys.path
    from runtime.defect_feature_runtime import DefectRuntimeFeatureBuilder, DefectFeaturePacket
    from runtime.dark_zone_adapter import DefectDarkZoneAdapter, DarkInferredArrival
    from ml.defect_model_runtime import DefectModelRuntime, DefectPrediction


class DigitalTwinDefectPipeline:
    """Persistent production pipeline. Instantiate once, then feed live records."""

    def __init__(
        self,
        *,
        stations_csv: str | Path,
        units_csv: str | Path,
        model_artifact_path: str | Path | None = None,
        config_path: str | Path | None = None,
        calibrator_path: str | Path | None = None,
        run_id: str = "LIVE",
        explain_mode: str = "warnings",
        shap_top_k: int = 3,
        dark_adapter: Optional[DefectDarkZoneAdapter] = None,
    ):
        explain_mode = str(explain_mode).strip().lower()
        if explain_mode not in {"off", "warnings", "all"}:
            raise ValueError("explain_mode must be: off, warnings, or all")
        if int(shap_top_k) < 1:
            raise ValueError("shap_top_k must be >= 1")

        self.explain_mode = explain_mode
        self.shap_top_k = int(shap_top_k)
        self.dark_adapter = dark_adapter

        self.features = DefectRuntimeFeatureBuilder(
            stations_csv=stations_csv,
            units_csv=units_csv,
            run_id=run_id,
        )
        supplied = [model_artifact_path, config_path, calibrator_path]
        if any(value is None for value in supplied) and not all(value is None for value in supplied):
            raise ValueError(
                "model_artifact_path, config_path, and calibrator_path must either all be supplied or all be omitted"
            )
        self.model = None
        if model_artifact_path is not None:
            self.model = DefectModelRuntime(
                model_artifact_path=model_artifact_path,
                config_path=config_path,
                calibrator_path=calibrator_path,
            )
            if self.features.feature_names != self.model.features:
                raise RuntimeError(
                    "Defect runtime feature builder and V5 CatBoost feature contracts differ"
                )

    def reset(self) -> None:
        self.features.reset()
        self.model.reset()

    def refresh_units(self, units_csv: str | Path) -> int:
        return self.features.refresh_units(units_csv)

    def _score_packet(self, packet: DefectFeaturePacket) -> DefectPrediction:
        if self.model is None:
            raise RuntimeError("This defect pipeline was created in feature-only mode")
        # For warnings mode, score first and only pay SHAP cost for actionable warnings.
        if self.explain_mode == "off":
            return self.model.predict_packet(packet, explain=False)
        if self.explain_mode == "all":
            return self.model.predict_packet(
                packet, explain=True, shap_top_k=self.shap_top_k
            )

        prediction = self.model.predict_packet(packet, explain=False)
        if prediction.warning:
            exp = self.model.explain_feature_row(
                packet.features_30,
                top_k=self.shap_top_k,
                expected_probability=prediction.raw_defect_probability,
            )
            prediction.explanation_available = True
            prediction.explanation_method = exp["method"]
            prediction.shap_value_space = exp["shap_value_space"]
            prediction.shap_base_value_raw = exp["base_value_raw"]
            prediction.shap_reconstructed_probability = exp["reconstructed_probability"]
            prediction.shap_probability_reconstruction_error = exp["probability_reconstruction_error"]
            prediction.top_risk_drivers = exp["top_risk_drivers"]
            prediction.top_protective_drivers = exp["top_protective_drivers"]
        return prediction

    def _packets_from_dark_arrivals(
        self, arrivals: list[DarkInferredArrival]
    ) -> list[DefectFeaturePacket]:
        out: list[DefectFeaturePacket] = []
        for a in arrivals:
            packet = self.features.process_inferred_dark_arrival(
                unit_id=a.unit_id,
                station_id=a.station_id,
                timestamp_ms=a.timestamp_ms,
                queue_estimate=a.queue_estimate,
                state_confidence=a.state_confidence,
                trigger=a.trigger,
                estimated_transition_time_ms=a.estimated_transition_time_ms,
            )
            if packet is not None:
                out.append(packet)
        return out

    def _score_dark_arrivals(
        self, arrivals: list[DarkInferredArrival]
    ) -> list[DefectPrediction]:
        return [self._score_packet(packet) for packet in self._packets_from_dark_arrivals(arrivals)]

    def process_station_event_packets(
        self, event: Mapping[str, Any]
    ) -> list[DefectFeaturePacket]:
        e = dict(event)
        packets: list[DefectFeaturePacket] = []
        if self.dark_adapter is not None:
            packets.extend(
                self._packets_from_dark_arrivals(self.dark_adapter.process_station_event(e))
            )

        is_dark = self.dark_adapter is not None and self.dark_adapter.is_dark_station(
            e.get("station_id", "")
        )
        event_type = str(e.get("event_type", "")).strip().upper()
        if is_dark and event_type in {"UNIT_ARRIVED", "PROCESSING_STARTED", "PROCESSING_COMPLETED"}:
            raise RuntimeError(
                f"Hidden DARK processing event leaked onto defect public stream: "
                f"{e.get('station_id')} {event_type}"
            )

        packet = self.features.process_station_event(e)
        if packet is not None:
            packets.append(packet)

        if (
            self.dark_adapter is not None
            and event_type == "DARK_ZONE_EXITED"
            and e.get("unit_id") is not None
        ):
            self.features.finalize_dark_vehicle(str(e["unit_id"]), int(e["timestamp_ms"]))
        return packets

    def process_sensor_reading_packets(
        self, reading: Mapping[str, Any]
    ) -> list[DefectFeaturePacket]:
        r = dict(reading)
        if self.dark_adapter is None or not self.dark_adapter.is_dark_station(r.get("station_id", "")):
            self.features.process_sensor_reading(r)
            return []
        if not self.dark_adapter.allows_dark_sensor(r.get("station_id", "")):
            raise RuntimeError(
                f"SENSOR observation appeared in DARK station {r.get('station_id')} "
                "where dz.csv has sensor_telemetry=false"
            )

        association, arrivals = self.dark_adapter.observe_sensor_station(
            station_id=str(r["station_id"]), timestamp_ms=int(r["timestamp_ms"])
        )
        packets = self._packets_from_dark_arrivals(arrivals)
        uid, confidence = self.dark_adapter.best_sensor_unit(association)
        if uid is None:
            self.features.process_dark_sensor_reading(
                r, unit_id="__UNASSIGNED__", attribution_confidence=confidence,
                min_confidence=self.dark_adapter.sensor_assignment_confidence,
            )
            return packets
        self.features.process_dark_sensor_reading(
            r, unit_id=uid, attribution_confidence=confidence,
            min_confidence=self.dark_adapter.sensor_assignment_confidence,
        )
        return packets

    def process_evidence_event_packets(
        self, evidence: Mapping[str, Any]
    ) -> list[DefectFeaturePacket]:
        if self.dark_adapter is None:
            return []
        e = dict(evidence)
        if (
            self.dark_adapter.is_dark_station(e.get("station_id", ""))
            and not self.dark_adapter.allows_dark_checkpoint(e.get("station_id", ""))
        ):
            raise RuntimeError(
                f"Checkpoint evidence appeared in DARK station {e.get('station_id')} "
                "where dz.csv has checkpoints=false"
            )
        return self._packets_from_dark_arrivals(self.dark_adapter.process_evidence_event(e))

    def process_manual_check_packets(
        self, check: Mapping[str, Any]
    ) -> list[DefectFeaturePacket]:
        c = dict(check)
        if (
            self.dark_adapter is not None
            and self.dark_adapter.is_dark_station(c.get("station_id", ""))
            and not self.dark_adapter.allows_dark_manual(c.get("station_id", ""))
        ):
            raise RuntimeError(
                f"MANUAL observation appeared in DARK station {c.get('station_id')} "
                "where dz.csv has manual_checks=false"
            )
        self.features.process_manual_check(c)
        return []

    def process_record_packets(
        self, record: Mapping[str, Any]
    ) -> list[DefectFeaturePacket]:
        r = dict(record)
        stream = str(r.pop("stream", "")).strip().lower()
        if stream == "station_event":
            return self.process_station_event_packets(r)
        if stream == "sensor_reading":
            return self.process_sensor_reading_packets(r)
        if stream == "manual_check":
            return self.process_manual_check_packets(r)
        if stream == "evidence":
            return self.process_evidence_event_packets(r)
        raise ValueError(
            "record.stream must be one of: station_event, sensor_reading, manual_check, evidence"
        )

    def process_station_event(
        self, event: Mapping[str, Any]
    ) -> list[DefectPrediction]:
        return [self._score_packet(packet) for packet in self.process_station_event_packets(event)]

    def process_sensor_reading(
        self, reading: Mapping[str, Any]
    ) -> list[DefectPrediction]:
        return [self._score_packet(packet) for packet in self.process_sensor_reading_packets(reading)]

    def process_evidence_event(
        self, evidence: Mapping[str, Any]
    ) -> list[DefectPrediction]:
        return [self._score_packet(packet) for packet in self.process_evidence_event_packets(evidence)]

    def process_manual_check(
        self, check: Mapping[str, Any]
    ) -> list[DefectPrediction]:
        self.process_manual_check_packets(check)
        return []

    def process_record(
        self, record: Mapping[str, Any]
    ) -> list[DefectPrediction]:
        return [self._score_packet(packet) for packet in self.process_record_packets(record)]

    def summary(self) -> dict[str, Any]:
        return {
            "pipeline": "defect-v5-runtime-v3",
            "dark_zone_used": self.dark_adapter is not None and bool(self.dark_adapter.dark_station_ids),
            "dark_zone": self.dark_adapter.diagnostics() if self.dark_adapter is not None else None,
            "prediction_trigger": "UNIT_ARRIVED",
            "target": "future final-inspection FAIL",
            "feature_builder": self.features.diagnostics(),
            "model": self.model.model_summary() if self.model is not None else None,
            "feature_contract_match": (
                self.features.feature_names == self.model.features
                if self.model is not None else True
            ),
            "explain_mode": self.explain_mode,
            "shap_top_k": self.shap_top_k,
        }
