import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Activity, Car, Bell } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  getStationById,
  getStationSensors,
  getStationMaintenance,
  getStationTrend,
  getStationBuffers,
  getStationFlowPrediction,
  getVehiclesAtStation,
  getStationAlerts,
} from "@/features/services";

import { StationOperationalSummary } from "@/features/stations/components/station-operational-summary";
import { StationSensorList } from "@/features/stations/components/station-sensor-list";
import { StationMaintenanceCard } from "@/features/stations/components/station-maintenance-card";
import { CycleTimeTrend } from "@/features/stations/components/cycle-time-trend";
import { BufferConditionCard } from "@/features/twin/components/buffer-condition-card";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import { SensorTrustBadge } from "@/features/trust/components/sensor-trust-badge";
import { cn } from "@/lib/utils";

export const revalidate = 0; // Disable server rendering cache for active updates

interface StationDetailPageProps {
  params: Promise<{ stationId: string }>;
}

export default async function StationDetailPage({ params }: StationDetailPageProps) {
  const { stationId } = await params;

  // Fetch the primary station details
  const station = await getStationById(stationId);

  // If station is not found, render the customized 404 page
  if (!station) {
    notFound();
  }

  // Fetch all related details through the service layer
  const sensors = await getStationSensors(stationId);
  const maintenance = await getStationMaintenance(stationId);
  const trend = await getStationTrend(stationId);
  const { upstream, downstream } = await getStationBuffers(stationId);
  const flowPrediction = await getStationFlowPrediction(stationId);
  const activeVehicle = await getVehiclesAtStation(stationId);
  const alerts = await getStationAlerts(stationId);

  const isHighRiskFlow = flowPrediction && flowPrediction.bottleneckRisk >= 0.50;

  return (
    <div className="space-y-6">
      {/* ── HEADER NAVIGATION ── */}
      <div className="space-y-2 border-b pb-4">
        <Link
          href="/app/live-twin"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground font-semibold transition-colors"
        >
          <ArrowLeft className="h-3 w-3" />
          Back to Live Twin Topology
        </Link>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              {station.id} — {station.name}
            </h1>
            <p className="text-xs text-muted-foreground mt-1">
              {station.operation} · <span className="font-mono text-[10px] uppercase font-semibold">Zone: {station.type}</span>
            </p>
          </div>
          {/* Badge groups */}
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={cn(
                "font-mono text-[9px] px-2 py-0.5 uppercase tracking-wide shrink-0",
                station.state === "PROCESSING" && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20",
                station.state === "IDLE" && "bg-slate-500/10 text-slate-700 dark:text-slate-400 border-slate-500/20",
                station.state === "BLOCKED" && "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20",
                station.state === "STARVED" && "bg-orange-500/10 text-orange-700 dark:text-orange-400 border-orange-500/20",
                station.state === "DOWN" && "bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20"
              )}
            >
              {station.state}
            </Badge>
            <SensorTrustBadge trust={station.sensorTrustState} className="shrink-0" />
            <ConfidenceBadge confidence={station.confidence} className="shrink-0 text-[8px]" />
          </div>
        </div>
      </div>

      {/* ── OPERATIONAL STATUS READOUTS ── */}
      <StationOperationalSummary station={station} vehicle={activeVehicle} />

      {/* ── DETAIL GRIDS ── */}
      <div className="grid gap-6 lg:grid-cols-2">
        
        {/* LEFT COLUMN: Flow, Buffers, Trends */}
        <div className="space-y-6">
          
          {/* Flow Prediction Card */}
          <Card className={cn("border bg-card text-card-foreground shadow-sm", isHighRiskFlow && "border-orange-500/20 bg-orange-500/5")}>
            <CardHeader className="pb-4">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Activity className="h-4 w-4 text-slate-500 shrink-0" />
                Flow Intelligence
              </CardTitle>
              <CardDescription className="text-xs text-muted-foreground">
                Congestion forecast and expected operational buffer depletion bounds.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              {flowPrediction ? (
                <div className="space-y-4">
                  <div className="grid gap-4 sm:grid-cols-2 font-mono text-xs">
                    <div className="p-3 border rounded bg-background/50 flex flex-col justify-between">
                      <span className="text-[10px] text-muted-foreground font-sans uppercase font-bold">
                        Bottleneck Onset Risk
                      </span>
                      <span className={cn(
                        "text-lg font-bold mt-1.5",
                        isHighRiskFlow ? "text-rose-500" : "text-foreground"
                      )}>
                        {Math.round(flowPrediction.bottleneckRisk * 100)}% Risk
                      </span>
                    </div>

                    <div className="p-3 border rounded bg-background/50 flex flex-col justify-between">
                      <span className="text-[10px] text-muted-foreground font-sans uppercase font-bold">
                        Expected Impact
                      </span>
                      <span className="text-lg font-bold mt-1.5 text-foreground">
                        {flowPrediction.expectedOnsetMin === flowPrediction.expectedOnsetMax
                          ? `${flowPrediction.expectedOnsetMin} min`
                          : `${flowPrediction.expectedOnsetMin}–${flowPrediction.expectedOnsetMax} min`}
                      </span>
                    </div>
                  </div>

                  {/* Signals Evidence list */}
                  <div className="space-y-2 border-t pt-4">
                    <h6 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider font-mono">
                      Observed Signals Evidence
                    </h6>
                    <ul className="grid gap-2 sm:grid-cols-2 font-mono text-xs">
                      {flowPrediction.evidence.map((item, idx) => (
                        <li key={idx} className="flex justify-between p-2 border rounded bg-muted/10">
                          <span className="text-muted-foreground truncate mr-2">{item.label}</span>
                          <span className={cn(
                            "font-bold",
                            item.direction === "negative" && "text-rose-500",
                            item.direction === "positive" && "text-emerald-500",
                            item.direction === "neutral" && "text-muted-foreground"
                          )}>
                            {item.value}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="p-4 border border-dashed rounded text-center text-xs text-muted-foreground font-mono bg-muted/5">
                  No developing bottleneck detected. Current operating conditions are not producing a significant predicted flow constraint.
                </div>
              )}
            </CardContent>
          </Card>

          {/* Buffer Conditions widget */}
          <BufferConditionCard upstream={upstream} downstream={downstream} />

          {/* Cycle Time Trend Sparkline */}
          <CycleTimeTrend trend={trend} baseline={station.baselineCycleTime} />
        </div>

        {/* RIGHT COLUMN: Telemetry, Vehicles, Maintenance, Alerts */}
        <div className="space-y-6">
          
          {/* Telemetry list */}
          <StationSensorList sensors={sensors} maturity={station.sensorMaturity} />

          {/* Active vehicle at station details */}
          <Card className="border bg-card text-card-foreground shadow-sm">
            <CardHeader className="pb-4">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Car className="h-4 w-4 text-slate-500 shrink-0" />
                Current Active Vehicle
              </CardTitle>
              <CardDescription className="text-xs text-muted-foreground">
                Telemetry details for the active assembly locked in the cell.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              {activeVehicle ? (
                <div className="space-y-4 font-mono text-xs">
                  <div className="grid gap-4 sm:grid-cols-3">
                    <div className="p-3 border rounded bg-background/50 flex flex-col justify-between">
                      <span className="text-[10px] text-muted-foreground font-sans uppercase font-bold">
                        Vehicle ID
                      </span>
                      <span className="text-base font-bold text-foreground mt-1">
                        {activeVehicle.id}
                      </span>
                    </div>

                    <div className="p-3 border rounded bg-background/50 flex flex-col justify-between">
                      <span className="text-[10px] text-muted-foreground font-sans uppercase font-bold">
                        Variant
                      </span>
                      <span className="text-base font-bold text-foreground mt-1 uppercase">
                        {activeVehicle.variant.replace("ICE_", "")}
                      </span>
                    </div>

                    <div className="p-3 border rounded bg-background/50 flex flex-col justify-between">
                      <span className="text-[10px] text-muted-foreground font-sans uppercase font-bold">
                        Defect Risk
                      </span>
                      <span className={cn(
                        "text-base font-bold mt-1",
                        activeVehicle.qualityRisk >= 0.50 ? "text-rose-500" : "text-foreground"
                      )}>
                        {Math.round(activeVehicle.qualityRisk * 100)}%
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-t pt-4">
                    <span className="text-muted-foreground font-sans">Validation Confidence:</span>
                    <ConfidenceBadge confidence={activeVehicle.confidence} className="text-[8px]" />
                  </div>

                  <Link
                    href="/app/vehicles"
                    className="inline-flex h-8 w-full items-center justify-center rounded-md border bg-background px-3 text-xs font-semibold text-foreground hover:bg-accent transition-colors mt-2 font-sans"
                  >
                    View Vehicles Feed
                  </Link>
                </div>
              ) : (
                <div className="p-4 border border-dashed rounded text-center text-xs text-muted-foreground font-mono bg-muted/5">
                  No vehicle currently docked at this station.
                </div>
              )}
            </CardContent>
          </Card>

          {/* Maintenance context stats */}
          <StationMaintenanceCard maintenance={maintenance} />

          {/* Cell Alerts Log */}
          <Card className="border bg-card text-card-foreground shadow-sm">
            <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4">
              <div>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Bell className="h-4 w-4 text-slate-500 shrink-0" />
                  Active Cell Alerts
                </CardTitle>
                <CardDescription className="text-xs text-muted-foreground">
                  Unresolved alerts matching this station cell.
                </CardDescription>
              </div>
              <Link
                href="/app/alerts"
                className="inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-3 text-xs font-semibold text-foreground hover:bg-accent transition-colors self-start sm:self-center font-sans"
              >
                View All Alerts
              </Link>
            </CardHeader>
            <CardContent className="p-0">
              <ul className="divide-y border-t select-none">
                {alerts.length === 0 ? (
                  <li className="p-6 text-center text-xs text-muted-foreground font-mono">
                    No active operational alerts for this station.
                  </li>
                ) : (
                  alerts.map((alert) => (
                    <li key={alert.id} className="p-4 flex items-start justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 font-mono">
                          <Badge variant="outline" className={cn(
                            "text-[8px] py-0 px-1 font-bold",
                            alert.severity === "CRITICAL" && "border-rose-500/20 text-rose-700 bg-rose-500/5 dark:text-rose-400",
                            alert.severity === "WARNING" && "border-orange-500/20 text-orange-700 bg-orange-500/5 dark:text-orange-400",
                            alert.severity === "WATCH" && "border-amber-500/20 text-amber-700 bg-amber-500/5 dark:text-amber-400",
                            alert.severity === "INFO" && "border-slate-500/20 text-slate-700 bg-slate-500/5 dark:text-slate-400"
                          )}>
                            {alert.severity}
                          </Badge>
                          <span className="text-[10px] text-muted-foreground uppercase">{alert.kind}</span>
                        </div>
                        <p className="text-xs font-bold text-foreground">
                          {alert.title}
                        </p>
                        <p className="text-[10px] text-muted-foreground font-sans leading-normal">
                          {alert.description}
                        </p>
                      </div>
                    </li>
                  ))
                )}
              </ul>
            </CardContent>
          </Card>
        </div>

      </div>
    </div>
  );
}
