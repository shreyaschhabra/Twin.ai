import type { SensorTrustState } from "./common";

/**
 * Sensor trust types for the trust monitoring feature.
 *
 * TwinAI must clearly surface sensor health to operators so they can
 * interpret prediction confidence accurately.
 */

/**
 * Trust state transition event — represents a change in a station's sensor trust.
 * Used to reconstruct trust history and display state timelines.
 */
export type TrustTransitionEvent = {
  stationId: string;
  from: SensorTrustState;
  to: SensorTrustState;
  occurredAt: string; // ISO timestamp
  durationSeconds?: number;
  /** Human-readable explanation of why trust degraded or recovered. */
  reason?: string;
};

/**
 * Sensor dropout scenario data model.
 *
 * Represents the LIVE → INFERRED → UNKNOWN degradation sequence
 * for a station. The UI can use this to animate or display sensor health.
 *
 * All three phases are optional — a station may be mid-degradation
 * and only have data for the first two phases so far.
 */
export type SensorDropoutScenario = {
  stationId: string;

  livePhase?: {
    startedAt: string;
    endedAt: string;
    /** Confidence level during live phase. */
    confidence: "HIGH" | "MEDIUM" | "LOW";
  };

  inferredPhase?: {
    startedAt: string;
    endedAt?: string;
    confidence: "HIGH" | "MEDIUM" | "LOW";
    inferenceSource: string;
  };

  unknownPhase?: {
    startedAt: string;
    endedAt?: string;
    confidence: "HIGH" | "MEDIUM" | "LOW";
  };
};
