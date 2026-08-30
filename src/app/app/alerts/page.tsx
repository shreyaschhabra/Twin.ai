/**
 * Unified Alerts Center Page — /app/alerts
 *
 * Visual dashboard presenting operational alerts across flow, quality,
 * sensor trust, and process anomaly categories.
 *
 * Architecture:
 *   page (server) → service layer → mock data
 *   Client-side interactive state managed by AlertsDashboardContainer
 */

import { getAlerts, getAlertSummary } from "@/features/services";
import { Badge } from "@/components/ui/badge";
import { AlertsDashboardContainer } from "@/features/alerts/components/alerts-dashboard-container";

export const revalidate = 0;

export default async function AlertsPage() {
  // Fetch initial alerts and summary statistics through service layer only
  const [alerts, summary] = await Promise.all([
    getAlerts(),
    getAlertSummary(),
  ]);

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-start justify-between gap-3 border-b pb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">
              Alerts
            </h1>
            <Badge
              variant="outline"
              className="text-xs font-normal text-muted-foreground"
            >
              Demo Data Mode
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Prioritized operational warnings across flow, quality, process anomalies, and sensor trust.
          </p>
        </div>
      </div>

      {/* ── DASHBOARD CLIENT CONTAINER ── */}
      <AlertsDashboardContainer
        initialAlerts={alerts}
        summary={summary}
      />
    </div>
  );
}
