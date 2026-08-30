/**
 * Quality Details Panel Component
 *
 * Displays detailed intelligence for the selected vehicle:
 * - Defect Risk & Confidence
 * - SVG Risk Progression Chart
 * - Contributing process signals
 * - Prediction confidence explanation
 * - Telemetry trust coverage (LIVE / INFERRED / UNKNOWN)
 */

import Link from "next/link";
import { ShieldCheck, HelpCircle, AlertTriangle, Info, ArrowRight, ExternalLink } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import { RiskProgressionChart } from "./risk-progression-chart";
import type { QualityPrediction } from "@/types/quality";
import type { SensorCoverageSummary } from "@/types/common";
import { cn } from "@/lib/utils";

interface QualityDetailsPanelProps {
  prediction: QualityPrediction;
  sensorCoverage?: SensorCoverageSummary;
}

function riskColor(risk: number) {
  if (risk >= 0.5) return "text-red-700 dark:text-red-400";
  if (risk >= 0.2) return "text-amber-700 dark:text-amber-400";
  return "text-emerald-700 dark:text-emerald-400";
}

export function QualityDetailsPanel({ prediction, sensorCoverage }: QualityDetailsPanelProps) {
  const riskPct = Math.round(prediction.defectRisk * 100);

  // Default sensor coverage if not provided
  const coverage = sensorCoverage || { livePercent: 72, inferredPercent: 21, unknownPercent: 7 };

  // Qualitative confidence breakdown based on prediction confidence & coverage
  const confidenceFactors = {
    overall: prediction.confidence,
    dataCoverage: coverage.livePercent > 80 ? "HIGH" : coverage.livePercent > 50 ? "MEDIUM" : "LOW",
    freshness: "HIGH",
    modelReliability: "HIGH",
    uncertainty: prediction.confidence === "HIGH" ? "LOW" : prediction.confidence === "MEDIUM" ? "MEDIUM" : "HIGH",
  };

  const hasUnknownTelemetry = coverage.unknownPercent > 0 || prediction.confidence === "LOW";

  return (
    <Card className="border shadow-none bg-card h-full">
      <CardHeader className="pb-3 border-b">
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground font-mono">
              Selected Vehicle
            </div>
            <CardTitle className="text-sm font-semibold flex items-center gap-2 mt-1">
              <span className="font-mono">{prediction.vehicleId}</span> ({prediction.variant.replace("_", " ")})
            </CardTitle>
          </div>
          <Link
            href={`/app/vehicles/${prediction.vehicleId}`}
            className="inline-flex h-7 items-center gap-1.5 rounded border bg-background px-2.5 text-xs hover:bg-accent transition-colors"
          >
            Open Vehicle Page
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          Current Stage: <span className="font-semibold text-foreground">{prediction.currentStage}</span>
        </p>
      </CardHeader>

      <CardContent className="pt-4 space-y-4">
        {/* ── Core Risk & Confidence ── */}
        <div className="grid grid-cols-2 gap-3 p-3 rounded-lg border bg-muted/10">
          <div>
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
              Defect Risk
            </span>
            <span className={cn("text-2xl font-black tracking-tight font-mono", riskColor(prediction.defectRisk))}>
              {riskPct}%
            </span>
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
              Confidence
            </span>
            <div className="mt-1">
              <ConfidenceBadge confidence={prediction.confidence} />
            </div>
          </div>
        </div>

        {/* ── Risk Progression Chart ── */}
        <div className="space-y-1.5">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
            Risk progression trend
          </p>
          <RiskProgressionChart
            riskHistory={prediction.riskHistory}
            exposureCohortStationId={prediction.exposureCohortId?.split("-")[1]}
          />
        </div>

        {/* ── Telemetry trust coverage (Sensor Trust) ── */}
        <div className="space-y-2 border-t pt-3">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
            Evidence Telemetry Coverage
          </p>
          <div className="h-2 w-full bg-slate-200 rounded-full overflow-hidden flex">
            <div
              className="bg-emerald-500 h-full"
              style={{ width: `${coverage.livePercent}%` }}
              title={`LIVE: ${coverage.livePercent}%`}
            />
            <div
              className="bg-blue-500 h-full"
              style={{ width: `${coverage.inferredPercent}%` }}
              title={`INFERRED: ${coverage.inferredPercent}%`}
            />
            <div
              className="bg-slate-400 h-full"
              style={{ width: `${coverage.unknownPercent}%` }}
              title={`UNKNOWN: ${coverage.unknownPercent}%`}
            />
          </div>
          <div className="grid grid-cols-3 gap-2 text-[10px] font-mono">
            <div>
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1" />
              <span className="text-muted-foreground">LIVE:</span> {coverage.livePercent}%
            </div>
            <div>
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 mr-1" />
              <span className="text-muted-foreground">INF:</span> {coverage.inferredPercent}%
            </div>
            <div>
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-slate-400 mr-1" />
              <span className="text-muted-foreground">UNK:</span> {coverage.unknownPercent}%
            </div>
          </div>

          {hasUnknownTelemetry && (
            <div className="rounded border border-slate-200 bg-slate-50 p-2 text-[10px] text-muted-foreground space-y-1">
              <div className="flex items-center gap-1 font-semibold text-slate-700 uppercase">
                <AlertTriangle className="h-3 w-3 text-slate-500" />
                Telemetry Incomplete
              </div>
              <p>
                Certain upstream measurements are unavailable (UNKNOWN). Confidence is reduced, and manual check sheet verification may be appropriate at inspection.
              </p>
            </div>
          )}
        </div>

        {/* ── Contributing Signals ── */}
        <div className="space-y-1.5 border-t pt-3">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
            Contributing Signals
          </p>
          <div className="space-y-1">
            {prediction.evidence.map((item, idx) => (
              <div key={idx} className="flex items-center justify-between text-xs py-1 border-b last:border-0">
                <span className="text-muted-foreground">{item.label}</span>
                <span
                  className={cn(
                    "font-medium font-mono",
                    item.direction === "negative"
                      ? "text-red-700"
                      : item.direction === "positive"
                      ? "text-emerald-700"
                      : "text-muted-foreground"
                  )}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Confidence Breakdown ── */}
        <div className="space-y-1.5 border-t pt-3">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
            Confidence Factors
          </p>
          <div className="rounded border text-[10px] divide-y font-mono">
            <div className="flex justify-between p-1.5">
              <span className="text-muted-foreground">Data Coverage</span>
              <span className="font-semibold">{confidenceFactors.dataCoverage}</span>
            </div>
            <div className="flex justify-between p-1.5">
              <span className="text-muted-foreground">Freshness</span>
              <span className="font-semibold text-emerald-700">{confidenceFactors.freshness}</span>
            </div>
            <div className="flex justify-between p-1.5">
              <span className="text-muted-foreground">Model Reliability</span>
              <span className="font-semibold text-emerald-700">{confidenceFactors.modelReliability}</span>
            </div>
            <div className="flex justify-between p-1.5">
              <span className="text-muted-foreground">Inference Uncertainty</span>
              <span className={cn(
                "font-semibold",
                confidenceFactors.uncertainty === "HIGH" ? "text-red-700" : "text-slate-700"
              )}>{confidenceFactors.uncertainty}</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
