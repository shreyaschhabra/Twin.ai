/**
 * MOCK DATA — Development only.
 *
 * Representative vehicle set covering all three variants and risk levels.
 * Includes the V2048 quality-risk scenario and sensor dropout vehicle.
 */

import type { Vehicle } from "@/types/vehicle";

export const mockVehicles: Vehicle[] = [
  // ── HEALTHY ICE SEDAN ────────────────────────────────────────────────────
  {
    id: "V2043",
    variant: "ICE_SEDAN",
    currentStationId: "S01",
    currentStage: "Body Shop",
    status: "ON_TRACK",
    qualityRisk: 0.04,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 96, inferredPercent: 3, unknownPercent: 1 },
    genealogy: [
      {
        stationId: "S01", stationName: "Body Side Inner Weld",
        enteredAt: "2026-08-30T06:00:00Z", exitedAt: "2026-08-30T06:01:02Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.04, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── HEALTHY ICE SUV ──────────────────────────────────────────────────────
  {
    id: "V2044",
    variant: "ICE_SUV",
    currentStationId: "S02",
    currentStage: "Body Shop",
    status: "ON_TRACK",
    qualityRisk: 0.06,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 94, inferredPercent: 5, unknownPercent: 1 },
    genealogy: [
      {
        stationId: "S01", stationName: "Body Side Inner Weld",
        enteredAt: "2026-08-30T06:05:00Z", exitedAt: "2026-08-30T06:06:05Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.06, sensorTrustState: "LIVE",
      },
      {
        stationId: "S02", stationName: "Floor Pan Weld",
        enteredAt: "2026-08-30T06:10:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.06, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── EV — WATCH STATUS ────────────────────────────────────────────────────
  {
    id: "V2045",
    variant: "EV",
    currentStationId: "S03",
    currentStage: "Body Shop",
    status: "WATCH",
    qualityRisk: 0.21,
    confidence: "MEDIUM",
    sensorCoverage: { livePercent: 82, inferredPercent: 14, unknownPercent: 4 },
    genealogy: [
      {
        stationId: "S01", stationName: "Body Side Inner Weld",
        enteredAt: "2026-08-30T06:10:00Z", exitedAt: "2026-08-30T06:11:12Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.05, sensorTrustState: "LIVE",
      },
      {
        stationId: "S02", stationName: "Floor Pan Weld",
        enteredAt: "2026-08-30T06:16:00Z", exitedAt: "2026-08-30T06:17:00Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.09, sensorTrustState: "LIVE",
      },
      {
        stationId: "S03", stationName: "Roof Panel Weld",
        enteredAt: "2026-08-30T06:22:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.21, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── ICE SEDAN — WATCH ────────────────────────────────────────────────────
  {
    id: "V2046",
    variant: "ICE_SEDAN",
    currentStationId: "S04",
    currentStage: "Body Shop",
    status: "WATCH",
    qualityRisk: 0.17,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 91, inferredPercent: 7, unknownPercent: 2 },
    genealogy: [
      {
        stationId: "S01", stationName: "Body Side Inner Weld",
        enteredAt: "2026-08-30T06:15:00Z", exitedAt: "2026-08-30T06:16:05Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.04, sensorTrustState: "LIVE",
      },
      {
        stationId: "S02", stationName: "Floor Pan Weld",
        enteredAt: "2026-08-30T06:21:00Z", exitedAt: "2026-08-30T06:22:00Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.08, sensorTrustState: "LIVE",
      },
      {
        stationId: "S03", stationName: "Roof Panel Weld",
        enteredAt: "2026-08-30T06:27:00Z", exitedAt: "2026-08-30T06:28:10Z",
        processStatus: "COMPLETE", anomalyExposure: true,
        qualityRiskAfterStation: 0.17, sensorTrustState: "INFERRED",
      },
      {
        stationId: "S04", stationName: "A-Pillar Weld",
        enteredAt: "2026-08-30T06:33:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.17, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── ICE SUV — WATCH ──────────────────────────────────────────────────────
  // Benign vehicle-mix variation scenario — ICE_SUV heavy, cycle time elevated
  // but NOT a critical bottleneck. Demonstrates false-alert control.
  {
    id: "V2047",
    variant: "ICE_SUV",
    currentStationId: "S06",
    currentStage: "Body Shop",
    status: "WATCH",
    qualityRisk: 0.12,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 88, inferredPercent: 10, unknownPercent: 2 },
    genealogy: [
      {
        stationId: "S01", stationName: "Body Side Inner Weld",
        enteredAt: "2026-08-30T06:20:00Z", exitedAt: "2026-08-30T06:21:08Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.05, sensorTrustState: "LIVE",
      },
      {
        stationId: "S06", stationName: "Door Aperture Weld",
        enteredAt: "2026-08-30T06:42:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.12, sensorTrustState: "INFERRED",
      },
    ],
  },

  // ── EV — HIGH RISK (QUALITY SCENARIO VEHICLE) ────────────────────────────
  // V2048 — Anomaly exposure at S12. Risk progression: 4% → 17% → 21% → 79%
  {
    id: "V2048",
    variant: "EV",
    currentStationId: "S12",
    currentStage: "General Assembly",
    status: "HIGH_RISK",
    qualityRisk: 0.79,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 71, inferredPercent: 24, unknownPercent: 5 },
    genealogy: [
      {
        stationId: "S01", stationName: "Body Side Inner Weld",
        enteredAt: "2026-08-30T05:00:00Z", exitedAt: "2026-08-30T05:01:05Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.04, sensorTrustState: "LIVE",
      },
      {
        stationId: "S02", stationName: "Floor Pan Weld",
        enteredAt: "2026-08-30T05:06:00Z", exitedAt: "2026-08-30T05:07:00Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.07, sensorTrustState: "LIVE",
      },
      {
        stationId: "S07", stationName: "Structural Adhesive Apply",
        enteredAt: "2026-08-30T05:40:00Z", exitedAt: "2026-08-30T05:40:50Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.17, sensorTrustState: "LIVE",
      },
      {
        stationId: "S08", stationName: "Hem Flange Seal",
        enteredAt: "2026-08-30T05:46:00Z", exitedAt: "2026-08-30T05:47:00Z",
        processStatus: "COMPLETE", anomalyExposure: false,
        qualityRiskAfterStation: 0.21, sensorTrustState: "LIVE",
      },
      {
        // Anomaly exposure at S12 — instrument panel robot fault during this window
        stationId: "S12", stationName: "Instrument Panel Robot",
        enteredAt: "2026-08-30T06:31:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: true,
        qualityRiskAfterStation: 0.79, sensorTrustState: "INFERRED",
      },
    ],
  },

  // ── ICE SEDAN — ON TRACK ─────────────────────────────────────────────────
  {
    id: "V2049",
    variant: "ICE_SEDAN",
    currentStationId: "S08",
    currentStage: "Body Shop",
    status: "ON_TRACK",
    qualityRisk: 0.05,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 95, inferredPercent: 4, unknownPercent: 1 },
    genealogy: [
      {
        stationId: "S08", stationName: "Hem Flange Seal",
        enteredAt: "2026-08-30T06:44:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.05, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── ICE SUV — ON TRACK ───────────────────────────────────────────────────
  {
    id: "V2050",
    variant: "ICE_SUV",
    currentStationId: "S09",
    currentStage: "Body Shop",
    status: "ON_TRACK",
    qualityRisk: 0.07,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 93, inferredPercent: 6, unknownPercent: 1 },
    genealogy: [
      {
        stationId: "S09", stationName: "Underbody Sealer",
        enteredAt: "2026-08-30T06:50:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.07, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── EV — SENSOR DROPOUT SCENARIO ─────────────────────────────────────────
  // V2051 — sensor trust degrading LIVE → INFERRED → UNKNOWN at S11
  {
    id: "V2051",
    variant: "EV",
    currentStationId: "S11",
    currentStage: "General Assembly",
    status: "WATCH",
    qualityRisk: 0.31,
    confidence: "LOW",
    sensorCoverage: { livePercent: 45, inferredPercent: 35, unknownPercent: 20 },
    genealogy: [
      {
        stationId: "S11", stationName: "Door Hinge Robot",
        enteredAt: "2026-08-30T06:55:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.31, sensorTrustState: "UNKNOWN",
      },
    ],
  },

  // ── ICE SEDAN — BLOCKED AT S13 ───────────────────────────────────────────
  {
    id: "V2052",
    variant: "ICE_SEDAN",
    currentStationId: "S12",
    currentStage: "General Assembly",
    status: "ON_TRACK",
    qualityRisk: 0.08,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 90, inferredPercent: 8, unknownPercent: 2 },
    genealogy: [
      {
        stationId: "S12", stationName: "Instrument Panel Robot",
        enteredAt: "2026-08-30T07:00:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.08, sensorTrustState: "INFERRED",
      },
    ],
  },

  // ── ICE SUV — BLOCKED STATION OCCUPANT ──────────────────────────────────
  {
    id: "V2053",
    variant: "ICE_SUV",
    currentStationId: "S13",
    currentStage: "General Assembly",
    status: "ON_TRACK",
    qualityRisk: 0.06,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 92, inferredPercent: 7, unknownPercent: 1 },
    genealogy: [
      {
        stationId: "S13", stationName: "Seat Install Robot",
        enteredAt: "2026-08-30T07:05:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.06, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── EV — ON TRACK, LATE LINE ─────────────────────────────────────────────
  {
    id: "V2054",
    variant: "EV",
    currentStationId: "S14",
    currentStage: "General Assembly",
    status: "ON_TRACK",
    qualityRisk: 0.09,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 89, inferredPercent: 9, unknownPercent: 2 },
    genealogy: [
      {
        stationId: "S14", stationName: "Engine Dress Robot",
        enteredAt: "2026-08-30T07:10:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.09, sensorTrustState: "LIVE",
      },
    ],
  },

  // ── ICE SEDAN — ON TRACK, TRANSFER ROBOT ────────────────────────────────
  {
    id: "V2055",
    variant: "ICE_SEDAN",
    currentStationId: "S15",
    currentStage: "General Assembly",
    status: "ON_TRACK",
    qualityRisk: 0.04,
    confidence: "HIGH",
    sensorCoverage: { livePercent: 97, inferredPercent: 3, unknownPercent: 0 },
    genealogy: [
      {
        stationId: "S15", stationName: "Body Transfer Robot",
        enteredAt: "2026-08-30T07:15:00Z",
        processStatus: "IN_PROGRESS", anomalyExposure: false,
        qualityRiskAfterStation: 0.04, sensorTrustState: "LIVE",
      },
    ],
  },
];

export const vehicleById = new Map<string, Vehicle>(
  mockVehicles.map((v) => [v.id, v]),
);
