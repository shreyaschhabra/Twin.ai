/**
 * Twin AI Feature Services
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ARCHITECTURE NOTE
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * All UI components must import data through these service functions.
 * Components MUST NOT import mock data directly.
 *
 * Current state (Phase 5):
 *   Services return static mock data.
 *
 * Future state (when backend API is live):
 *   Replace the mock import with an API call.
 *   No component changes required.
 *
 * Example migration:
 *
 *   // Before (mock):
 *   export async function getStations(): Promise<Station[]> {
 *     return mockStations;
 *   }
 *
 *   // After (live API):
 *   export async function getStations(): Promise<Station[]> {
 *     return apiClient<Station[]>("/stations");
 *   }
 *
 * The TWIN_API_URL env var controls the base URL (see src/lib/api/client.ts).
 * ═══════════════════════════════════════════════════════════════════════════
 */

import { appConfig } from "@/config/app";

// Mock data imports — only used when appConfig.useMockData is true
import { mockStations, stationById } from "@/data/mock/stations";
import { mockBuffers, bufferById } from "@/data/mock/buffers";
import { mockVehicles, vehicleById } from "@/data/mock/vehicles";
import { mockFlowPredictions, flowPredictionByStation } from "@/data/mock/flow";
import {
  mockQualityPredictions,
  qualityPredictionByVehicle,
  mockExposureCohorts,
  exposureCohortById,
} from "@/data/mock/quality";
import { mockAlerts } from "@/data/mock/alerts";
import {
  mockManagerAnalytics,
  mockShiftAnalytics,
  mockMaintenanceCandidates,
  mockAnomalyPatterns,
} from "@/data/mock/analytics";
import {
  mockValidationMetrics,
  mockFlowBaselines,
  mockQualityBaselines,
  mockValidationProtocol,
  mockAnomalyValidation,
  mockEvaluationMetadata,
} from "@/data/mock/validation";
import { mockRoiDefaults } from "@/data/mock/roi";
import { mockLeadershipSummary } from "@/data/mock/leadership";
import {
  mockDropoutScenario,
  mockS12DropoutHistory,
  mockTrustTransitions,
} from "@/data/mock/trust";

import type { Station, StationSensor, StationMaintenance, StationProcessTrend } from "@/types/station";
import type { Buffer } from "@/types/buffer";
import type { Vehicle, VehicleGenealogyEvent } from "@/types/vehicle";
import type { FlowPrediction } from "@/types/flow";
import type { ExposureCohort, QualityPrediction } from "@/types/quality";
import type { Alert } from "@/types/alert";
import type { ManagerAnalytics, ShiftAnalytics, MaintenanceCandidate, AnomalyPattern } from "@/types/analytics";
import type {
  ValidationMetrics,
  BaselineResult,
  ValidationCheck,
  AnomalyValidationMetrics,
  ReproducibilityMetadata,
} from "@/types/validation";
import type { RoiCalculation } from "@/types/roi";
import type { LeadershipSummary } from "@/types/leadership";
import type { SensorDropoutScenario, TrustTransitionEvent } from "@/types/trust";

// ─── STATIONS ─────────────────────────────────────────────────────────────────

/** Returns all 45 stations. */
export async function getStations(): Promise<Station[]> {
  if (appConfig.useMockData) return mockStations;
  // TODO: return apiClient<Station[]>("/stations");
  throw new Error("Live API not configured. Set TWIN_API_URL.");
}

/** Returns a single station by ID, or null if not found. */
export async function getStationById(id: string): Promise<Station | null> {
  if (appConfig.useMockData) return stationById.get(id) ?? null;
  // TODO: return apiClient<Station | null>(`/stations/${id}`);
  throw new Error("Live API not configured.");
}

// ─── BUFFERS ──────────────────────────────────────────────────────────────────

/** Returns all inter-station buffers. */
export async function getBuffers(): Promise<Buffer[]> {
  if (appConfig.useMockData) return mockBuffers;
  // TODO: return apiClient<Buffer[]>("/buffers");
  throw new Error("Live API not configured.");
}

/** Returns a buffer by ID. */
export async function getBufferById(id: string): Promise<Buffer | null> {
  if (appConfig.useMockData) return bufferById.get(id) ?? null;
  throw new Error("Live API not configured.");
}

// ─── VEHICLES ─────────────────────────────────────────────────────────────────

