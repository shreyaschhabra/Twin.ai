/**
 * ROI Calculator Page — /app/roi
 *
 * Interactive financial business case calculator allowing executives to estimate
 * potential downtime benefit, rework savings, sensor retrofits, and steady-state ROI
 * based on configurable plant volume and cost assumptions.
 */

import { Badge } from "@/components/ui/badge";
import { getRoiDefaults } from "@/features/services";
import { RoiDashboardContainer } from "@/features/roi/components/roi-dashboard-container";

export const revalidate = 0;

export default async function RoiPage() {
  // Fetch default ROI configuration parameters through the service layer
  const defaultCalculation = await getRoiDefaults();

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-start justify-between gap-3 border-b pb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">
              ROI Calculator
            </h1>
            <Badge
              variant="outline"
              className="text-xs font-normal text-muted-foreground"
            >
              Demo Data Mode
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Estimate the potential business impact of Twin AI using configurable plant assumptions.
          </p>
        </div>
        <div className="text-right">
          <span className="text-[10px] uppercase font-mono bg-slate-100 text-slate-600 px-2 py-1 rounded border tracking-wider font-semibold">
            Illustrative Scenario Estimate
          </span>
        </div>
      </div>

      {/* ── INTERACTIVE CALCULATOR CONTAINER ── */}
      <RoiDashboardContainer defaultCalculation={defaultCalculation} />
    </div>
  );
}
