import type {
  ConfidenceLevel,
  ISOTimestamp,
  SensorCoverageSummary,
  SensorTrustState,
} from "./common";

/**
 * Vehicle variants produced on the Twin AI monitored line.
 *
 * ICE_SEDAN — internal combustion engine sedan body style.
 * ICE_SUV   — internal combustion engine SUV body style.
 * EV        — battery electric vehicle (additional stations, longer cycle times).
 */
export type VehicleVariant = "ICE_SEDAN" | "ICE_SUV" | "EV";

/** Vehicle production/quality status. */
export type VehicleStatus = "ON_TRACK" | "WATCH" | "HIGH_RISK" | "COMPLETE";

/**
 * A single genealogy event — one station passage in a vehicle's production journey.
 *
 * Used to reconstruct the full history of exposure, quality risk accumulation,
 * and sensor trust per station visited.
 */
export type VehicleGenealogyEvent = {
  stationId: string;
  stationName: string;

  enteredAt: ISOTimestamp;
  exitedAt?: ISOTimestamp;

  processStatus: "COMPLETE" | "IN_PROGRESS" | "SKIPPED";

  /** Whether an anomaly was detected at this station during this vehicle's pass. */
  anomalyExposure: boolean;

  /** Cumulative defect risk score after exiting this station. */
  qualityRiskAfterStation: number;

  sensorTrustState: SensorTrustState;
};

/**
 * Frontend vehicle contract.
 *
 * Represents the current state and risk profile of a vehicle on the production line.
 * Does not model raw sensor telemetry — that lives in the backend.
 */
export type Vehicle = {
  id: string;
  variant: VehicleVariant;

  /** Station where the vehicle currently resides. */
  currentStationId: string;

  /** Human-readable production stage label, e.g. "Body Shop", "Paint". */
  currentStage: string;

  status: VehicleStatus;

  /** Probability of a quality defect, 0–1. */
  qualityRisk: number;

  /** Confidence in the qualityRisk prediction. */
  confidence: ConfidenceLevel;

  sensorCoverage: SensorCoverageSummary;

  /** Full production genealogy — one entry per station visited. */
  genealogy: VehicleGenealogyEvent[];
};