/** Returns all vehicles currently on the production line. */
export async function getVehicles(): Promise<Vehicle[]> {
  if (appConfig.useMockData) return mockVehicles;
  // TODO: return apiClient<Vehicle[]>("/vehicles");
  throw new Error("Live API not configured.");
}

/** Returns a single vehicle by ID. */
export async function getVehicleById(id: string): Promise<Vehicle | null> {
  if (appConfig.useMockData) return vehicleById.get(id) ?? null;
  // TODO: return apiClient<Vehicle | null>(`/vehicles/${id}`);
  throw new Error("Live API not configured.");
}

/** Returns the production genealogy for a vehicle. */
export async function getVehicleGenealogy(
  vehicleId: string,
): Promise<VehicleGenealogyEvent[]> {
  if (appConfig.useMockData) {
    return vehicleById.get(vehicleId)?.genealogy ?? [];
  }
  // TODO: return apiClient<VehicleGenealogyEvent[]>(`/vehicles/${vehicleId}/genealogy`);
  throw new Error("Live API not configured.");
}

// ─── FLOW PREDICTIONS ─────────────────────────────────────────────────────────

/** Returns all current flow (bottleneck) predictions. */
export async function getFlowPredictions(): Promise<FlowPrediction[]> {
  if (appConfig.useMockData) return mockFlowPredictions;
  // TODO: return apiClient<FlowPrediction[]>("/flow/predictions");
  throw new Error("Live API not configured.");
}

/** Returns the flow prediction for a specific station. */
export async function getFlowPredictionByStation(
  stationId: string,
): Promise<FlowPrediction | null> {
  if (appConfig.useMockData) {
    return flowPredictionByStation.get(stationId) ?? null;
  }
  // TODO: return apiClient<FlowPrediction | null>(`/flow/predictions/${stationId}`);
  throw new Error("Live API not configured.");
}

// ─── QUALITY PREDICTIONS ──────────────────────────────────────────────────────

/** Returns all current vehicle quality predictions. */
export async function getQualityPredictions(): Promise<QualityPrediction[]> {
  if (appConfig.useMockData) return mockQualityPredictions;
  // TODO: return apiClient<QualityPrediction[]>("/quality/predictions");
  throw new Error("Live API not configured.");
}

/** Returns the quality prediction for a specific vehicle. */
export async function getQualityPredictionByVehicle(
  vehicleId: string,
): Promise<QualityPrediction | null> {
  if (appConfig.useMockData) {
    return qualityPredictionByVehicle.get(vehicleId) ?? null;
  }
  // TODO: return apiClient<QualityPrediction | null>(`/quality/predictions/${vehicleId}`);
  throw new Error("Live API not configured.");
}

/** Returns all anomaly exposure cohorts. */
export async function getExposureCohorts(): Promise<ExposureCohort[]> {
  if (appConfig.useMockData) return mockExposureCohorts;
  // TODO: return apiClient<ExposureCohort[]>("/quality/cohorts");
  throw new Error("Live API not configured.");
}

/** Returns a single exposure cohort by ID. */
export async function getExposureCohortById(
  cohortId: string,
): Promise<ExposureCohort | null> {
  if (appConfig.useMockData) {
    return exposureCohortById.get(cohortId) ?? null;
  }
  throw new Error("Live API not configured.");
}

// ─── QUALITY INTELLIGENCE HELPERS ─────────────────────────────────────────────

/**
 * Derives top-level quality summary metrics for the Quality Intelligence page.
 */
export async function getQualitySummary(): Promise<{
  totalMonitored: number;
  highRiskCount: number;
  watchCount: number;
  activeCohortCount: number;
  highestRisk: number;
}> {
  if (!appConfig.useMockData) throw new Error("Live API not configured.");
  const predictions = mockQualityPredictions;
  const cohorts = mockExposureCohorts;

  return {
    totalMonitored: predictions.length,
    highRiskCount: predictions.filter((p) => p.status === "HIGH").length,
    watchCount: predictions.filter((p) => p.status === "WATCH").length,
    activeCohortCount: cohorts.length,
    highestRisk:
      predictions.length > 0
        ? Math.max(...predictions.map((p) => p.defectRisk))
        : 0,
  };
}

/**
 * Returns quality predictions at or above minimum risk, sorted by
 * defect risk descending.
 */
export async function getHighRiskVehiclePredictions(
  minRisk = 0,
): Promise<QualityPrediction[]> {
  if (!appConfig.useMockData) throw new Error("Live API not configured.");
  return [...mockQualityPredictions]
    .filter((p) => p.defectRisk >= minRisk)
    .sort((a, b) => b.defectRisk - a.defectRisk);
}

