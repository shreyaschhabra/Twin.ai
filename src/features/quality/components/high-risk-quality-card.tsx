/**
 * High Risk Quality Card
 *
 * Prominent card displaying the vehicle with the highest defect risk prediction.
 * Shows risk percentage, confidence level, anomaly exposure details, and evidence.
 */

import Link from "next/link";
import { AlertTriangle, Car, ShieldAlert, ArrowRight, Activity, HelpCircle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import type { QualityPrediction } from "@/types/quality";
import { cn } from "@/lib/utils";

interface HighRiskQualityCardProps {
  prediction: QualityPrediction;
}

function riskColor(risk: number) {
  if (risk >= 0.5) return "text-red-700 dark:text-red-400";
  if (risk >= 0.2) return "text-amber-700 dark:text-amber-400";
  return "text-emerald-700 dark:text-emerald-400";
}

function riskBg(risk: number) {
  if (risk >= 0.5) return "bg-red-500";
  if (risk >= 0.2) return "bg-amber-500";
  return "bg-emerald-500";
}

export function HighRiskQualityCard({ prediction }: HighRiskQualityCardProps) {
  const riskPct = Math.round(prediction.defectRisk * 100);

  return (
    <Card className="border-2 border-red-200 shadow-none bg-red-50/20">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-red-600 shrink-0" aria-hidden="true" />
              <CardTitle className="text-sm font-semibold">
                Highest Priority Quality Risk
              </CardTitle>
            </div>
            <CardDescription className="text-xs">
              Vehicle with the highest active Quality defect risk estimate.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 text-[10px] uppercase font-semibold">
              HIGH RISK
            </Badge>
            <ConfidenceBadge confidence={prediction.confidence} />
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {/* Vehicle ID */}
          <div className="space-y-0.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Vehicle ID
            </p>
            <p className="text-lg font-bold font-mono">{prediction.vehicleId}</p>
            <p className="text-xs text-muted-foreground uppercase">{prediction.variant.replace("_", " ")}</p>
          </div>

          {/* Defect Risk */}
          <div className="space-y-0.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Defect Risk Estimate
            </p>
            <p className={cn("text-3xl font-extrabold tracking-tight tabular-nums", riskColor(prediction.defectRisk))}>
              {riskPct}%
            </p>
            <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-500", riskBg(prediction.defectRisk))}
                style={{ width: `${riskPct}%` }}
              />
            </div>
          </div>

          {/* Current Stage */}
          <div className="space-y-0.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Current Stage
            </p>
            <p className="text-sm font-bold text-foreground mt-1">
              {prediction.currentStage}
            </p>
            <p className="text-[10px] text-muted-foreground">In production line</p>
          </div>

          {/* Final QC Status */}
          <div className="space-y-0.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Final QC Status
            </p>
            <div className="mt-1">
              <Badge className="bg-slate-100 text-slate-700 border-slate-200 text-xs font-semibold hover:bg-slate-100">
                PENDING
              </Badge>
            </div>
            <p className="text-[10px] text-muted-foreground">QC downstream</p>
          </div>
        </div>

        {/* Anomaly Exposure Info */}
        {prediction.exposureCohortId && (
          <div className="rounded-md border border-amber-200 bg-amber-50/40 p-3 space-y-1.5">
            <div className="flex items-center gap-1.5 text-amber-800 text-[10px] font-semibold uppercase tracking-wider font-mono">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
              Process Anomaly Exposure Detected
            </div>
            <p className="text-xs text-muted-foreground">
              This vehicle passed through a station during a detected process anomaly window.
            </p>
            <div className="flex flex-wrap gap-4 pt-1 text-xs">
              <div>
                <span className="text-muted-foreground">Station:</span>{" "}
                <Link
                  href={`/app/live-twin/stations/${prediction.exposureCohortId.split("-")[1] || "S12"}`}
                  className="font-mono font-semibold text-foreground hover:underline"
                >
                  {prediction.exposureCohortId.split("-")[1] || "S12"}
                </Link>
              </div>
              <div>
                <span className="text-muted-foreground">Cohort ID:</span>{" "}
                <span className="font-mono text-foreground font-semibold">{prediction.exposureCohortId}</span>
              </div>
            </div>
          </div>
        )}

        {/* Contributing Signals Evidence */}
        <div className="border-t pt-3 space-y-2">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
            Contributing Signals (Correlations)
          </p>
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-2">
            {prediction.evidence.map((item, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between p-2 rounded border bg-background text-xs font-mono"
              >
                <span className="text-muted-foreground truncate mr-2">{item.label}</span>
                <span
                  className={cn(
                    "font-medium shrink-0",
                    item.direction === "negative"
                      ? "text-red-700"
                      : item.direction === "positive"
                      ? "text-emerald-700"
                      : "text-muted-foreground",
                  )}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground flex items-center gap-1 italic mt-1.5">
            <HelpCircle className="h-3 w-3 shrink-0 text-muted-foreground" />
            Anomaly signals represent unusual process behavior. Defect risk is estimated separately and does not establish root-cause certainty.
          </p>
        </div>

        {/* Navigation */}
        <div className="border-t pt-3 flex flex-wrap gap-3">
          <Link
            href={`/app/vehicles/${prediction.vehicleId}`}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground hover:underline"
          >
            <Car className="h-3.5 w-3.5" />
            Open Vehicle Detail
          </Link>
          <Link
            href="/app/live-twin"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground hover:underline transition-colors"
          >
            Locate on Live Twin Line
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
