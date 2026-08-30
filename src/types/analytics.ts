import type { ISOTimestamp } from "./common";

/**
 * Plant Manager analytics contracts.
 *
 * These are frontend data structures for rendering analytics dashboards.
 * No calculations are done here — the backend or mock data provides
 * pre-computed values.
 */

/** A single time-series data point for trend charts. */
export type TrendPoint = {
  timestamp: ISOTimestamp;
  value: number;
};

/** Station throughput contribution over a time window. */
export type ThroughputTrend = {
  stationId: string;
  stationName: string;
  /** Vehicles processed per hour, measured over the last N minutes. */
  vehiclesPerHour: number;
  trend: TrendPoint[];
};

/** Bottleneck occurrence frequency by station. */
export type BottleneckHotspot = {
  stationId: string;
  stationName: string;
  /** Number of bottleneck events in the analysis window. */
  occurrences: number;
  /** Average duration of each bottleneck event in minutes. */
  avgDurationMin: number;
  /** Total estimated throughput loss in vehicles. */
  estimatedThroughputLoss: number;
};

/** Defect concentration by station. */
export type DefectHotspot = {
  stationId: string;
  stationName: string;
  /** Defect rate as a proportion of vehicles passing this station. */
  defectRate: number;
  /** Number of high-risk vehicles flagged at this station. */
  highRiskVehicleCount: number;
};

/** System-level false-alert trend over time. */
export type FalseAlertTrend = {
  period: string; // e.g. "2026-08-30T06:00"
  falseAlerts: number;
  totalAlerts: number;
  falseAlertRate: number;
};

/** Stations with identified sensor data gaps. */
export type SensorGapSummary = {
  stationId: string;
  stationName: string;
  /** Percentage of readings classified as INFERRED or UNKNOWN. */
  gapPercent: number;
  /** Most recent gap event timestamp. */
  lastGapAt?: ISOTimestamp;
};

/**
 * Top-level analytics summary for a Plant Manager shift view.
 */
export type ManagerAnalytics = {
  /** As-of timestamp for this analytics snapshot. */
  asOf: ISOTimestamp;

  /** Active bottleneck or high-risk flow events. */
  activeFlowWarnings: number;

  /** Vehicles currently flagged WATCH or HIGH_RISK for quality. */
  activeQualityFlags: number;

  /** Stations currently in INFERRED or UNKNOWN trust state. */
  sensorGapStations: number;

  throughputTrend: ThroughputTrend[];
  bottleneckHotspots: BottleneckHotspot[];
  defectHotspots: DefectHotspot[];
  falseAlertTrend: FalseAlertTrend[];
  sensorGaps: SensorGapSummary[];
};

/**
 * Shift-level historical summary analytics.
 */
export type ShiftAnalytics = {
  shiftId: string;
  throughput: number;
  bottleneckEvents: number;
  defectRate: number; // e.g. 0.038 for 3.8%
  falseAlerts: number;
  medianWarningLeadTime: number; // in minutes
  unknownCoverage: number; // e.g. 0.08 for 8%
};

/**
 * Maintenance candidate identifying stations requiring operational or quality inspection.
 */
export type MaintenanceCandidate = {
  stationId: string;
  stationName: string;
  reason: string;
  flowEvents: number;
  qualityExposure: number; // vehicles exposed
  minorStops: number;
  maintenanceAgePercent: number; // 0-100 representing tool wear/age
};

/**
 * Recurring anomaly pattern.
 */
export type AnomalyPattern = {
  stationId: string;
  stationName: string;
  anomalyType: string;
  occurrences: number;
  avgDurationMin: number;
  vehiclesExposed: number;
};