// ─── ALERTS ───────────────────────────────────────────────────────────────────

/** Returns all active alerts across flow, quality, sensor and anomaly kinds. */
export async function getAlerts(): Promise<Alert[]> {
  if (appConfig.useMockData) return mockAlerts;
  // TODO: return apiClient<Alert[]>("/alerts");
  throw new Error("Live API not configured.");
}

/** Derives top-level summary metrics for alerts dashboard. */
export async function getAlertSummary(): Promise<{
  activeCount: number;
  criticalCount: number;
  warningCount: number;
  watchCount: number;
  unreviewedCount: number;
}> {
  if (!appConfig.useMockData) throw new Error("Live API not configured.");
  const alerts = mockAlerts;

  return {
    activeCount: alerts.length,
    criticalCount: alerts.filter((a) => a.severity === "CRITICAL").length,
    warningCount: alerts.filter((a) => a.severity === "WARNING").length,
    watchCount: alerts.filter((a) => a.severity === "WATCH").length,
    unreviewedCount: alerts.filter((a) => !a.acknowledged).length,
  };
}

// ─── ANALYTICS ────────────────────────────────────────────────────────────────

/** Returns the Plant Manager analytics snapshot. */
export async function getManagerAnalytics(): Promise<ManagerAnalytics> {
  if (appConfig.useMockData) return mockManagerAnalytics;
  // TODO: return apiClient<ManagerAnalytics>("/analytics/manager");
  throw new Error("Live API not configured.");
}

/** Returns shift historical summary analytics. */
export async function getShiftAnalytics(): Promise<ShiftAnalytics[]> {
  if (appConfig.useMockData) return mockShiftAnalytics;
  throw new Error("Live API not configured.");
}

/** Returns the active maintenance candidates list. */
export async function getMaintenanceCandidates(): Promise<MaintenanceCandidate[]> {
  if (appConfig.useMockData) return mockMaintenanceCandidates;
  throw new Error("Live API not configured.");
}

/** Returns recurring anomaly patterns. */
export async function getAnomalyPatterns(): Promise<AnomalyPattern[]> {
  if (appConfig.useMockData) return mockAnomalyPatterns;
  throw new Error("Live API not configured.");
}

// ─── VALIDATION METRICS ───────────────────────────────────────────────────────

/** Returns Flow ML and Quality ML model validation metrics. */
export async function getValidationMetrics(): Promise<ValidationMetrics> {
  if (appConfig.useMockData) return mockValidationMetrics;
  // TODO: return apiClient<ValidationMetrics>("/validation/metrics");
  throw new Error("Live API not configured.");
}

/** Returns Flow model comparison baseline results. */
export async function getFlowBaselines(): Promise<BaselineResult[]> {
  if (appConfig.useMockData) return mockFlowBaselines;
  throw new Error("Live API not configured.");
}

/** Returns Quality model comparison baseline results. */
export async function getQualityBaselines(): Promise<BaselineResult[]> {
  if (appConfig.useMockData) return mockQualityBaselines;
  throw new Error("Live API not configured.");
}

/** Returns validation protocol leakage checks. */
export async function getValidationProtocol(): Promise<ValidationCheck[]> {
  if (appConfig.useMockData) return mockValidationProtocol;
  throw new Error("Live API not configured.");
}

/** Returns anomaly validation evaluation metrics. */
export async function getAnomalyValidation(): Promise<AnomalyValidationMetrics> {
  if (appConfig.useMockData) return mockAnomalyValidation;
  throw new Error("Live API not configured.");
}

/** Returns evaluation reproducibility run metadata. */
export async function getEvaluationRunMetadata(): Promise<ReproducibilityMetadata> {
  if (appConfig.useMockData) return mockEvaluationMetadata;
  throw new Error("Live API not configured.");
}

// ─── LEADERSHIP / ROI ─────────────────────────────────────────────────────────

export async function getLeadershipSummary(): Promise<LeadershipSummary> {
  if (appConfig.useMockData) return mockLeadershipSummary;
  throw new Error("Live API not configured.");
}

/** Returns the default ROI calculator state. */
export async function getRoiDefaults(): Promise<RoiCalculation> {
  if (appConfig.useMockData) return mockRoiDefaults;
  // TODO: return apiClient<RoiCalculation>("/roi/defaults");
  throw new Error("Live API not configured.");
}

