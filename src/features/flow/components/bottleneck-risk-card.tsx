import { Activity } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import type { FlowPrediction } from "@/types/flow";
import { cn } from "@/lib/utils";

interface BottleneckRiskCardProps {
  prediction: FlowPrediction | null;
}

export function BottleneckRiskCard({ prediction }: BottleneckRiskCardProps) {
  if (!prediction) {
    return (
      <Card className="border bg-card text-card-foreground shadow-sm">
        <CardContent className="p-8 text-center text-sm text-muted-foreground font-mono">
          No developing bottlenecks predicted. Production flow is nominal.
        </CardContent>
      </Card>
    );
  }

  const {
    stationId,
    stationName,
    bottleneckRisk,
    expectedOnsetMin,
    expectedOnsetMax,
    confidence,
    evidence,
  } = prediction;

  const riskPercent = Math.round(bottleneckRisk * 100);

  // Styling based on risk level
  const isHighRisk = bottleneckRisk >= 0.7;
  const isWatch = bottleneckRisk >= 0.2 && bottleneckRisk < 0.7;

  const riskColorClass = isHighRisk
    ? "text-rose-600 dark:text-rose-400"
    : isWatch
    ? "text-amber-600 dark:text-amber-400"
    : "text-emerald-600 dark:text-emerald-400";

  const barColorClass = isHighRisk
    ? "bg-rose-500"
    : isWatch
    ? "bg-amber-500"
    : "bg-emerald-500";

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="border-b pb-4 flex flex-row items-center justify-between gap-4">
        <div className="space-y-1">
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <Activity className="h-4 w-4 text-rose-500 shrink-0" />
            Developing Flow Bottleneck Warning
          </CardTitle>
          <CardDescription className="text-xs text-muted-foreground">
            Highest-priority flow disruption predicted on the line.
          </CardDescription>
        </div>
        <ConfidenceBadge confidence={confidence} />
      </CardHeader>
      <CardContent className="pt-6 space-y-6">
        {/* Core Stats Grid */}
        <div className="grid gap-6 md:grid-cols-3">
          {/* Station Details */}
          <div className="space-y-1 border-r pr-4">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Station Cell
            </span>
            <h5 className="text-lg font-bold text-foreground">
              {stationId} — {stationName}
            </h5>
            <p className="text-xs text-muted-foreground font-mono">
              [ Flow prediction model instance ]
            </p>
          </div>

          {/* Risk Level */}
          <div className="space-y-1 border-r pr-4">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Bottleneck Risk
            </span>
            <div className="flex items-baseline gap-2 pt-0.5">
              <span className={cn("text-3xl font-extrabold tracking-tight", riskColorClass)}>
                {riskPercent}%
              </span>
              <span className="text-xs text-muted-foreground font-mono">PROBABILITY</span>
            </div>
            {/* Risk meter */}
            <div className="h-1.5 w-full bg-muted rounded-full mt-2 overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-500", barColorClass)}
                style={{ width: `${riskPercent}%` }}
              />
            </div>
          </div>

          {/* Onset Timing */}
          <div className="space-y-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Expected Onset
            </span>
            <div className="flex items-baseline gap-1 pt-0.5">
              <span className="text-3xl font-extrabold tracking-tight text-foreground">
                {expectedOnsetMin === expectedOnsetMax
                  ? expectedOnsetMin
                  : `${expectedOnsetMin}–${expectedOnsetMax}`}
              </span>
              <span className="text-sm font-semibold text-foreground">min</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Operational buffer depletion window.
            </p>
          </div>
        </div>

        {/* Signals Evidence */}
        <div className="border-t pt-4 space-y-3">
          <h6 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Contributors &amp; Signals Evidence
          </h6>
          <ul className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
            {evidence.map((item, idx) => {
              const textColors = {
                negative: "text-rose-600 dark:text-rose-400 font-medium",
                positive: "text-emerald-600 dark:text-emerald-400 font-medium",
                neutral: "text-muted-foreground",
              };
              return (
                <li
                  key={idx}
                  className="flex items-center justify-between p-2 rounded border bg-muted/10 font-mono text-xs"
                >
                  <span className="text-muted-foreground truncate mr-2">{item.label}</span>
                  <span className={textColors[item.direction]}>{item.value}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}
