/**
 * MOCK DATA — Development only.
 * Mock leadership dashboard summaries and rollout roadmap configurations.
 */

import type { LeadershipSummary } from "@/types/leadership";

export const mockLeadershipSummary: LeadershipSummary = {
  asOf: "2026-08-30T10:55:00Z",

  kpis: {
    throughputOpportunity: "Moderate-High",
    downtimeOpportunity: "Moderate",
    qualityOpportunity: "High",
    sensorReadiness: 78,
    predictionReadiness: "Validated Demo",
    rolloutReadiness: "Pilot-ready",
  },

  readiness: {
    flowMaturity: "PILOT_READY",
    qualityMaturity: "PILOT_READY",
    anomalyMaturity: "IN_PROGRESS",
    sensorMaturity: "READY",
    plantIntegration: "PENDING",
  },

  retrofitPriorities: [
    {
      stationId: "S34",
      processName: "Battery Mounting Robot",
      maturity: "POOR",
      unknownCoverage: 0.27,
      inferredDependence: 0.42,
      confidenceImpact: "HIGH",
      action: "Evaluate retrofit",
    },
    {
      stationId: "S39",
      processName: "Glass Sealant Applicator",
      maturity: "PARTIAL",
      unknownCoverage: 0.08,
      inferredDependence: 0.41,
      confidenceImpact: "MODERATE",
      action: "Consider additional instrumentation",
    },
  ],

  stages: [
    {
      stageName: "Prototype",
      status: "COMPLETE",
      description: "Initial synthetic line simulator verification and core algorithm definition.",
    },
    {
      stageName: "Offline Validation",
      status: "COMPLETE",
      description: "Held-out temporal evaluation of Flow/Quality models using shift history data.",
    },
    {
      stageName: "Read-only Sidecar Integration",
      status: "PLANNED",
      description: "Real-time read-only shadow deployment consuming factory stream without output controls.",
    },
    {
      stageName: "Pilot Line",
      status: "NEXT",
      description: "Active deployment on single production line with operator feedback loop.",
    },
    {
      stageName: "Multi-Line Scale",
      status: "FUTURE",
      description: "Rollout across remaining plant lines and shared telemetry calibration.",
    },
  ],

  scale: {
    sharedContracts: "READY",
    stationTemplates: "READY",
    plantMapping: "REQUIRED",
    modelRecalibration: "REQUIRED",
    cybersecurityReview: "REQUIRED",
  },
};