// ─── TRUST / SENSOR ───────────────────────────────────────────────────────────

/** Returns the active sensor dropout scenario (S11). */
export async function getActiveDropoutScenario(): Promise<SensorDropoutScenario> {
  if (appConfig.useMockData) return mockDropoutScenario;
  throw new Error("Live API not configured.");
}

/** Returns S12's historical dropout scenario (for audit/history views). */
export async function getS12DropoutHistory(): Promise<SensorDropoutScenario> {
  if (appConfig.useMockData) return mockS12DropoutHistory;
  throw new Error("Live API not configured.");
}

/** Returns sensor trust transition events for the trust timeline. */
export async function getTrustTransitions(): Promise<TrustTransitionEvent[]> {
  if (appConfig.useMockData) return mockTrustTransitions;
  throw new Error("Live API not configured.");
}

// ─── STATION DETAIL EXTENSIONS ───────────────────────────────────────────────

/** Returns sensor telemetry channels for a given station cell. */
export async function getStationSensors(stationId: string): Promise<StationSensor[]> {
  if (!appConfig.useMockData) {
    throw new Error("Live API not configured.");
  }
  
  if (stationId === "S18") {
    return [
      { id: "S18-VIB", name: "Spindle Vibration", value: 2.7, unit: "mm/s", trustState: "LIVE", status: "NORMAL" },
      { id: "S18-TMP", name: "Clamping Temperature", value: 41.2, unit: "°C", trustState: "LIVE", status: "NORMAL" },
      { id: "S18-TRQ", name: "Transducer Torque Feedback", value: 58.4, unit: "Nm", trustState: "LIVE", status: "DEVIATING" },
    ];
  }

  if (stationId === "S12") {
    return [
      { id: "S12-CUR", name: "Axis 3 Joint Current", value: 12.4, unit: "A", trustState: "INFERRED", status: "NORMAL" },
      { id: "S12-PRS", name: "Hydraulic System Pressure", value: 180, unit: "bar", trustState: "INFERRED", status: "NORMAL" },
      { id: "S12-TMP", name: "Servo Motor Temperature", value: 55.8, unit: "°C", trustState: "INFERRED", status: "NORMAL" },
    ];
  }

  if (stationId === "S40") {
    return [
      { id: "S40-TMP", name: "Manifold Intake Temperature", unit: "°C", trustState: "UNKNOWN", status: "UNAVAILABLE" },
      { id: "S40-PRS", name: "Refrigerant Charge Pressure", unit: "bar", trustState: "UNKNOWN", status: "UNAVAILABLE" },
    ];
  }

  // Fallback default set for other stations
  return [
    { id: `${stationId}-VIB`, name: "Vibration Signal", value: 1.2, unit: "mm/s", trustState: "LIVE", status: "NORMAL" },
    { id: `${stationId}-CUR`, name: "Operating Current", value: 8.5, unit: "A", trustState: "LIVE", status: "NORMAL" },
  ];
}

/** Returns maintenance context for a given station. */
export async function getStationMaintenance(stationId: string): Promise<StationMaintenance | null> {
  if (!appConfig.useMockData) {
    throw new Error("Live API not configured.");
  }
  
  if (stationId === "S18") {
    return { hoursSinceMaintenance: 38, toolAgePercent: 12, recentMinorStopsCount: 3, needsAttention: false };
  }
  if (stationId === "S12") {
    return { hoursSinceMaintenance: 142, toolAgePercent: 74, recentMinorStopsCount: 1, needsAttention: false };
  }
  if (stationId === "S13") {
    return { hoursSinceMaintenance: 210, toolAgePercent: 85, recentMinorStopsCount: 0, needsAttention: true };
  }

  // Deterministic values based on ID hash
  const hash = stationId.charCodeAt(1) || 0;
  return {
    hoursSinceMaintenance: (hash * 3) % 200,
    toolAgePercent: (hash * 7) % 95,
    recentMinorStopsCount: hash % 4,
    needsAttention: (hash % 10) === 0,
  };
}

/** Returns historical cycle-time trend data. */
export async function getStationTrend(stationId: string): Promise<StationProcessTrend | null> {
  if (!appConfig.useMockData) {
    throw new Error("Live API not configured.");
  }

  if (stationId === "S18") {
    return { cycleTimeHistory: [52, 53, 54, 56, 58, 61] };
  }
  if (stationId === "S12") {
    return { cycleTimeHistory: [90, 92, 95, 99, 102, 104] };
  }

  const station = mockStations.find(s => s.id === stationId);
  const baseline = station?.baselineCycleTime ?? 50;

  return {
    cycleTimeHistory: [
      baseline - 2,
      baseline - 1,
      baseline,
      baseline + 1,
      baseline - 1,
      station?.currentCycleTime ?? baseline,
    ],
  };
}

