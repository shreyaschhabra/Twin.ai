/**
 * Common primitive types shared across Twin AI domain.
 */

/** ISO 8601 timestamp string. */
export type ISOTimestamp = string;

/** Canonical confidence in a model prediction. Separate from risk probability. */
export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";

/**
 * Sensor trust state for a station or data source.
 *
 * LIVE     — real-time sensor data is healthy and current.
 * INFERRED — sensor gap; value is inferred from adjacent context or model.
 * UNKNOWN  — insufficient evidence to determine a value; treat with caution.
 *
 * "Blind Spot" is not a separate runtime enum; it is communicated through
 * UNKNOWN combined with contextual evidence.
 */
export type SensorTrustState = "LIVE" | "INFERRED" | "UNKNOWN";

/**
 * Sensor coverage maturity of a station's instrumentation.
 *
 * RICH    — comprehensive, high-frequency, high-reliability sensors.
 * PARTIAL — some sensors missing, intermittent, or lower-frequency.
 * POOR    — minimal instrumentation; significant inference required.
 */
export type SensorMaturity = "RICH" | "PARTIAL" | "POOR";

/** Alert severity levels, from informational to critical. */
export type AlertSeverity = "INFO" | "WATCH" | "WARNING" | "CRITICAL";

/** Alert kind — which domain generated the alert. */
export type AlertKind = "FLOW" | "QUALITY" | "SENSOR" | "ANOMALY";

/**
 * A single piece of structured evidence supporting a prediction or alert.
 * direction: "negative" = worsening indicator, "positive" = improving, "neutral" = informational.
 */
export type EvidenceItem = {
  label: string;
  value: string;
  direction: "negative" | "positive" | "neutral";
};

/** Sensor coverage summary — percentage of readings in each trust state. */
export type SensorCoverageSummary = {
  livePercent: number;
  inferredPercent: number;
  unknownPercent: number;
};
