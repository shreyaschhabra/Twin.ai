import {
  getStations,
  getVehicles,
  getFlowPredictions,
  getQualityPredictions,
  getAlerts,
  getExposureCohorts,
  getManagerAnalytics,
} from "@/features/services";

import { OperationalKpiCard } from "@/features/twin/components/operational-kpi-card";
import { LineHealthSummary } from "@/features/twin/components/line-health-summary";
import { BottleneckRiskCard } from "@/features/flow/components/bottleneck-risk-card";
import { HighRiskVehicles } from "@/features/quality/components/high-risk-vehicles";
import { QualitySummaryCard } from "@/features/quality/components/quality-summary-card";
import { SensorTrustSummary } from "@/features/trust/components/sensor-trust-summary";
import { ActiveAlertsList } from "@/features/alerts/components/active-alerts-list";
import { Badge } from "@/components/ui/badge";
import { Info } from "lucide-react";

export const revalidate = 0; // Disable server rendering cache for active updates

export default async function AppPage() {
  // 1. Fetch data through the feature service layer only
  const stations = await getStations();
  await getVehicles();
  const flowPreds = await getFlowPredictions();
  const qualityPreds = await getQualityPredictions();
  const alerts = await getAlerts();
  const cohorts = await getExposureCohorts();
  const analytics = await getManagerAnalytics();

  // 2. Perform calculations dynamically from mock services
  // Entry point throughput (S01 Body shop)
  const throughputVal = `${analytics.throughputTrend[0]?.vehiclesPerHour ?? 47} / hr`;
  
  // Active stations (anything not offline/DOWN)
  const activeStationsVal = `${stations.filter(s => s.state !== "DOWN").length} / ${stations.length}`;
  
  // High risk vehicles count (risk >= 0.50)
  const highRiskVehiclesCount = qualityPreds.filter(v => v.defectRisk >= 0.5).length;
  
  // Average sensor trust coverage count (LIVE + INFERRED stations)
  const liveOrInferredCount = stations.filter(s => s.sensorTrustState !== "UNKNOWN").length;
  const avgCoveragePct = `${Math.round((liveOrInferredCount / stations.length) * 100)}%`;

  // Get highest flow prediction (S13 is 99% blocked, S18 is 87% warning)
  // Let's filter to S18 warning as it is the primary developing warning scenario requested in PRD
  const highestFlowPred = flowPreds.find(f => f.stationId === "S18") || null;

  // Active Alerts count (unacknowledged or total)
  const activeAlertsCount = alerts.filter(a => !a.acknowledged).length;

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Supervisor Overview</h1>
          <p className="text-xs text-muted-foreground mt-1">
            Live operational intelligence and bottleneck tracking for the active production line.
          </p>
        </div>
        
        {/* Status indicators */}
        <div className="flex flex-wrap items-center gap-3 font-mono text-[10px]">
          <div className="flex items-center gap-1.5 px-2 py-1 rounded border bg-muted/20">
            <span className="text-muted-foreground uppercase">Mode:</span>
            <Badge variant="outline" className="h-4 border-amber-500/20 text-amber-700 dark:text-amber-400 bg-amber-50/20 font-bold uppercase tracking-wide text-[9px] px-1 rounded-sm">
              DEMO DATA
            </Badge>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded border bg-muted/20">
            <span className="text-muted-foreground uppercase">Heartbeat:</span>
            <span className="text-foreground font-semibold">LIVE</span>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded border bg-muted/20">
            <span className="text-muted-foreground uppercase">As of:</span>
            <span className="text-foreground font-semibold">10:55:00Z</span>
          </div>
        </div>
      </div>

      {/* ── TOP KPI SUMMARY GRID ── */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <OperationalKpiCard
          label="Line Throughput"
          value={throughputVal}
          contextText="Based on S01 intake rate"
          status="normal"
        />
        <OperationalKpiCard
          label="Active Stations"
          value={activeStationsVal}
          contextText="Cells online & running"
          status="normal"
        />
        <OperationalKpiCard
          label="Active Alerts"
          value={activeAlertsCount}
          contextText="Awaiting supervisor action"
          status={activeAlertsCount > 3 ? "critical" : "warning"}
        />
        <OperationalKpiCard
          label="High-Risk Vehicles"
          value={highRiskVehiclesCount}
          contextText="Holding inspection triggers"
          status={highRiskVehiclesCount > 0 ? "warning" : "normal"}
        />
        <OperationalKpiCard
          label="Average Sensor Coverage"
          value={avgCoveragePct}
          contextText="LIVE / INFERRED nodes"
          status="watch"
        />
      </div>

      {/* ── MAIN DASHBOARD DUAL COLUMN GRID ── */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Column 1: Primaries (Flow Warning + High Risk List) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Developing Bottleneck */}
          <BottleneckRiskCard prediction={highestFlowPred} />

          {/* High-Risk Vehicles */}
          <HighRiskVehicles predictions={qualityPreds} />
        </div>

        {/* Column 2: Secondaries (Quality Stats + Trust + Line states) */}
        <div className="space-y-6">
          {/* Quality Summary */}
          <QualitySummaryCard predictions={qualityPreds} cohorts={cohorts} />

          {/* Sensor Trust Summary */}
          <SensorTrustSummary stations={stations} />
        </div>
      </div>

      {/* ── THIRD COLUMN GRID: ALERTS & HEALTH ── */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Active Alerts */}
        <div className="lg:col-span-2">
          <ActiveAlertsList alerts={alerts} />
        </div>

        {/* Assembly Line Health counts */}
        <div>
          <LineHealthSummary stations={stations} />
        </div>
      </div>

      {/* ── BENIGN VARIATION FOOTER BANNER ── */}
      <div className="flex gap-2.5 p-3 border border-slate-500/10 bg-slate-500/5 text-slate-600 dark:text-slate-400 rounded-md text-xs select-none max-w-3xl">
        <Info className="h-4 w-4 shrink-0 mt-0.5 text-slate-400" />
        <div className="space-y-1">
          <p className="font-semibold font-mono text-[9px] uppercase tracking-wider">
            False-Alert Suppression Monitoring
          </p>
          <p className="font-sans text-muted-foreground leading-normal">
            Station <strong>S28 (Trim Line A)</strong> cycle-time variation observed (+7% variation) due to high ICE SUV vehicle mix (71% this shift). Occupancy remains stable within tolerances; prediction risk evaluated at 22% (WATCH). Alert suppression active.
          </p>
        </div>
      </div>
    </div>
  );
}
