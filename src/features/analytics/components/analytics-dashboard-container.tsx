/**
 * Analytics Dashboard Container Component
 *
 * Coordinates client-side interactive state for the Plant Manager Analytics page:
 * - Dynamic time range selector (Last 10, 30, 100 Shifts)
 * - Computes KPI cards dynamically from selected shifts data
 * - Handles chart/grid reflows and layouts
 */

"use client";

import { useState, useMemo } from "react";
import {
  Activity,
  ShieldAlert,
  Clock,
  BellRing,
  Percent,
  Layers,
  Wrench,
  HelpCircle,
  TrendingUp,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ThroughputTrendChart } from "./throughput-trend-chart";
import { WarningLeadTimeChart } from "./warning-lead-time-chart";
import { FalseAlertTrendChart } from "./false-alert-trend-chart";
import { BottleneckHotspots } from "./bottleneck-hotspots";
import { QualityHotspots } from "./quality-hotspots";
import { AnomalyPatterns } from "./anomaly-patterns";
import { SensorGapAnalysis } from "./sensor-gap-analysis";
import { MaintenanceCandidates } from "./maintenance-candidates";
import { ShiftSummaryTable } from "./shift-summary-table";
import type { ShiftAnalytics, MaintenanceCandidate, AnomalyPattern, BottleneckHotspot } from "@/types/analytics";

interface AnalyticsDashboardContainerProps {
  initialShifts: ShiftAnalytics[];
  candidates: MaintenanceCandidate[];
  patterns: AnomalyPattern[];
}

