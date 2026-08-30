/**
 * MOCK DATA — Development only.
 *
 * Quality prediction scenarios and anomaly exposure cohorts.
 *
 * Key scenario: V2048 (EV) with risk progression 4% → 17% → 21% → 79%
 * due to anomaly exposure at S12 (Instrument Panel Robot).
 */

import type { ExposureCohort, QualityPrediction } from "@/types/quality";

// ─── QUALITY PREDICTIONS ──────────────────────────────────────────────────────

export const mockQualityPredictions: QualityPrediction[] = [
  // ── V2048 — HIGH RISK (QUALITY SCENARIO) ─────────────────────────────────
  {
    vehicleId: "V2048",
    variant: "EV",
    currentStage: "General Assembly",
    defectRisk: 0.79,
    confidence: "HIGH",
    status: "HIGH",
    riskHistory: [
      { stationId: "S01", timestamp: "2026-08-30T05:01:05Z", risk: 0.04 },
      { stationId: "S02", timestamp: "2026-08-30T05:07:00Z", risk: 0.07 },
      { stationId: "S07", timestamp: "2026-08-30T05:40:50Z", risk: 0.17 },
      { stationId: "S08", timestamp: "2026-08-30T05:47:00Z", risk: 0.21 },
      { stationId: "S12", timestamp: "2026-08-30T06:31:00Z", risk: 0.79 },
    ],
    evidence: [
      { label: "Anomaly exposure",       value: "S12 — 10:31–10:42 window", direction: "negative" },
      { label: "Sensor trust at S12",    value: "INFERRED (camera dropout)",  direction: "negative" },
      { label: "Risk jump at S12",       value: "+58 percentage points",      direction: "negative" },
      { label: "Prior risk trajectory",  value: "Gradual — within norms",     direction: "positive" },
    ],
    exposureCohortId: "EC-S12-20260830-1031",
  },

  // ── V2051 — WATCH (SENSOR DROPOUT) ──────────────────────────────────────
  {
    vehicleId: "V2051",
    variant: "EV",
    currentStage: "General Assembly",
    defectRisk: 0.31,
    confidence: "LOW",
    status: "WATCH",
    riskHistory: [
      { stationId: "S11", timestamp: "2026-08-30T06:55:00Z", risk: 0.31 },
    ],
    evidence: [
      { label: "Sensor trust",     value: "UNKNOWN — insufficient data",  direction: "negative" },
      { label: "Confidence",       value: "LOW — sensor dropout at S11",   direction: "negative" },
      { label: "Estimated risk",   value: "Inferred from adjacent cohort", direction: "neutral"  },
    ],
  },

  // ── V2045 — WATCH (EV ELEVATED BASELINE) ────────────────────────────────
  {
    vehicleId: "V2045",
    variant: "EV",
    currentStage: "Body Shop",
    defectRisk: 0.21,
    confidence: "MEDIUM",
    status: "WATCH",
    riskHistory: [
      { stationId: "S01", timestamp: "2026-08-30T06:11:12Z", risk: 0.05 },
      { stationId: "S02", timestamp: "2026-08-30T06:17:00Z", risk: 0.09 },
      { stationId: "S03", timestamp: "2026-08-30T06:28:10Z", risk: 0.21 },
    ],
    evidence: [
      { label: "Variant",          value: "EV — higher baseline risk", direction: "neutral"  },
      { label: "Cycle-time trend", value: "+3% at S03",                direction: "negative" },
      { label: "Sensor trust",     value: "LIVE — full coverage",      direction: "positive" },
    ],
  },

  // ── V2043 — LOW RISK ────────────────────────────────────────────────────
  {
    vehicleId: "V2043",
    variant: "ICE_SEDAN",
    currentStage: "Body Shop",
    defectRisk: 0.04,
    confidence: "HIGH",
    status: "LOW",
    riskHistory: [
      { stationId: "S01", timestamp: "2026-08-30T06:01:02Z", risk: 0.04 },
    ],
    evidence: [
      { label: "Sensor trust",  value: "LIVE — full coverage",   direction: "positive" },
      { label: "Cycle time",    value: "On baseline",             direction: "positive" },
    ],
  },

  // ── V2044 — LOW RISK ────────────────────────────────────────────────────
  {
    vehicleId: "V2044",
    variant: "ICE_SUV",
    currentStage: "Body Shop",
    defectRisk: 0.06,
    confidence: "HIGH",
    status: "LOW",
    riskHistory: [
      { stationId: "S01", timestamp: "2026-08-30T06:06:05Z", risk: 0.06 },
      { stationId: "S02", timestamp: "2026-08-30T06:22:00Z", risk: 0.06 },
    ],
    evidence: [
      { label: "Sensor trust",  value: "LIVE — full coverage",   direction: "positive" },
    ],
  },
];

export const qualityPredictionByVehicle = new Map<string, QualityPrediction>(
  mockQualityPredictions.map((q) => [q.vehicleId, q]),
);

// ─── EXPOSURE COHORTS ─────────────────────────────────────────────────────────

export const mockExposureCohorts: ExposureCohort[] = [
  {
    id: "EC-S12-20260830-1031",
    stationId: "S12",
    startTime: "2026-08-30T10:31:00Z",
    endTime: "2026-08-30T10:42:00Z",
    affectedVehicleIds: ["V2048", "V2049", "V2050", "V2051", "V2052"],
    highRiskVehicleIds: ["V2048"],
    description: "Instrument Panel Robot (S12) — camera system dropout during panel alignment cycle. Anomaly detected via cycle-time spike and missing vision confirmation events.",
    evidence: [
      { label: "Anomaly type",    value: "Sensor dropout — vision system", direction: "negative" },
      { label: "Duration",        value: "11 minutes",                     direction: "negative" },
      { label: "Vehicles in window", value: "5",                           direction: "neutral"  },
      { label: "High-risk flags",  value: "1 (V2048)",                     direction: "negative" },
    ],
  },
];

export const exposureCohortById = new Map<string, ExposureCohort>(
  mockExposureCohorts.map((c) => [c.id, c]),
);
