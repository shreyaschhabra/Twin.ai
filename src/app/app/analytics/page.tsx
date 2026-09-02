/**
 * Plant Analytics Page — /app/analytics
 *
 * Plant Manager analytics interface providing operational histories,
 * recurring bottlenecks, defect hotspot correlations, warning lead times,
 * false alarm trends, telemetry coverage gaps, and maintenance candidates.
 */

import { Badge } from "@/components/ui/badge";
import {
  getShiftAnalytics,
  getMaintenanceCandidates,
  getAnomalyPatterns,
} from "@/features/services";
import { AnalyticsDashboardContainer } from "@/features/analytics/components/analytics-dashboard-container";

export const revalidate = 0;

export default async function AnalyticsPage() {
  // Fetch initial analytics summaries via feature service layer
  const [shifts, candidates, patterns] = await Promise.all([
    getShiftAnalytics(),
    getMaintenanceCandidates(),
    getAnomalyPatterns(),
  ]);

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-start justify-between gap-3 border-b pb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">
              Plant Analytics
            </h1>
            <Badge
              variant="outline"
              className="text-xs font-normal text-muted-foreground"
            >
              Demo Data Mode
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Operational trends, recurring constraints and quality patterns across recent production shifts.
          </p>
        </div>
      </div>

      {/* ── INTERACTIVE ANALYTICS CONTAINER ── */}
      <AnalyticsDashboardContainer
        initialShifts={shifts}
        candidates={candidates}
        patterns={patterns}
      />
    </div>
  );
}
