import type { ConfidenceLevel, EvidenceItem } from "./common";

/**
 * Flow prediction — bottleneck risk at a specific station.
 *
 * bottleneckRisk and confidence are always separate:
 * Example: bottleneckRisk = 0.87, confidence = "MEDIUM" is valid and meaningful.
 * It means the model is moderately confident there is a high-risk bottleneck forming.
 */
export type FlowPredictionStatus = "CLEAR" | "WATCH" | "WARNING" | "CRITICAL";

export type FlowPrediction = {
  stationId: string;
  stationName: string;

  /** Bottleneck probability, 0–1. */
  bottleneckRisk: number;

  /**
   * Predicted onset window — minutes from now.
   * expectedOnsetMin <= expectedOnsetMax.
   */
  expectedOnsetMin: number;
  expectedOnsetMax: number;

  /** Confidence in the bottleneck prediction itself. */
  confidence: ConfidenceLevel;

  status: FlowPredictionStatus;

  /** Structured evidence list driving the prediction. */
  evidence: EvidenceItem[];

  /**
   * Stations upstream that will be starved if this bottleneck forms.
   * Ordered from closest to furthest upstream.
   */
  affectedUpstreamStations: string[];

  /**
   * Stations downstream that will be blocked if this bottleneck forms.
   */
  affectedDownstreamStations: string[];
};