/** Queries buffers to locate upstream and downstream buffers associated with the station. */
export async function getStationBuffers(stationId: string): Promise<{ upstream: Buffer | null; downstream: Buffer | null }> {
  if (!appConfig.useMockData) {
    throw new Error("Live API not configured.");
  }

  const upstream = mockBuffers.find(b => b.downstreamStationId === stationId) ?? null;
  const downstream = mockBuffers.find(b => b.upstreamStationId === stationId) ?? null;

  return { upstream, downstream };
}

/** Returns the active flow prediction for the station. */
export async function getStationFlowPrediction(stationId: string): Promise<FlowPrediction | null> {
  if (!appConfig.useMockData) {
    throw new Error("Live API not configured.");
  }

  return mockFlowPredictions.find(fp => fp.stationId === stationId) ?? null;
}

/** Returns the vehicle currently at the station. */
export async function getVehiclesAtStation(stationId: string): Promise<Vehicle | null> {
  if (!appConfig.useMockData) {
    throw new Error("Live API not configured.");
  }

  return mockVehicles.find(v => v.currentStationId === stationId) ?? null;
}

/** Returns active Alerts associated with the station. */
export async function getStationAlerts(stationId: string): Promise<Alert[]> {
  if (!appConfig.useMockData) {
    throw new Error("Live API not configured.");
  }

  return mockAlerts.filter(a => a.stationId === stationId);
}

// ─── FLOW INTELLIGENCE HELPERS ────────────────────────────────────────────────

/**
 * Derives a top-level summary of current flow prediction state.
 * Used by the Flow Intelligence page summary bar.
 */
export async function getFlowSummary(): Promise<{
  totalMonitored: number;
  elevatedCount: number;
  criticalHighCount: number;
  medianOnsetMin: number | null;
  buffersNearCapacity: number;
}> {
  if (!appConfig.useMockData) throw new Error("Live API not configured.");

  const predictions = mockFlowPredictions;
  const buffers = mockBuffers;

  const elevated = predictions.filter((p) => p.bottleneckRisk >= 0.2);
  const criticalHigh = predictions.filter((p) => p.bottleneckRisk >= 0.7);

  const onsets = elevated
    .filter((p) => p.expectedOnsetMin > 0)
    .map((p) => Math.round((p.expectedOnsetMin + p.expectedOnsetMax) / 2))
    .sort((a, b) => a - b);

  const medianOnset =
    onsets.length > 0 ? onsets[Math.floor(onsets.length / 2)] : null;

  const buffersNearCapacity = buffers.filter(
    (b) => b.occupancyRatio >= 0.75,
  ).length;

  return {
    totalMonitored: predictions.length,
    elevatedCount: elevated.length,
    criticalHighCount: criticalHigh.length,
    medianOnsetMin: medianOnset,
    buffersNearCapacity,
  };
}

/**
 * Returns flow predictions at or above the given risk threshold,
 * sorted by bottleneck risk descending.
 */
export async function getHighRiskFlowPredictions(
  minRisk = 0.2,
): Promise<FlowPrediction[]> {
  if (!appConfig.useMockData) throw new Error("Live API not configured.");

  return [...mockFlowPredictions]
    .filter((p) => p.bottleneckRisk >= minRisk)
    .sort((a, b) => b.bottleneckRisk - a.bottleneckRisk);
}

/**
 * Returns buffers adjacent to stations with elevated flow risk (WATCH+),
 * sorted by occupancy ratio descending.
 */
export async function getRelevantBuffersForFlow(): Promise<Buffer[]> {
  if (!appConfig.useMockData) throw new Error("Live API not configured.");

  const elevatedStationIds = new Set(
    mockFlowPredictions
      .filter((p) => p.bottleneckRisk >= 0.2)
      .map((p) => p.stationId),
  );

  const relevant = mockBuffers.filter(
    (b) =>
      elevatedStationIds.has(b.downstreamStationId) ||
      elevatedStationIds.has(b.upstreamStationId),
  );

  return [...relevant].sort((a, b) => b.occupancyRatio - a.occupancyRatio);
}
