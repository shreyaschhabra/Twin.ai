import type {
  AlertKind,
  AlertSeverity,
  ConfidenceLevel,
  EvidenceItem,
  ISOTimestamp,
} from "./common";

/**
 * Unified frontend alert model.
 *
 * All alert types (flow, quality, sensor, anomaly) share this contract.
 * The `kind` field determines which domain fields are relevant.
 *
 * stationId and vehicleId are both optional — some alerts are station-level,
 * some are vehicle-level, some are system-level.
 */
export type Alert = {
  id: string;
  kind: AlertKind;
  severity: AlertSeverity;

  title: string;
  description: string;

  timestamp: ISOTimestamp;

  /** Station associated with this alert, if applicable. */
  stationId?: string;

  /** Vehicle associated with this alert, if applicable. */
  vehicleId?: string;

  /**
   * Risk probability that triggered this alert, 0–1.
   * For FLOW alerts: bottleneck risk. For QUALITY: defect risk.
   */
  risk?: number;

  /** Confidence in the underlying prediction. */
  confidence?: ConfidenceLevel;

  /** Structured evidence supporting the alert. */
  evidence?: EvidenceItem[];

  /** Whether a supervisor has acknowledged this alert. */
  acknowledged: boolean;
};
