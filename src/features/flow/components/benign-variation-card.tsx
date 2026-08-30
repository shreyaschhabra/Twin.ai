/**
 * Benign Variation Card
 *
 * Surfaces monitored flow predictions with WATCH status that are NOT
 * expected to escalate to operational bottlenecks.
 *
 * This is critical for operator trust — elevated cycle time alone
 * does NOT automatically equal a critical bottleneck.
 */

import Link from "next/link";
import type { FlowPrediction } from "@/types/flow";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import { FlowRiskBadge } from "./flow-risk-badge";
import { cn } from "@/lib/utils";
import { Info } from "lucide-react";

interface BenignVariationCardProps {
  prediction: FlowPrediction;
}

export function BenignVariationCard({ prediction }: BenignVariationCardProps) {
  const riskPct = Math.round(prediction.bottleneckRisk * 100);

  return (
    <Card className="border shadow-none bg-slate-50/60">
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <Info className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
              <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Monitored Variation
              </CardTitle>
            </div>
            <div className="flex items-center gap-2 flex-wrap mt-1">
              <span className="text-sm font-bold font-mono">{prediction.stationId}</span>
              <span className="text-sm text-muted-foreground">{prediction.stationName}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <FlowRiskBadge status={prediction.status} />
            <ConfidenceBadge confidence={prediction.confidence} />
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-4 pb-4 space-y-3">
        {/* Risk display — clearly low/watch, not critical */}
        <div className="flex items-center gap-4 flex-wrap">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Flow Risk
            </p>
            <p
              className={cn(
                "text-xl font-bold tabular-nums",
                riskPct >= 50 ? "text-red-700" : riskPct >= 20 ? "text-amber-700" : "text-emerald-700",
              )}
            >
              {riskPct}%
            </p>
          </div>
          {prediction.expectedOnsetMin > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Onset Estimate
              </p>
              <p className="text-sm font-semibold">
                {prediction.expectedOnsetMin === prediction.expectedOnsetMax
                  ? `${prediction.expectedOnsetMin} min`
                  : `${prediction.expectedOnsetMin}–${prediction.expectedOnsetMax} min`}
              </p>
            </div>
          )}
        </div>

        {/* Evidence */}
        <div className="space-y-1">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
            Observed Signals
          </p>
          <ul className="space-y-1">
            {prediction.evidence.map((item, idx) => (
              <li key={idx} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{item.label}</span>
                <span
                  className={cn(
                    "font-medium font-mono",
                    item.direction === "negative"
                      ? "text-amber-700"
                      : item.direction === "positive"
                      ? "text-emerald-700"
                      : "text-muted-foreground",
                  )}
                >
                  {item.value}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Benign assessment message */}
        <div className="rounded border bg-slate-100/60 px-3 py-2 text-xs text-muted-foreground border-slate-200">
          <p>
            Current variation is consistent with expected load patterns and is
            not projected to create meaningful system-level bottleneck impact.
            No escalation action required at this time.
          </p>
        </div>

        <Link
          href={`/app/live-twin/stations/${prediction.stationId}`}
          className="inline-flex text-xs text-muted-foreground hover:text-foreground hover:underline transition-colors"
        >
          View station {prediction.stationId} →
        </Link>
      </CardContent>
    </Card>
  );
}
