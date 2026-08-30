/**
 * Vehicle Genealogy Timeline
 *
 * Vertical production timeline — one entry per station visited.
 * - COMPLETE stations: shows timestamps, risk, trust, anomaly exposure.
 * - IN_PROGRESS station: rendered with distinct "current position" styling.
 * - Future stations: not shown (no telemetry leakage).
 */

import Link from "next/link";
import type { VehicleGenealogyEvent } from "@/types/vehicle";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface VehicleGenealogyTimelineProps {
  genealogy: VehicleGenealogyEvent[];
  currentStationId: string;
}

function formatTime(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

function trustBadge(state: string, processStatus: string) {
  if (processStatus === "IN_PROGRESS") {
    if (state === "UNKNOWN")
      return (
        <Badge className="bg-slate-100 text-slate-600 border-slate-200 text-[10px] px-1.5 py-0">
          Unavailable
        </Badge>
      );
    if (state === "INFERRED")
      return (
        <Badge className="bg-amber-100 text-amber-700 border-amber-200 text-[10px] px-1.5 py-0">
          Inferred (proxy)
        </Badge>
      );
    return (
      <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200 text-[10px] px-1.5 py-0">
        Live
      </Badge>
    );
  }
  switch (state) {
    case "LIVE":
      return (
        <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200 text-[10px] px-1.5 py-0">
          Live
        </Badge>
      );
    case "INFERRED":
      return (
        <Badge className="bg-amber-100 text-amber-700 border-amber-200 text-[10px] px-1.5 py-0">
          Inferred (proxy)
        </Badge>
      );
    case "UNKNOWN":
      return (
        <Badge className="bg-slate-100 text-slate-600 border-slate-200 text-[10px] px-1.5 py-0">
          Unavailable
        </Badge>
      );
    default:
      return null;
  }
}

function riskColorClass(risk: number) {
  if (risk >= 0.5) return "text-red-700 font-semibold";
  if (risk >= 0.2) return "text-amber-700 font-semibold";
  return "text-emerald-700 font-medium";
}

export function VehicleGenealogyTimeline({
  genealogy,
  currentStationId,
}: VehicleGenealogyTimelineProps) {
  if (genealogy.length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">
        No genealogy events recorded.
      </p>
    );
  }

  return (
    <ol className="relative border-l border-border ml-3 space-y-0">
      {genealogy.map((event, idx) => {
        const isCurrent =
          event.stationId === currentStationId &&
          event.processStatus === "IN_PROGRESS";
        const isComplete = event.processStatus === "COMPLETE";
        const isLast = idx === genealogy.length - 1;

        return (
          <li key={`${event.stationId}-${idx}`} className="mb-0 ml-6">
            {/* Timeline dot */}
            <span
              className={cn(
                "absolute -left-3 flex h-6 w-6 items-center justify-center rounded-full ring-4 ring-background",
                isCurrent
                  ? "bg-blue-600"
                  : isComplete
                  ? "bg-emerald-600"
                  : "bg-slate-300",
              )}
            >
              {isCurrent ? (
                <Loader2 className="h-3 w-3 text-white animate-spin" />
              ) : isComplete ? (
                <CheckCircle2 className="h-3 w-3 text-white" />
              ) : (
                <span className="h-2 w-2 rounded-full bg-slate-400" />
              )}
            </span>

            {/* Event card */}
            <div
              className={cn(
                "mb-4 ml-2 p-3 rounded-md border",
                isCurrent
                  ? "border-blue-200 bg-blue-50/60"
                  : "border-border bg-card",
              )}
            >
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      href={`/app/live-twin/stations/${event.stationId}`}
                      className="text-sm font-semibold hover:underline"
                    >
                      {event.stationName}
                    </Link>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {event.stationId}
                    </span>
                    {isCurrent && (
                      <Badge className="bg-blue-100 text-blue-800 border-blue-200 text-[10px] px-1.5 py-0">
                        Current Position
                      </Badge>
                    )}
                    {event.anomalyExposure && (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-700 font-medium">
                        <AlertTriangle className="h-3 w-3" />
                        Anomaly Window
                      </span>
                    )}
                  </div>

                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                    <span>
                      Entered:{" "}
                      <span className="text-foreground font-mono text-[11px]">
                        {formatTime(event.enteredAt)}
                      </span>
                    </span>
                    {event.exitedAt && (
                      <span>
                        Exited:{" "}
                        <span className="text-foreground font-mono text-[11px]">
                          {formatTime(event.exitedAt)}
                        </span>
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex flex-col items-end gap-1 shrink-0">
                  {/* Cumulative risk after station */}
                  <span
                    className={cn(
                      "text-sm tabular-nums",
                      riskColorClass(event.qualityRiskAfterStation),
                    )}
                  >
                    {(event.qualityRiskAfterStation * 100).toFixed(0)}% risk
                  </span>
                  {/* Sensor trust */}
                  {trustBadge(event.sensorTrustState, event.processStatus)}
                </div>
              </div>

              {/* UNKNOWN sensor disclosure */}
              {event.sensorTrustState === "UNKNOWN" && (
                <p className="mt-2 text-[10px] text-muted-foreground border-t pt-2">
                  Sensor data unavailable at this station during this passage.
                  Risk figure is carried forward from previous station.
                </p>
              )}

              {/* INFERRED sensor disclosure */}
              {event.sensorTrustState === "INFERRED" && (
                <p className="mt-2 text-[10px] text-muted-foreground border-t pt-2">
                  Risk estimate based on proxy signals — direct sensor data was
                  not available at this station. Treat with additional caution.
                </p>
              )}
            </div>

            {/* Spacer between events */}
            {!isLast && <div className="ml-2 h-1" />}
          </li>
        );
      })}
    </ol>
  );
}
