import type {
  ConfidenceLevel,
  EvidenceItem,
  ISOTimestamp,
} from "./common";
import type { VehicleVariant } from "./vehicle";

/** Quality risk status bucket — maps risk probability to operator-facing label. */
export type QualityRiskStatus = "LOW" | "WATCH" | "HIGH";

/**
 * A risk history data point — for rendering trend sparklines.
 */
export type QualityRiskPoint = {
  stationId: string;
  timestamp: ISOTimestamp;
  /** Defect risk probability at this point in the vehicle's journey, 0–1. */
  risk: number;
};

/**
 * Frontend quality prediction contract for a single vehicle.
 *
 * defectRisk and confidence are always separate.
 * A vehicle can have high defect risk with LOW confidence
 * (e.g. sensor dropout causing the model to extrapolate).
 */
export type QualityPrediction = {
  vehicleId: string;
  variant: VehicleVariant;
  currentStage: string;

  /** Probability of a production defect, 0–1. */
  defectRisk: number;

  /** Confidence in the defectRisk prediction. */
  confidence: ConfidenceLevel;

  status: QualityRiskStatus;

  /** Risk accumulation history across stations visited so far. */
  riskHistory: QualityRiskPoint[];

  /** Structured evidence supporting the current defect risk level. */
  evidence: EvidenceItem[];

  /**
   * ID of the anomaly exposure cohort this vehicle belongs to, if any.
   * Links to ExposureCohort.id for detailed cohort information.
   */
  exposureCohortId?: string;
};

/**
 * Anomaly exposure cohort.
 *
 * Represents a group of vehicles that passed through a station during
 * a detected anomaly window. Used to identify vehicles requiring
 * additional quality scrutiny at end-of-line or final inspection.
 */
export type ExposureCohort = {
  id: string;
  stationId: string;

  startTime: ISOTimestamp;
  endTime: ISOTimestamp;

  /** All vehicle IDs that passed through the affected station during the window. */
  affectedVehicleIds: string[];

  /** Subset of affectedVehicleIds with elevated defect risk (e.g. > 0.5). */
  highRiskVehicleIds: string[];

  /** Human-readable description of the anomaly or triggering condition. */
  description: string;

  evidence?: EvidenceItem[];
};
