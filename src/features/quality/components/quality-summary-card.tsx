import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import type { QualityPrediction, ExposureCohort } from "@/types/quality";

interface QualitySummaryCardProps {
  predictions: QualityPrediction[];
  cohorts: ExposureCohort[];
}

export function QualitySummaryCard({ predictions, cohorts }: QualitySummaryCardProps) {
  const totalMonitored = predictions.length;
  const highRiskCount = predictions.filter((p) => p.defectRisk >= 0.5).length;

  // Find highest risk vehicle
  const highestRiskPred = predictions.reduce<QualityPrediction | null>((max, p) => {
    if (!max || p.defectRisk > max.defectRisk) return p;
    return max;
  }, null);

  const activeCohort = cohorts[0]; // Take the first cohort

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4">
        <div>
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-500 shrink-0" />
            Quality Summary
          </CardTitle>
          <CardDescription className="text-xs text-muted-foreground">
            Defect containment telemetry metrics.
          </CardDescription>
        </div>
        <Link
          href="/app/quality"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-3 text-xs font-medium text-foreground hover:bg-accent transition-colors self-start sm:self-center"
        >
          View Quality Page
        </Link>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Quality stats row */}
        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 border rounded-md bg-muted/10 font-mono text-center">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider block">
              Monitored Vehicles
            </span>
            <span className="text-xl font-bold tracking-tight">{totalMonitored}</span>
          </div>
          <div className="p-3 border rounded-md bg-muted/10 font-mono text-center">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider block">
              High-Risk Assemblies
            </span>
            <span className="text-xl font-bold tracking-tight text-orange-500">
              {highRiskCount}
            </span>
          </div>
        </div>

        {/* Highest risk highlight */}
        {highestRiskPred && (
          <div className="p-3 border rounded-md bg-muted/5 space-y-1 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-muted-foreground uppercase tracking-wider text-[9px] font-mono">
                Highest Risk Vehicle
              </span>
              <span className="font-mono text-rose-500 font-bold">
                {Math.round(highestRiskPred.defectRisk * 100)}% Risk
              </span>
            </div>
            <p className="font-mono font-medium text-foreground">
              {highestRiskPred.vehicleId} ({highestRiskPred.variant}) — {highestRiskPred.currentStage}
            </p>
          </div>
        )}

        {/* Active cohort indicator */}
        {activeCohort ? (
          <div className="p-3 border border-amber-500/20 bg-amber-500/5 rounded-md text-xs space-y-1">
            <div className="flex items-center gap-1 text-amber-700 dark:text-amber-400 font-semibold uppercase tracking-wider text-[9px] font-mono">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
              Active Exposure Cohort
            </div>
            <p className="font-mono text-foreground font-semibold">
              {activeCohort.id} ({activeCohort.stationId})
            </p>
            <p className="text-muted-foreground font-sans line-clamp-2">
              {activeCohort.description}
            </p>
          </div>
        ) : (
          <div className="p-3 border rounded-md bg-muted/10 text-center text-xs text-muted-foreground">
            No active quality exposure cohorts.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
