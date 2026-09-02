/**
 * Validation Dashboard Container Component
 *
 * Client-side layout tab coordinator displaying:
 * - Overview: Splitting timeline, validation protocols, checks list, and reproducibility run metadata.
 * - Flow Model Validation: Flow KPIs, model baseline comparisons, threshold curves.
 * - Quality Model Validation: Quality KPIs, calibration curve, PR curve, confusion matrix.
 * - Anomaly & Robustness: Event recall, unseen scenario robustness testing.
 */

"use client";

import { useState } from "react";
import Link from "next/link";
import {
  GitCommit,
  ShieldCheck,
  TableProperties,
  LineChart,
  Network,
  Wrench,
  HelpCircle,
  ArrowRight,
  Database,
  ArrowUpRight,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { PrecisionRecallChart } from "./precision-recall-chart";
import { CalibrationChart } from "./calibration-chart";
import { ThresholdTradeoffChart } from "./threshold-tradeoff-chart";
import { ConfusionMatrixCard } from "./confusion-matrix-card";
import { SHAPExamples } from "./shap-examples";
import type {
  ValidationMetrics,
  BaselineResult,
  ValidationCheck,
  AnomalyValidationMetrics,
  ReproducibilityMetadata,
} from "@/types/validation";

interface ValidationDashboardContainerProps {
  metrics: ValidationMetrics;
  flowBaselines: BaselineResult[];
  qualityBaselines: BaselineResult[];
  protocolChecks: ValidationCheck[];
  anomalyMetrics: AnomalyValidationMetrics;
  runMetadata: ReproducibilityMetadata;
}

export function ValidationDashboardContainer({
  metrics,
  flowBaselines,
  qualityBaselines,
  protocolChecks,
  anomalyMetrics,
  runMetadata,
}: ValidationDashboardContainerProps) {
  const [activeTab, setActiveTab] = useState<string>("overview"); // overview, flow, quality, anomaly

  const { flow, quality } = metrics;

  return (
    <div className="space-y-6">
      {/* ── TABS SELECTOR ── */}
      <div className="flex border-b overflow-x-auto gap-2 scrollbar-none">
        <button
          onClick={() => setActiveTab("overview")}
          className={`pb-2.5 px-4 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all whitespace-nowrap ${
            activeTab === "overview"
              ? "border-blue-600 text-blue-600 font-bold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Overview & Run Metadata
        </button>
        <button
          onClick={() => setActiveTab("flow")}
          className={`pb-2.5 px-4 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all whitespace-nowrap ${
            activeTab === "flow"
              ? "border-blue-600 text-blue-600 font-bold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Flow ML Validation
        </button>
        <button
          onClick={() => setActiveTab("quality")}
          className={`pb-2.5 px-4 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all whitespace-nowrap ${
            activeTab === "quality"
              ? "border-blue-600 text-blue-600 font-bold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Quality ML Validation
        </button>
        <button
          onClick={() => setActiveTab("anomaly")}
          className={`pb-2.5 px-4 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all whitespace-nowrap ${
            activeTab === "anomaly"
              ? "border-blue-600 text-blue-600 font-bold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Anomalies & Explainability
        </button>
      </div>

      {/* ── OVERVIEW TAB ── */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Validation Status Banner */}
          <div className="bg-slate-50 border rounded-lg p-4 grid gap-4 grid-cols-2 md:grid-cols-4">
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                Evaluation Mode
              </p>
              <p className="text-xs font-mono font-bold mt-1 text-foreground">
                Time-separated holdout
              </p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                Model Results State
              </p>
              <p className="text-xs font-mono font-bold mt-1 text-amber-700">
                Demo / awaiting final integration
              </p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                Leakage Check
              </p>
              <p className="text-xs font-mono font-bold mt-1 text-foreground">
                Designed for temporal isolation
              </p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                Threshold Selector
              </p>
              <p className="text-xs font-mono font-bold mt-1 text-foreground">
                Validation-set based
              </p>
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* Temporal Split Diagram */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Temporal Train/Validation/Test Split</CardTitle>
                <CardDescription className="text-xs">
                  Evaluation uses time-ordered shift separation so future information is not leaked into predictions.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4 space-y-4">
                <div className="h-6 w-full bg-slate-100 rounded overflow-hidden flex border">
                  <div className="bg-slate-300 text-slate-800 h-full flex items-center justify-center text-[10px] font-mono font-bold uppercase tracking-wider" style={{ width: "70%" }}>
                    Train (1-70)
                  </div>
                  <div className="bg-amber-100 text-amber-800 h-full flex items-center justify-center text-[10px] font-mono font-bold uppercase tracking-wider" style={{ width: "15%" }}>
                    Val (71-85)
                  </div>
                  <div className="bg-blue-100 text-blue-800 h-full flex items-center justify-center text-[10px] font-mono font-bold uppercase tracking-wider" style={{ width: "15%" }}>
                    Test (86-100)
                  </div>
                </div>
                <div className="text-[10px] text-muted-foreground flex items-start gap-1">
                  <HelpCircle className="h-3.5 w-3.5 shrink-0 text-slate-400 mt-0.5" />
                  <span>
                    Neighboring time-series rows are not randomly split. Shift indices are partitioned temporally to mimic production startup.
                  </span>
                </div>
              </CardContent>
            </Card>

            {/* Validation protocol checks */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Validation Leakage Protocol Checks</CardTitle>
                <CardDescription className="text-xs">
                  Required criteria to prevent predictive lookup leakage during training.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <div className="space-y-3">
                  {protocolChecks.map((check, idx) => (
                    <div key={idx} className="flex items-start justify-between gap-3 text-xs">
                      <div className="space-y-0.5">
                        <p className="font-semibold text-foreground">{check.label}</p>
                        <p className="text-[10px] text-muted-foreground">{check.description}</p>
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          check.status === "DEMO"
                            ? "bg-amber-50 text-amber-700 border-amber-200 text-[9px] uppercase font-bold whitespace-nowrap shrink-0"
                            : "bg-slate-50 text-slate-700 border-slate-200 text-[9px] uppercase font-semibold whitespace-nowrap shrink-0"
                        }
                      >
                        {check.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Reproducibility Run Metadata */}
          <Card className="border shadow-none">
            <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-sm font-semibold">Evaluation Reproducibility run metadata</CardTitle>
                <CardDescription className="text-xs">
                  Active model candidate specifications and seeds.
                </CardDescription>
              </div>
              <Badge variant="outline" className="text-[9px] uppercase font-mono bg-slate-50">
                Demo Run Config
              </Badge>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="grid gap-4 grid-cols-2 md:grid-cols-4 text-xs font-mono">
                <div>
                  <span className="text-muted-foreground block text-[10px]">Model version</span>
                  <span className="text-foreground font-bold">{runMetadata.modelVersion}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Simulation config</span>
                  <span className="text-foreground font-semibold">{runMetadata.simulationConfig}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Training shift range</span>
                  <span className="text-foreground">{runMetadata.trainingShifts}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Validation range</span>
                  <span className="text-foreground">{runMetadata.validationShifts}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Test range</span>
                  <span className="text-foreground">{runMetadata.testShifts}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Alert threshold</span>
                  <span className="text-foreground font-bold">{runMetadata.alertThreshold}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Random seed</span>
                  <span className="text-foreground">{runMetadata.randomSeed}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Evaluation timestamp</span>
                  <span className="text-foreground text-[10px]">{runMetadata.timestamp}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── FLOW VALIDATION TAB ── */}
      {activeTab === "flow" && (
        <div className="space-y-6">
          {/* Flow KPIs */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Precision (PPV)
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {flow.precision}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Of issued alerts, how many were true constraints
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Recall (Sens.)
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {flow.recall}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Of constraints, how many were correctly detected
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  False Alerts
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {flow.falseAlertsPerShift}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Unnecessary warnings issued per shift
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Median Lead Time
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {flow.medianWarningLeadTime} min
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Typical time between alert and actual impact
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Useful Horizon
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {Math.round(flow.detectedWithinUsefulHorizon * 100)}%
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Detected within target 5–10 min window
                </p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* Flow Baseline comparison table */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Model Baseline Comparisons</CardTitle>
                <CardDescription className="text-xs">
                  Comparison against simpler rules and standard ML candidates.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <div className="rounded border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/40">
                        <TableHead className="text-xs font-semibold">Model</TableHead>
                        <TableHead className="text-xs font-semibold text-center">Precision</TableHead>
                        <TableHead className="text-xs font-semibold text-center">Recall</TableHead>
                        <TableHead className="text-xs font-semibold text-center">False Alerts / Shift</TableHead>
                        <TableHead className="text-xs font-semibold text-center">Lead Time</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {flowBaselines.map((baseline, idx) => (
                        <TableRow key={idx} className={baseline.isBest ? "bg-blue-50/20 font-medium" : ""}>
                          <TableCell className="text-xs whitespace-nowrap">
                            <div className="flex items-center gap-1.5">
                              {baseline.model}
                              {baseline.isBest && (
                                <Badge variant="outline" className="text-[9px] uppercase bg-blue-100 text-blue-800 border-blue-200 py-0 font-bold">
                                  Current Best
                                </Badge>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.precision}</TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.recall}</TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.falseAlertsPerShift}</TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.medianLeadTime}m</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            {/* Threshold trade-off chart */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Threshold Trade-off Curves</CardTitle>
                <CardDescription className="text-xs">
                  Alert volume and prediction accuracy as decision bounds shift.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <ThresholdTradeoffChart selectedThreshold={0.65} />
              </CardContent>
            </Card>
          </div>

          <div className="flex items-center justify-between border rounded p-3 bg-slate-50/50">
            <span className="text-xs text-muted-foreground font-medium">
              Want to see real-time constraint prediction logs?
            </span>
            <Link
              href="/app/flow"
              className="text-xs font-semibold text-blue-600 hover:underline flex items-center gap-1"
            >
              View Flow Intelligence
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      )}

      {/* ── QUALITY VALIDATION TAB ── */}
      {activeTab === "quality" && (
        <div className="space-y-6">
          {/* Quality KPIs */}
          <div className="grid grid-cols-2 sm:grid-cols-6 gap-3">
            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Precision (PPV)
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {quality.precision}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Of flagged vehicles, how many were confirmed defects
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Recall (Sens.)
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {quality.recall}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Of defects, how many were correctly caught by model
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  F1 Score
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {quality.f1}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Harmonic mean of precision and recall
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  PR-AUC
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {quality.prAuc}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Area under Precision-Recall curve
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  False Alerts
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {quality.falseAlertsPer100Vehicles}
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Unnecessary warnings per 100 vehicles
                </p>
              </CardContent>
            </Card>

            <Card className="border shadow-none">
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Early Detection
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-lg font-bold font-mono text-foreground">
                  {quality.averageEarlyDetectionDistance} stations
                </p>
                <p className="text-[9px] text-muted-foreground mt-0.5">
                  Avg stations flagged before final inspection QC
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Imbalance class note */}
          <div className="bg-amber-50/50 text-amber-900 border border-amber-200 rounded p-3 text-xs leading-relaxed">
            <strong>Class Imbalance Context:</strong> The simulated Quality defect rate is approximately 4%, so raw accuracy is not treated as the primary evaluation metric. Instead, the focus is placed on F1-Score, PR-AUC, and false-alert rates.
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* PR Curve */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Precision-Recall Curve</CardTitle>
                <CardDescription className="text-xs">
                  Reflects classifier threshold capabilities under severe class imbalance.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <PrecisionRecallChart points={quality.prCurve || []} />
              </CardContent>
            </Card>

            {/* Calibration Curve */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Probability Calibration</CardTitle>
                <CardDescription className="text-xs">
                  Predicted risk probabilities must match observed empirical event rates.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <CalibrationChart points={quality.calibration || []} />
                <p className="text-[10px] text-muted-foreground mt-3 leading-relaxed">
                  If Twin AI displays an 80% risk, that probability should correspond reasonably to observed outcomes among comparable predictions.
                </p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* Confusion Matrix */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Confusion Matrix</CardTitle>
                <CardDescription className="text-xs">
                  Prediction vs Ground Truth outcomes for the validation test set.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <ConfusionMatrixCard matrix={quality.confusionMatrix} title="Quality Classifier Matrix" />
              </CardContent>
            </Card>

            {/* Quality Baseline model comparison */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Model Baseline Comparisons</CardTitle>
                <CardDescription className="text-xs">
                  Comparison against simpler rules and baseline ML architectures.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <div className="rounded border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/40">
                        <TableHead className="text-xs font-semibold">Model</TableHead>
                        <TableHead className="text-xs font-semibold text-center">Precision</TableHead>
                        <TableHead className="text-xs font-semibold text-center">Recall</TableHead>
                        <TableHead className="text-xs font-semibold text-center">F1</TableHead>
                        <TableHead className="text-xs font-semibold text-center">PR-AUC</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {qualityBaselines.map((baseline, idx) => (
                        <TableRow key={idx} className={baseline.isBest ? "bg-blue-50/20 font-medium" : ""}>
                          <TableCell className="text-xs whitespace-nowrap">
                            <div className="flex items-center gap-1.5">
                              {baseline.model}
                              {baseline.isBest && (
                                <Badge variant="outline" className="text-[9px] uppercase bg-blue-100 text-blue-800 border-blue-200 py-0 font-bold">
                                  Current Best
                                </Badge>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.precision}</TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.recall}</TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.f1}</TableCell>
                          <TableCell className="text-xs text-center font-mono">{baseline.prAuc}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="flex items-center justify-between border rounded p-3 bg-slate-50/50">
            <span className="text-xs text-muted-foreground font-medium">
              Want to see real-time vehicle-level defect risk cohorts?
            </span>
            <Link
              href="/app/quality"
              className="text-xs font-semibold text-blue-600 hover:underline flex items-center gap-1"
            >
              View Quality Intelligence
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      )}

      {/* ── ANOMALIES & EXPLAINABILITY TAB ── */}
      {activeTab === "anomaly" && (
        <div className="space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            {/* Anomaly Detection evaluation */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Anomaly Detection Evaluation</CardTitle>
                <CardDescription className="text-xs">
                  Event-based validation metrics (evaluates anomalies as single events rather than independent minutes).
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="border rounded p-3 text-center">
                    <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block">
                      Event Recall
                    </span>
                    <span className="text-xl font-bold font-mono text-foreground block mt-1">
                      {Math.round(anomalyMetrics.eventRecall * 100)}%
                    </span>
                  </div>
                  <div className="border rounded p-3 text-center">
                    <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block">
                      Detection Delay
                    </span>
                    <span className="text-xl font-bold font-mono text-foreground block mt-1">
                      {anomalyMetrics.detectionDelaySec}s
                    </span>
                  </div>
                  <div className="border rounded p-3 text-center">
                    <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block">
                      False Anomalies
                    </span>
                    <span className="text-xl font-bold font-mono text-foreground block mt-1">
                      {anomalyMetrics.falseAlertsPerShift} / shift
                    </span>
                  </div>
                  <div className="border rounded p-3 text-center">
                    <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block">
                      Time to Detect
                    </span>
                    <span className="text-xl font-bold font-mono text-foreground block mt-1">
                      {anomalyMetrics.timeToDetectSec}s
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Unseen scenario robustness */}
            <Card className="border shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-sm font-semibold">Unseen Scenario Robustness</CardTitle>
                <CardDescription className="text-xs">
                  Validation of anomaly layer under unfamiliar or un-modeled situations.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4 space-y-3">
                <div className="flex items-start justify-between gap-3 text-xs border-b pb-2">
                  <span className="text-muted-foreground font-medium">Unseen Scenario state</span>
                  <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-200 text-[9px] uppercase font-bold">
                    Held out
                  </Badge>
                </div>
                <div className="flex items-start justify-between gap-3 text-xs border-b pb-2">
                  <span className="text-muted-foreground font-medium">Supervised model accuracy</span>
                  <span className="font-semibold text-slate-700">Limited / not generalized</span>
                </div>
                <div className="flex items-start justify-between gap-3 text-xs pb-1">
                  <span className="text-muted-foreground font-medium">Anomaly layer response</span>
                  <span className="font-bold text-emerald-700">Unusual telemetry flags raised</span>
                </div>
                <p className="text-[10px] text-muted-foreground leading-relaxed mt-2">
                  At least one abnormal dropout scenario was excluded from supervised training to test whether the anomaly layer still recognizes unfamiliar telemetry dropouts.
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Explainability SHAP Example Attributions */}
          <Card className="border shadow-none">
            <CardHeader className="pb-3 border-b">
              <CardTitle className="text-sm font-semibold">Explainability Factor Examples</CardTitle>
              <CardDescription className="text-xs">
                Attribution structure demonstrating predictive factors contributing to alerts.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4">
              <SHAPExamples />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
