/**
 * Model Validation Page — /app/validation
 *
 * Provides a comprehensive dashboard showing model metrics (precision, recall,
 * confusion matrices, F1-scores, calibration plots, PR curves, and threshold trade-offs)
 * to evaluate Flow ML, Quality ML, and anomaly detection layers honestly on time-separated holdouts.
 */

import { Badge } from "@/components/ui/badge";
import {
  getValidationMetrics,
  getFlowBaselines,
  getQualityBaselines,
  getValidationProtocol,
  getAnomalyValidation,
  getEvaluationRunMetadata,
} from "@/features/services";
import { ValidationDashboardContainer } from "@/features/validation/components/validation-dashboard-container";

export const revalidate = 0;

export default async function ValidationPage() {
  // Fetch evaluation metrics through the feature service abstraction layer
  const [
    metrics,
    flowBaselines,
    qualityBaselines,
    protocolChecks,
    anomalyMetrics,
    runMetadata,
  ] = await Promise.all([
    getValidationMetrics(),
    getFlowBaselines(),
    getQualityBaselines(),
    getValidationProtocol(),
    getAnomalyValidation(),
    getEvaluationRunMetadata(),
  ]);

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-start justify-between gap-3 border-b pb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">
              Model Validation
            </h1>
            <Badge
              variant="outline"
              className="text-xs font-normal text-muted-foreground"
            >
              Demo Data
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Held-out evaluation of Flow and Quality intelligence, alert behavior and prediction reliability.
          </p>
        </div>
        <div className="text-right">
          <span className="text-[10px] uppercase font-mono bg-slate-100 text-slate-600 px-2 py-1 rounded border tracking-wider font-semibold">
            Representative validation layout
          </span>
        </div>
      </div>

      {/* ── VALIDATION DASHBOARD CONTAINER ── */}
      <ValidationDashboardContainer
        metrics={metrics}
        flowBaselines={flowBaselines}
        qualityBaselines={qualityBaselines}
        protocolChecks={protocolChecks}
        anomalyMetrics={anomalyMetrics}
        runMetadata={runMetadata}
      />
    </div>
  );
}
