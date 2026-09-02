/**
 * Leadership / Business Impact contracts for the Leadership Overview.
 *
 * Pre-computed high-level statistics representing business value opportunity,
 * rollout readiness, and sensor retrofit recommendations.
 */

export type ExecutiveKPIs = {
  throughputOpportunity: string;
  downtimeOpportunity: string;
  qualityOpportunity: string;
  sensorReadiness: number; // e.g. 78%
  predictionReadiness: string; // e.g. "Validated Demo"
  rolloutReadiness: string; // e.g. "Pilot-ready"
};

export type IntelligenceReadiness = {
  flowMaturity: "READY" | "PILOT_READY" | "IN_PROGRESS" | "PENDING";
  qualityMaturity: "READY" | "PILOT_READY" | "IN_PROGRESS" | "PENDING";
  anomalyMaturity: "READY" | "PILOT_READY" | "IN_PROGRESS" | "PENDING";
  sensorMaturity: "READY" | "PILOT_READY" | "IN_PROGRESS" | "PENDING";
  plantIntegration: "READY" | "PILOT_READY" | "IN_PROGRESS" | "PENDING";
};

export type SensorRetrofitPriority = {
  stationId: string;
  processName: string;
  maturity: "POOR" | "PARTIAL" | "RICH";
  unknownCoverage: number; // e.g. 0.27 for 27%
  inferredDependence: number; // e.g. 0.42 for 42%
  confidenceImpact: "HIGH" | "MODERATE" | "LOW";
  action: string;
};

export type RolloutStage = {
  stageName: string;
  status: "COMPLETE" | "IN_PROGRESS" | "PLANNED" | "NEXT" | "FUTURE";
  description: string;
};

export type ScaleReadiness = {
  sharedContracts: "READY" | "IN_PROGRESS" | "REQUIRED" | "PENDING";
  stationTemplates: "READY" | "IN_PROGRESS" | "REQUIRED" | "PENDING";
  plantMapping: "READY" | "IN_PROGRESS" | "REQUIRED" | "PENDING";
  modelRecalibration: "READY" | "IN_PROGRESS" | "REQUIRED" | "PENDING";
  cybersecurityReview: "READY" | "IN_PROGRESS" | "REQUIRED" | "PENDING";
};

export type LeadershipSummary = {
  asOf: string;
  kpis: ExecutiveKPIs;
  readiness: IntelligenceReadiness;
  retrofitPriorities: SensorRetrofitPriority[];
  stages: RolloutStage[];
  scale: ScaleReadiness;
};
