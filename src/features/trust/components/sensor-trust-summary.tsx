import { AlertTriangle, ShieldAlert } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { SensorTrustBadge } from "./sensor-trust-badge";
import { ConfidenceBadge } from "./confidence-badge";
import type { Station } from "@/types/station";
import type { SensorTrustState, ConfidenceLevel } from "@/types/common";

interface SensorTrustSummaryProps {
  stations: Station[];
}

export function SensorTrustSummary({ stations }: SensorTrustSummaryProps) {
  // Aggregate sensor trust states
  const trustCounts: Record<SensorTrustState, number> = {
    LIVE: 0,
    INFERRED: 0,
    UNKNOWN: 0,
  };

  const confidenceCounts: Record<ConfidenceLevel, number> = {
    HIGH: 0,
    MEDIUM: 0,
    LOW: 0,
  };

  for (const s of stations) {
    trustCounts[s.sensorTrustState]++;
    confidenceCounts[s.confidence]++;
  }

  const unknownCount = trustCounts.UNKNOWN;

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-slate-500 shrink-0" />
          Sensor &amp; Prediction Trust
        </CardTitle>
        <CardDescription className="text-xs text-muted-foreground">
          System instrumentation trust indices and prediction bounds.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Sensor Trust breakdown */}
        <div className="space-y-3">
          <h6 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider font-mono">
            Sensor Trust States
          </h6>
          <div className="grid grid-cols-3 gap-3">
            {(["LIVE", "INFERRED", "UNKNOWN"] as SensorTrustState[]).map((state) => (
              <div
                key={state}
                className="flex flex-col items-center p-2 border rounded-md bg-muted/10 font-mono"
              >
                <SensorTrustBadge trust={state} className="mb-2" />
                <span className="text-lg font-bold text-foreground">
                  {trustCounts[state]}
                </span>
                <span className="text-[9px] text-muted-foreground font-sans">
                  {state === "LIVE" ? "Direct feed" : state === "INFERRED" ? "Model proxy" : "No signal"}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Prediction Confidence breakdown */}
        <div className="space-y-3 border-t pt-4">
          <h6 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider font-mono">
            Prediction Confidence
          </h6>
          <div className="grid grid-cols-3 gap-3">
            {(["HIGH", "MEDIUM", "LOW"] as ConfidenceLevel[]).map((level) => (
              <div
                key={level}
                className="flex flex-col items-center p-2 border rounded-md bg-muted/10 font-mono"
              >
                <ConfidenceBadge confidence={level} className="mb-2 text-[8px]" />
                <span className="text-lg font-bold text-foreground">
                  {confidenceCounts[level]}
                </span>
                <span className="text-[9px] text-muted-foreground font-sans">
                  Stations
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Unknown state disclaimer warning */}
        {unknownCount > 0 && (
          <div className="flex gap-2.5 p-3 border border-slate-500/10 bg-slate-500/5 text-slate-700 dark:text-slate-400 rounded-md text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-slate-500" />
            <div className="space-y-1">
              <p className="font-semibold font-mono text-[10px] uppercase tracking-wider">
                Operational Trust Advisory
              </p>
              <p className="font-sans text-muted-foreground leading-normal">
                {unknownCount} stations currently have insufficient live/inferred telemetry.
                Manual floor checks may be required for secondary verification.
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
