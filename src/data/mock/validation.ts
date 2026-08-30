/**
 * MOCK DATA — Development only.
 * Model validation metrics (placeholder values for UI development).
 * Real metrics will come from the Flow ML and Quality ML teams.
 */

import type {
  ValidationMetrics,
  BaselineResult,
  ValidationCheck,
  AnomalyValidationMetrics,
  ReproducibilityMetadata,
} from "@/types/validation";

export const mockValidationMetrics: ValidationMetrics = {
  asOf: "2026-08-30T08:00:00Z",

  flow: {
    precision: 0.89,
    recall: 0.85,
    falseAlertsPerShift: 1.2,
    medianWarningLeadTime: 8.4,
    detectedWithinUsefulHorizon: 0.91,
    onsetRangeError: 1.8,

    confusionMatrix: {
      truePositives: 43,
      falsePositives: 5,
      trueNegatives: 210,
      falseNegatives: 8,
    },

    prCurve: [
      { threshold: 0.3, precision: 0.71, recall: 0.96 },
      { threshold: 0.5, precision: 0.82, recall: 0.90 },
      { threshold: 0.7, precision: 0.89, recall: 0.85 },
      { threshold: 0.85, precision: 0.94, recall: 0.72 },
      { threshold: 0.95, precision: 0.98, recall: 0.55 },
    ],

    thresholdTradeoff: [
      { threshold: 0.5, precision: 0.82, recall: 0.90, alertsPerShift: 3.1 },
      { threshold: 0.7, precision: 0.89, recall: 0.85, alertsPerShift: 2.0 },
      { threshold: 0.8, precision: 0.92, recall: 0.79, alertsPerShift: 1.5 },
      { threshold: 0.9, precision: 0.96, recall: 0.63, alertsPerShift: 0.9 },
    ],
  },

  quality: {
    precision: 0.86,
    recall: 0.82,
    f1: 0.84,
    prAuc: 0.91,
    falseAlertsPer100Vehicles: 3.2,
    averageEarlyDetectionDistance: 6.1,

    confusionMatrix: {
      truePositives: 39,
      falsePositives: 6,
      trueNegatives: 182,
      falseNegatives: 9,
    },

    prCurve: [
      { threshold: 0.3, precision: 0.68, recall: 0.95 },
      { threshold: 0.5, precision: 0.80, recall: 0.88 },
      { threshold: 0.65, precision: 0.86, recall: 0.82 },
      { threshold: 0.80, precision: 0.92, recall: 0.70 },
      { threshold: 0.90, precision: 0.96, recall: 0.52 },
    ],

    thresholdTradeoff: [
      { threshold: 0.5, precision: 0.80, recall: 0.88, alertsPerShift: 4.2 },
      { threshold: 0.65, precision: 0.86, recall: 0.82, alertsPerShift: 3.2 },
      { threshold: 0.75, precision: 0.90, recall: 0.74, alertsPerShift: 2.5 },
      { threshold: 0.85, precision: 0.94, recall: 0.61, alertsPerShift: 1.8 },
    ],
  },
};

export const mockFlowBaselines: BaselineResult[] = [
  { model: "Simple Rule Baseline", precision: 0.65, recall: 0.70, falseAlertsPerShift: 2.4, medianLeadTime: 4.2 },
  { model: "Logistic Regression", precision: 0.78, recall: 0.80, falseAlertsPerShift: 1.8, medianLeadTime: 6.1 },
  { model: "Random Forest", precision: 0.84, recall: 0.83, falseAlertsPerShift: 1.4, medianLeadTime: 7.8 },
  { model: "Gradient Boosting (XGBoost/LightGBM)", precision: 0.89, recall: 0.85, falseAlertsPerShift: 1.2, medianLeadTime: 8.4, isBest: true },
];

export const mockQualityBaselines: BaselineResult[] = [
  { model: "Logistic Regression", precision: 0.58, recall: 0.64, f1: 0.61, prAuc: 0.68, falseAlertsPer100Vehicles: 5.4 },
  { model: "Random Forest", precision: 0.74, recall: 0.76, f1: 0.75, prAuc: 0.82, falseAlertsPer100Vehicles: 4.1 },
  { model: "XGBoost (Demo Candidate)", precision: 0.86, recall: 0.82, f1: 0.84, prAuc: 0.91, falseAlertsPer100Vehicles: 3.2, isBest: true },
];

export const mockValidationProtocol: ValidationCheck[] = [
  {
    label: "Temporal shift separation",
    status: "DEMO",
    description: "Training (1–70), validation (71–85), and test (86–100) sets split in order of shifts to prevent future-data leaks.",
  },
  {
    label: "Future station measurement exclusion",
    status: "EXPECTED",
    description: "Model features only look at station sequences completed by the target assembly. Future measurements are strictly masked.",
  },
  {
    label: "Future buffer state exclusion",
    status: "EXPECTED",
    description: "Line flow metrics prevent looking ahead at downstream WIP changes past the assembly's current location.",
  },
  {
    label: "Hidden scenario labels exclusion",
    status: "EXPECTED",
    description: "Unseen synthetic dropout scenarios are kept completely separate from model training features.",
  },
  {
    label: "Future defect labels exclusion",
    status: "EXPECTED",
    description: "Downstream QC pass/fail outcome labels are excluded from vehicle-level prediction window evidence.",
  },
];

export const mockAnomalyValidation: AnomalyValidationMetrics = {
  eventRecall: 0.92,
  detectionDelaySec: 45,
  falseAlertsPerShift: 0.4,
  timeToDetectSec: 18,
};

export const mockEvaluationMetadata: ReproducibilityMetadata = {
  modelVersion: "flow-demo-v1 / quality-demo-v1",
  simulationConfig: "plant-layout-v3.2-synthetic",
  trainingShifts: "Shifts 1–70",
  validationShifts: "Shifts 71–85",
  testShifts: "Shifts 86–100",
  alertThreshold: 0.65,
  randomSeed: 4096,
  timestamp: "2026-08-30T08:00:00Z",
};

