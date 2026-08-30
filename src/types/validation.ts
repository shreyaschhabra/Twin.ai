/**
 * Model validation metric contracts for the Validation dashboard.
 *
 * These types represent the frontend data contract for displaying
 * ML model performance. Actual metrics are computed by the backend teams
 * building Flow ML and Quality ML.
 */

/** A point on a Precision-Recall curve. */
export type PRCurvePoint = {
  threshold: number;
  precision: number;
  recall: number;
};

/** A row in a confusion matrix (binary classification). */
export type ConfusionMatrix = {
  truePositives: number;
  falsePositives: number;
  trueNegatives: number;
  falseNegatives: number;
};

/** A calibration curve data point. */
export type CalibrationPoint = {
  /** Mean predicted probability in this bin. */
  meanPredicted: number;
  /** Fraction of actual positives in this bin. */
  fractionPositives: number;
};

/** A threshold-tradeoff data point — varies precision, recall, and alert volume with threshold. */
export type ThresholdTradeoff = {
  threshold: number;
  precision: number;
  recall: number;
  alertsPerShift: number;
};

/**
 * Flow model validation metrics.
 *
 * Covers bottleneck prediction quality.
 * medianWarningLeadTime — median minutes of warning before actual onset.
 */
export type FlowValidationMetrics = {
  precision: number;
  recall: number;
  falseAlertsPerShift: number;
  medianWarningLeadTime: number;
  /** Fraction of bottlenecks detected within a clinically useful warning window. */
  detectedWithinUsefulHorizon: number;
  /** Median absolute error in onset time prediction, in minutes. */
  onsetRangeError: number;

  confusionMatrix?: ConfusionMatrix;
  prCurve?: PRCurvePoint[];
  calibration?: CalibrationPoint[];
  thresholdTradeoff?: ThresholdTradeoff[];
};

/**
 * Quality model validation metrics.
 *
 * Covers binary defect-risk prediction quality.
 * averageEarlyDetectionDistance — average number of stations before end-of-line
 * at which the model correctly flags a vehicle.
 */
export type QualityValidationMetrics = {
  precision: number;
  recall: number;
  f1: number;
  prAuc: number;
  falseAlertsPer100Vehicles: number;
  averageEarlyDetectionDistance: number;

  confusionMatrix?: ConfusionMatrix;
  prCurve?: PRCurvePoint[];
  calibration?: CalibrationPoint[];
  thresholdTradeoff?: ThresholdTradeoff[];
};

/** Combined validation dashboard contract. */
export type ValidationMetrics = {
  asOf: string;
  flow: FlowValidationMetrics;
  quality: QualityValidationMetrics;
};

export type BaselineResult = {
  model: string;
  precision: number;
  recall: number;
  f1?: number;
  prAuc?: number;
  falseAlertsPerShift?: number;
  falseAlertsPer100Vehicles?: number;
  medianLeadTime?: number;
  isBest?: boolean;
};

export type ValidationCheck = {
  label: string;
  status: "EXPECTED" | "DEMO" | "PASSED" | "FAILED" | "NOT_RUN";
  description: string;
};

export type AnomalyValidationMetrics = {
  eventRecall: number;
  detectionDelaySec: number;
  falseAlertsPerShift: number;
  timeToDetectSec: number;
};

export type ReproducibilityMetadata = {
  modelVersion: string;
  simulationConfig: string;
  trainingShifts: string;
  validationShifts: string;
  testShifts: string;
  alertThreshold: number;
  randomSeed: number;
  timestamp: string;
};