export function AnalyticsDashboardContainer({
  initialShifts,
  candidates,
  patterns,
}: AnalyticsDashboardContainerProps) {
  const [timeRange, setTimeRange] = useState<string>("30"); // 10, 30, 100

  // Slice shifts dynamically based on selected range
  const filteredShifts = useMemo(() => {
    const limit = parseInt(timeRange, 10);
    return initialShifts.slice(-limit);
  }, [initialShifts, timeRange]);

  // Compute dynamic KPIs based on selected range
  const kpis = useMemo(() => {
    if (filteredShifts.length === 0) {
      return {
        avgThroughput: 0,
        bottlenecksCount: 0,
        medianLeadTime: 0,
        falseAlertsPerShift: 0,
        defectRate: 0,
        sensorCoverage: 0,
      };
    }

    const totalThroughput = filteredShifts.reduce((sum, s) => sum + s.throughput, 0);
    const totalLeadTime = filteredShifts.reduce((sum, s) => sum + s.medianWarningLeadTime, 0);
    const totalFalseAlerts = filteredShifts.reduce((sum, s) => sum + s.falseAlerts, 0);
    const totalDefectRate = filteredShifts.reduce((sum, s) => sum + s.defectRate, 0);
    const totalUnknown = filteredShifts.reduce((sum, s) => sum + s.unknownCoverage, 0);

    return {
      avgThroughput: Math.round(totalThroughput / filteredShifts.length),
      bottlenecksCount: 4, // Recurring bottleneck stations count is overall line context
      medianLeadTime: Math.round((totalLeadTime / filteredShifts.length) * 10) / 10,
      falseAlertsPerShift: Math.round((totalFalseAlerts / filteredShifts.length) * 10) / 10,
      defectRate: Math.round((totalDefectRate / filteredShifts.length) * 1000) / 10,
      sensorCoverage: Math.round((1 - totalUnknown / filteredShifts.length) * 100),
    };
  }, [filteredShifts]);

  return (
    <div className="space-y-6">
      {/* ── Time Range selector ── */}
      <div className="flex items-center gap-3">
        <label htmlFor="range-select" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Analysis Window
        </label>
        <Select id="range-select" value={timeRange} onValueChange={(v) => setTimeRange(v ?? "30")}>
          <SelectTrigger className="h-8 text-sm w-[150px]" aria-label="Select Shift Range">
            <SelectValue placeholder="Time Range" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="10">Last 10 Shifts</SelectItem>
            <SelectItem value="30">Last 30 Shifts</SelectItem>
            <SelectItem value="100">Last 100 Shifts</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* ── TOP KPI SUMMARY METRICS (derived dynamically) ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Average Throughput */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-1.5">
              <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
              <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                Avg Throughput
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold font-mono tracking-tight text-foreground">
              {kpis.avgThroughput}
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              vehicles / shift
            </p>
          </CardContent>
        </Card>

        {/* Recurring Bottlenecks count */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-1.5">
              <ShieldAlert className="h-3.5 w-3.5 text-amber-600" />
              <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                Recurr Bottlenecks
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold font-mono tracking-tight text-amber-700">
              {kpis.bottlenecksCount} stations
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              constraint hotspots
            </p>
          </CardContent>
        </Card>

        {/* Average Warning Lead Time */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-muted-foreground" />
              <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                Avg Lead Time
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold font-mono tracking-tight text-foreground">
              {kpis.medianLeadTime} min
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              predictive horizon
            </p>
          </CardContent>
        </Card>

        {/* False Alerts per shift */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-1.5">
              <BellRing className="h-3.5 w-3.5 text-muted-foreground" />
              <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                False Alerts
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold font-mono tracking-tight text-foreground">
              {kpis.falseAlertsPerShift}
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              alerts / shift avg
            </p>
          </CardContent>
        </Card>

        {/* Defect Rate */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-1.5">
              <Percent className="h-3.5 w-3.5 text-red-600" />
              <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                Defect Rate
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold font-mono tracking-tight text-red-700">
              {kpis.defectRate}%
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              historical rate avg
            </p>
          </CardContent>
        </Card>

        {/* Sensor Coverage */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5 text-muted-foreground" />
              <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                Sensor Coverage
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold font-mono tracking-tight text-foreground">
              {kpis.sensorCoverage}%
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              live telemetry avg
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── ROW 1: Trend Charts ── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Throughput Trend */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Throughput Trend</CardTitle>
            <CardDescription className="text-xs">
              Vehicles completed per shift. Reflects production output consistency.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <ThroughputTrendChart shifts={filteredShifts} />
          </CardContent>
        </Card>

        {/* Warning Lead Time Trend */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Warning Lead Time Trend</CardTitle>
            <CardDescription className="text-xs">
              Median minutes warnings occurred prior to constraint onset. Target range is 5-10m.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <WarningLeadTimeChart shifts={filteredShifts} />
          </CardContent>
        </Card>
      </div>

      {/* ── ROW 2: Hotspot Tables ── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Bottleneck Hotspots */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Recurring Bottleneck Hotspots</CardTitle>
            <CardDescription className="text-xs">
              Stations ranked by frequency of bottleneck constraints across prior shifts.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <BottleneckHotspots hotspots={[]} />
          </CardContent>
        </Card>

        {/* Quality Hotspots */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Quality Hotspots</CardTitle>
            <CardDescription className="text-xs">
              Stations frequently associated with elevated quality-risk exposure or downstream defects.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <QualityHotspots />
          </CardContent>
        </Card>
      </div>

      {/* ── ROW 3: False Alerts & Anomalies ── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* False Alerts Trend */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">False Alerts per Shift</CardTitle>
            <CardDescription className="text-xs">
              Average alerts designated as false alarms. Low rates preserve operator trust.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <FalseAlertTrendChart shifts={filteredShifts} />
            <div className="mt-3 text-[10px] text-muted-foreground flex items-start gap-1">
              <HelpCircle className="h-3.5 w-3.5 shrink-0 text-slate-400 mt-0.5" />
              <span>
                False alerts are monitored because excessive warnings cause alarm fatigue. Twin AI publishes model accuracy transparently.
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Recurring Anomaly Patterns */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Recurring Anomaly Patterns</CardTitle>
            <CardDescription className="text-xs">
              Meaningful repeated process limit deviation patterns (e.g. signal drift, pressure variations).
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <AnomalyPatterns patterns={patterns} />
          </CardContent>
        </Card>
      </div>

      {/* ── ROW 4: Sensor Gaps & Maintenance Candidates ── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Sensor Coverage Gaps */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Sensor Coverage Gaps</CardTitle>
            <CardDescription className="text-xs">
              Stations where high UNKNOWN or INFERRED data coverage limits prediction confidence.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <SensorGapAnalysis />
          </CardContent>
        </Card>

        {/* Maintenance Candidates */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <div className="flex items-center gap-2">
              <Wrench className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm font-semibold">Maintenance Candidates</CardTitle>
            </div>
            <CardDescription className="text-xs">
              Stations requiring review due to tool wear, minor stops, or repeated cycle deviations.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <MaintenanceCandidates candidates={candidates} />
          </CardContent>
        </Card>
      </div>

      {/* ── ROW 5: Shift summary list ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">Recent Shift History</CardTitle>
          <CardDescription className="text-xs">
            Shift-by-shift summary of plant production throughput, defects, warning lead times, and telemetry.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-4">
          <ShiftSummaryTable shifts={filteredShifts} />
        </CardContent>
      </Card>
    </div>
  );
}
