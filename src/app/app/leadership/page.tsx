/**
 * Leadership Overview Page — /app/leadership
 *
 * Provides high-level operational opportunity metrics, sensor maturity distributions,
 * baseline comparisons, rollout roadmap stages, read-only sidecar integration plans,
 * and illustrative ROI business case reviews for Twin AI plant executives.
 */

import { Badge } from "@/components/ui/badge";
import {
  getLeadershipSummary,
  getRoiDefaults,
  getValidationMetrics,
} from "@/features/services";
import { LeadershipDashboardContainer } from "@/features/leadership/components/leadership-dashboard-container";

export const revalidate = 0;

export default async function LeadershipPage() {
  // Fetch leadership data, ROI defaults, and validation metrics through the services layer
  const [summary, roiDefaults, validationMetrics] = await Promise.all([
    getLeadershipSummary(),
    getRoiDefaults(),
    getValidationMetrics(),
  ]);

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-start justify-between gap-3 border-b pb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">
              Leadership Overview
            </h1>
            <Badge
              variant="outline"
              className="text-xs font-normal text-muted-foreground"
            >
              Demo Data Mode
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Business impact, operational opportunity and rollout readiness for Twin AI.
          </p>
        </div>
        <div className="text-right">
          <span className="text-[10px] uppercase font-mono bg-slate-100 text-slate-600 px-2 py-1 rounded border tracking-wider font-semibold">
            Illustrative business impact based on configurable assumptions
          </span>
        </div>
      </div>

      {/* ── LEADERSHIP DASHBOARD CONTAINER ── */}
      <LeadershipDashboardContainer
        summary={summary}
        roiDefaults={roiDefaults}
        validationMetrics={validationMetrics}
      />
    </div>
  );
}
