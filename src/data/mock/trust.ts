/**
 * MOCK DATA — Development only.
 * Sensor dropout scenario data for the trust monitoring feature.
 * Models the LIVE → INFERRED → UNKNOWN degradation at S11.
 */

import type { SensorDropoutScenario, TrustTransitionEvent } from "@/types/trust";

/** S11 — Active sensor degradation scenario. */
export const mockDropoutScenario: SensorDropoutScenario = {
  stationId: "S11",

  livePhase: {
    startedAt: "2026-08-30T06:00:00Z",
    endedAt: "2026-08-30T10:48:00Z",
    confidence: "HIGH",
  },

  inferredPhase: {
    startedAt: "2026-08-30T10:48:00Z",
    endedAt: "2026-08-30T10:52:00Z",
    confidence: "MEDIUM",
    inferenceSource: "Adjacent sensor S10 + historical cycle-time model",
  },

  unknownPhase: {
    startedAt: "2026-08-30T10:52:00Z",
    // No endedAt — still in UNKNOWN phase
    confidence: "LOW",
  },
};

/** S12 — Completed dropout (camera fault, now recovered). */
export const mockS12DropoutHistory: SensorDropoutScenario = {
  stationId: "S12",

  livePhase: {
    startedAt: "2026-08-30T06:00:00Z",
    endedAt: "2026-08-30T10:31:00Z",
    confidence: "HIGH",
  },

  inferredPhase: {
    startedAt: "2026-08-30T10:31:00Z",
    endedAt: "2026-08-30T10:36:00Z",
    confidence: "MEDIUM",
    inferenceSource: "Cycle-time model + S11 process completion signal",
  },

  unknownPhase: {
    startedAt: "2026-08-30T10:36:00Z",
    endedAt: "2026-08-30T10:42:00Z", // Recovered at 10:42
    confidence: "LOW",
  },
};

/** Transition events for the alert/history feed. */
export const mockTrustTransitions: TrustTransitionEvent[] = [
  {
    stationId: "S11",
    from: "LIVE",
    to: "INFERRED",
    occurredAt: "2026-08-30T10:48:00Z",
    durationSeconds: 240,
    reason: "Primary sensor signal lost — switching to inferred mode via adjacent context",
  },
  {
    stationId: "S11",
    from: "INFERRED",
    to: "UNKNOWN",
    occurredAt: "2026-08-30T10:52:00Z",
    reason: "Inference confidence below threshold — insufficient adjacent signal",
  },
  {
    stationId: "S12",
    from: "LIVE",
    to: "INFERRED",
    occurredAt: "2026-08-30T10:31:00Z",
    durationSeconds: 300,
    reason: "Camera system lost alignment reference",
  },
  {
    stationId: "S12",
    from: "INFERRED",
    to: "UNKNOWN",
    occurredAt: "2026-08-30T10:36:00Z",
    durationSeconds: 360,
    reason: "Inference model lost sufficient anchor points",
  },
  {
    stationId: "S12",
    from: "UNKNOWN",
    to: "LIVE",
    occurredAt: "2026-08-30T10:42:00Z",
    reason: "Camera system recalibrated and restored — sensor trust recovered",
  },
];
