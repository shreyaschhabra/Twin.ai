/**
 * Leadership Dashboard Container Component
 *
 * Coordinates executive-friendly business case presentations, rollout roadmaps,
 * sensor retrofit priorities, and model trust snapshots for Twin AI.
 */

"use client";

import Link from "next/link";
import {
  TrendingUp,
  Activity,
  Layers,
  Wrench,
  HelpCircle,
  ArrowUpRight,
  ShieldCheck,
  CheckCircle2,
  DollarSign,
  AlertTriangle,
  Cpu,
  BarChart3,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { LeadershipSummary } from "@/types/leadership";
import type { RoiCalculation } from "@/types/roi";
import type { ValidationMetrics } from "@/types/validation";
import { formatCurrency, formatNumber } from "@/features/roi/lib/roi-formatters";

interface LeadershipDashboardContainerProps {
  summary: LeadershipSummary;
  roiDefaults: RoiCalculation;
  validationMetrics: ValidationMetrics;
}

export function LeadershipDashboardContainer({
  summary,
  roiDefaults,
  validationMetrics,
}: LeadershipDashboardContainerProps) {
  const { kpis, readiness, retrofitPriorities, stages, scale } = summary;
  const { inputs, outputs } = roiDefaults;
  const { flow, quality } = validationMetrics;

  return (
    <div className="space-y-6">
      {/* ── TOP EXECUTIVE KPIs ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Throughput Opportunity */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Throughput Opportunity
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold text-foreground">
              {kpis.throughputOpportunity}
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              Potential recovery
            </p>
          </CardContent>
        </Card>

        {/* Downtime Opportunity */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Downtime Opportunity
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold text-amber-700">
              {kpis.downtimeOpportunity}
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              addressed bottleneck minutes
            </p>
          </CardContent>
        </Card>

        {/* Quality Opportunity */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Quality Opportunity
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold text-red-700">
              {kpis.qualityOpportunity}
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              rework & scrap reduction
            </p>
          </CardContent>
        </Card>

        {/* Sensor Readiness */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Sensor Readiness
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold font-mono text-foreground">
              {kpis.sensorReadiness}%
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              telemetry rich/partial
            </p>
          </CardContent>
        </Card>

        {/* Prediction Readiness */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Prediction Readiness
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold text-foreground">
              {kpis.predictionReadiness}
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              offline holdout results
            </p>
          </CardContent>
        </Card>

        {/* Rollout Readiness */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Rollout Readiness
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-lg font-bold text-emerald-700">
              {kpis.rolloutReadiness}
            </p>
            <p className="text-[9px] text-muted-foreground mt-0.5 uppercase font-semibold">
              read-only sidecar stage
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── SECTION 1: Business Value Areas ── */}
      <div className="grid gap-4 md:grid-cols-3">
        {/* Flow Value */}
        <Card className="border shadow-none">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <span className="p-1.5 bg-blue-50 text-blue-700 rounded border border-blue-100">
                <TrendingUp className="h-4 w-4" />
              </span>
              <CardTitle className="text-sm font-semibold">Flow Value Area</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground leading-relaxed">
              Address recurring bottlenecks at torque and manual fastening areas to minimize unplanned line downtime and throughput loss.
            </p>
            <div className="pt-2 border-t text-[10px] text-muted-foreground flex items-center justify-between font-mono">
              <span>Potential Throughput Recovery:</span>
              <span className="font-bold text-foreground">4 vehicles / shift</span>
            </div>
          </CardContent>
        </Card>

        {/* Quality Value */}
        <Card className="border shadow-none">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <span className="p-1.5 bg-red-50 text-red-700 rounded border border-red-100">
                <ShieldCheck className="h-4 w-4" />
              </span>
              <CardTitle className="text-sm font-semibold">Quality Value Area</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground leading-relaxed">
              Identify high-risk vehicles earlier in assembly stages to prevent completed defective parts from passing downstream.
            </p>
            <div className="pt-2 border-t text-[10px] text-muted-foreground flex items-center justify-between font-mono">
              <span>Avg Early Warnings:</span>
              <span className="font-bold text-foreground">6.1 stations early</span>
            </div>
          </CardContent>
        </Card>

        {/* Trust/Sensor Optimization Value */}
        <Card className="border shadow-none">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <span className="p-1.5 bg-slate-100 text-slate-800 rounded border border-slate-200">
                <Layers className="h-4 w-4" />
              </span>
              <CardTitle className="text-sm font-semibold">Trust & Instrumentation Value</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground leading-relaxed">
              Avoid excessive hardware sensor retrofit expenses. Twin AI utilizes virtual inferred sensing where network latency permits.
            </p>
            <div className="pt-2 border-t text-[10px] text-muted-foreground flex items-center justify-between font-mono">
              <span>Inferred Sensing dependency:</span>
              <span className="font-bold text-foreground">17% runtime telemetry</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── SECTION 2: Impact & Trust snapshot ── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Model Trust Snapshot */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between flex-wrap gap-2">
            <div>
              <CardTitle className="text-sm font-semibold">Model Trust Snapshot</CardTitle>
              <CardDescription className="text-xs">
                Summarized holdout verification metrics proving model credibility.
              </CardDescription>
            </div>
            <Link
              href="/app/validation"
              className="text-xs font-semibold text-blue-600 hover:underline flex items-center gap-0.5"
            >
              Verify model stats
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="pt-4 space-y-4">
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="border rounded p-2 bg-slate-50/50">
                <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                  Flow Precision
                </span>
                <span className="text-sm font-bold font-mono text-foreground block mt-1">
                  {Math.round(flow.precision * 100)}%
                </span>
              </div>
              <div className="border rounded p-2 bg-slate-50/50">
                <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                  Flow Recall
                </span>
                <span className="text-sm font-bold font-mono text-foreground block mt-1">
                  {Math.round(flow.recall * 100)}%
                </span>
              </div>
              <div className="border rounded p-2 bg-slate-50/50">
                <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                  Flow Lead Time
                </span>
                <span className="text-sm font-bold font-mono text-foreground block mt-1">
                  {flow.medianWarningLeadTime}m
                </span>
              </div>
              <div className="border rounded p-2 bg-slate-50/50">
                <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                  Quality PR-AUC
                </span>
                <span className="text-sm font-bold font-mono text-foreground block mt-1">
                  {Math.round(quality.prAuc * 100)}%
                </span>
              </div>
              <div className="border rounded p-2 bg-slate-50/50">
                <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                  Quality Recall
                </span>
                <span className="text-sm font-bold font-mono text-foreground block mt-1">
                  {Math.round(quality.recall * 100)}%
                </span>
              </div>
              <div className="border rounded p-2 bg-slate-50/50">
                <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                  False Alerts
                </span>
                <span className="text-sm font-bold font-mono text-foreground block mt-1">
                  {flow.falseAlertsPerShift} / shift
                </span>
              </div>
            </div>
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              Confidence outputs use calibrated probabilities. Unnecessary alerts are transparently monitored to prevent alarms fatigue.
            </p>
          </CardContent>
        </Card>

        {/* Intelligence Readiness */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Intelligence Readiness Levels</CardTitle>
            <CardDescription className="text-xs">
              Maturity statuses for core analytical features.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs border-b pb-2">
                <span className="text-muted-foreground">Flow constraint forecasting</span>
                <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[9px] uppercase font-semibold">
                  {readiness.flowMaturity.replace("_", " ")}
                </Badge>
              </div>
              <div className="flex items-center justify-between text-xs border-b pb-2">
                <span className="text-muted-foreground">Quality defect risk flags</span>
                <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[9px] uppercase font-semibold">
                  {readiness.qualityMaturity.replace("_", " ")}
                </Badge>
              </div>
              <div className="flex items-center justify-between text-xs border-b pb-2">
                <span className="text-muted-foreground">Process telemetry anomalies</span>
                <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 text-[9px] uppercase font-semibold">
                  {readiness.anomalyMaturity.replace("_", " ")}
                </Badge>
              </div>
              <div className="flex items-center justify-between text-xs border-b pb-2">
                <span className="text-muted-foreground">Sensor Trust logic</span>
                <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[9px] uppercase font-semibold">
                  {readiness.sensorMaturity.replace("_", " ")}
                </Badge>
              </div>
              <div className="flex items-center justify-between text-xs pb-1">
                <span className="text-muted-foreground">Direct plant controllers (PLC) integration</span>
                <Badge variant="outline" className="bg-slate-50 text-slate-600 border-slate-200 text-[9px] uppercase font-semibold">
                  {readiness.plantIntegration.replace("_", " ")}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── SECTION 3: Sensor Maturity & Retrofits ── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Sensor Maturity */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Sensor Maturity Distribution</CardTitle>
            <CardDescription className="text-xs">
              Physical instrumentation breakdown across the plant's 45 stations.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4 space-y-4">
            <div className="space-y-3">
              {/* Stacked maturity bar */}
              <div className="h-6 w-full bg-slate-100 rounded overflow-hidden flex border">
                <div className="bg-emerald-600 h-full flex items-center justify-center text-[10px] text-white font-mono font-bold" style={{ width: "64%" }} title="RICH: 29 stations">
                  29 RICH
                </div>
                <div className="bg-amber-500 h-full flex items-center justify-center text-[10px] text-white font-mono font-bold" style={{ width: "22%" }} title="PARTIAL: 10 stations">
                  10 PART
                </div>
                <div className="bg-slate-400 h-full flex items-center justify-center text-[10px] text-white font-mono font-bold" style={{ width: "14%" }} title="POOR: 6 stations">
                  6 POOR
                </div>
              </div>

              {/* Data trust coverage breakdown */}
              <div className="border-t pt-3 space-y-2">
                <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block">
                  Telemetry Runtime coverage
                </span>
                <div className="grid grid-cols-3 gap-2 text-center text-xs font-mono">
                  <div className="p-1 border rounded bg-emerald-50/20 text-emerald-800">
                    <span className="block text-[8px] font-sans text-muted-foreground">LIVE</span>
                    <span className="font-bold">76%</span>
                  </div>
                  <div className="p-1 border rounded bg-blue-50/20 text-blue-800">
                    <span className="block text-[8px] font-sans text-muted-foreground">INFERRED</span>
                    <span className="font-bold">17%</span>
                  </div>
                  <div className="p-1 border rounded bg-slate-50/20 text-slate-700">
                    <span className="block text-[8px] font-sans text-muted-foreground">UNKNOWN</span>
                    <span className="font-bold">7%</span>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Retrofit priorities */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Sensor Retrofit Priorities</CardTitle>
            <CardDescription className="text-xs">
              Maturity gaps where retrofit investments would directly improve prediction confidence.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="rounded border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40">
                    <TableHead className="text-xs font-semibold">Station</TableHead>
                    <TableHead className="text-xs font-semibold">Maturity</TableHead>
                    <TableHead className="text-xs font-semibold">UNK Coverage</TableHead>
                    <TableHead className="text-xs font-semibold">Action Suggestion</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {retrofitPriorities.map((item) => (
                    <TableRow key={item.stationId}>
                      <TableCell>
                        <div className="space-y-0.5">
                          <Link
                            href={`/app/live-twin/stations/${item.stationId}`}
                            className="font-mono font-bold text-xs hover:underline text-foreground flex items-center gap-1"
                          >
                            {item.stationId}
                            <ArrowUpRight className="h-3 w-3 text-muted-foreground" />
                          </Link>
                          <p className="text-[9px] text-muted-foreground font-sans truncate max-w-[130px]">
                            {item.processName}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[9px] uppercase font-mono font-semibold">
                          {item.maturity}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs font-mono font-semibold text-red-700">
                        {Math.round(item.unknownCoverage * 100)}%
                      </TableCell>
                      <TableCell className="text-xs text-foreground font-medium">
                        {item.action}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── SECTION 4: Rollout Roadmap & Integration strategy ── */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Rollout Stages Roadmap */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Deployment Rollout Stages</CardTitle>
            <CardDescription className="text-xs">
              Maturity roadmap for Twin AI site scaling.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="space-y-4">
              {stages.map((stage, idx) => (
                <div key={idx} className="flex items-start gap-3 text-xs">
                  <div className="mt-1">
                    {stage.status === "COMPLETE" ? (
                      <CheckCircle2 className="h-4.5 w-4.5 text-emerald-600 shrink-0" />
                    ) : stage.status === "NEXT" ? (
                      <Activity className="h-4.5 w-4.5 text-blue-600 shrink-0 animate-pulse" />
                    ) : (
                      <Cpu className="h-4.5 w-4.5 text-slate-300 shrink-0" />
                    )}
                  </div>
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-foreground">{stage.stageName}</span>
                      <Badge
                        variant="outline"
                        className={
                          stage.status === "COMPLETE"
                            ? "bg-emerald-50 text-emerald-700 border-emerald-200 text-[8px] font-bold"
                            : stage.status === "NEXT"
                            ? "bg-blue-50 text-blue-700 border-blue-200 text-[8px] font-bold"
                            : "bg-slate-50 text-slate-600 border-slate-200 text-[8px]"
                        }
                      >
                        {stage.status}
                      </Badge>
                    </div>
                    <p className="text-[10px] text-muted-foreground leading-relaxed">
                      {stage.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Integration and scaling strategy */}
        <div className="space-y-4">
          <Card className="border shadow-none">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">Risk Mitigation: Read-Only Sidecar Strategy</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Twin AI initially operates strictly as a <strong>read-only sidecar</strong>. It consumes active plant telemetry streams and publishes predictive alerts for operators, but does <strong>NOT</strong> write control inputs back to PLCs, MES, or production hardware. This eliminates any direct machine control risks.
              </p>
            </CardContent>
          </Card>

          <Card className="border shadow-none">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">Scale Strategy Across Plants</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground leading-relaxed">
                Rollout uses shared configurations to avoid rebuilds:
              </p>
              <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                <div className="border p-2 rounded">
                  <span className="text-muted-foreground block text-[9px]">Shared contracts</span>
                  <span className="text-emerald-700 font-bold">READY</span>
                </div>
                <div className="border p-2 rounded">
                  <span className="text-muted-foreground block text-[9px]">Reusable templates</span>
                  <span className="text-emerald-700 font-bold">READY</span>
                </div>
                <div className="border p-2 rounded">
                  <span className="text-muted-foreground block text-[9px]">Plant calibration</span>
                  <span className="text-amber-700 font-bold">REQUIRED</span>
                </div>
                <div className="border p-2 rounded">
                  <span className="text-muted-foreground block text-[9px]">Cybersecurity review</span>
                  <span className="text-amber-700 font-bold">REQUIRED</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ── SECTION 5: Business case & ROI preview ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b flex flex-row items-center justify-between flex-wrap gap-2">
          <div>
            <CardTitle className="text-sm font-semibold">Business Case Inputs & ROI Preview</CardTitle>
            <CardDescription className="text-xs">
              Illustrative financial outputs generated from plant sizing assumptions.
            </CardDescription>
          </div>
          <Link
            href="/app/roi"
            className="text-xs font-semibold text-blue-600 hover:underline flex items-center gap-0.5"
          >
            Open ROI Calculator
            <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          <div className="grid gap-6 md:grid-cols-2">
            {/* Input list */}
            <div className="space-y-2">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider block">
                Illustrative Inputs
              </span>
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">Vehicles / Year:</span>
                  <span className="text-foreground font-bold">{formatNumber(inputs.vehiclesPerYear)}</span>
                </div>
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">Downtime Cost/Min:</span>
                  <span className="text-foreground font-bold">{formatCurrency(inputs.downtimeCostPerMinute, "INR")}</span>
                </div>
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">Historical Defect Rate:</span>
                  <span className="text-foreground font-bold">{(inputs.defectRate * 100).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">Avg Rework Cost:</span>
                  <span className="text-foreground font-bold">{formatCurrency(inputs.averageReworkCost, "INR")}</span>
                </div>
                <div className="flex justify-between border-b pb-1 col-span-2">
                  <span className="text-muted-foreground">Software Integration Cost:</span>
                  <span className="text-foreground">{formatCurrency(inputs.softwareIntegrationCost, "INR")}</span>
                </div>
              </div>
            </div>

            {/* Outputs list */}
            <div className="space-y-2">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider block">
                Estimated Benefit Preview
              </span>
              <div className="grid grid-cols-2 gap-2">
                <div className="border rounded p-2 bg-slate-50/50">
                  <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                    Estimated Annual Benefit
                  </span>
                  <span className="text-sm font-bold font-mono text-emerald-800 block mt-1.5">
                    {formatCurrency(outputs.annualGrossBenefit, "INR", true)}
                  </span>
                </div>
                <div className="border rounded p-2 bg-slate-50/50">
                  <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                    Estimated Annual Cost
                  </span>
                  <span className="text-sm font-bold font-mono text-slate-800 block mt-1.5">
                    {formatCurrency(inputs.annualOperatingCost, "INR", true)}
                  </span>
                </div>
                <div className="border rounded p-2 bg-slate-50/50">
                  <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                    Estimated Payback
                  </span>
                  <span className="text-sm font-bold font-mono text-foreground block mt-1.5">
                    {outputs.paybackMonths !== null ? `${outputs.paybackMonths}m` : "N/A"}
                  </span>
                </div>
                <div className="border rounded p-2 bg-slate-50/50">
                  <span className="text-[9px] uppercase font-semibold text-muted-foreground block">
                    Illustrative ROI
                  </span>
                  <span className="text-sm font-bold font-mono text-foreground block mt-1.5">
                    {outputs.roiPct !== null ? `${outputs.roiPct}%` : "N/A"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── SECTION 6: Key Assumptions & Constraints ── */}
      <Card className="border shadow-none bg-slate-50/30">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-1.5 text-amber-700">
            <AlertTriangle className="h-4 w-4" />
            <CardTitle className="text-sm font-semibold">Key Assumptions & Executive Constraints</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <ul className="list-disc pl-4 text-xs text-muted-foreground space-y-1">
            <li>
              <strong>Illustrative Opportunity:</strong> Benefit projections are scenario-based and depend on plant-specific calibration.
            </li>
            <li>
              <strong>Cybersecurity and Rollout approval:</strong> Production integration requires full offline network sidecar audits.
            </li>
            <li>
              <strong>No direct machine control:</strong> twin predictions provide recommendations only, MES operator override is always active.
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
