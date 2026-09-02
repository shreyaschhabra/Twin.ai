import Link from "next/link";
import { AlertCircle, AlertTriangle, CheckCircle2, Circle, Info } from "lucide-react";
import { SensorTrustBadge } from "@/features/trust/components/sensor-trust-badge";
import { Badge } from "@/components/ui/badge";
import type { Station, StationState } from "@/types/station";
import type { Vehicle } from "@/types/vehicle";
import type { FlowPrediction } from "@/types/flow";
import { cn } from "@/lib/utils";

interface StationNodeProps {
  station: Station;
  vehicle: Vehicle | null;
  flowPrediction: FlowPrediction | null;
  isDimmed: boolean;
}

export function StationNode({
  station,
  vehicle,
  flowPrediction,
  isDimmed,
}: StationNodeProps) {
  const { id, name, state, sensorTrustState } = station;
  const isHighRiskFlow = flowPrediction && flowPrediction.bottleneckRisk >= 0.50;

  // Icon mapping based on run-states
  const stateIcons: Record<StationState, React.ComponentType<{ className?: string }>> = {
    PROCESSING: CheckCircle2,
    IDLE: Circle,
    BLOCKED: AlertTriangle,
    STARVED: Info,
    DOWN: AlertCircle,
  };

  const StateIcon = stateIcons[state];

  // Color border mapping based on state and risk
  const stateColors = {
    PROCESSING: "border-emerald-500/30 hover:border-emerald-500 bg-emerald-50/5 dark:bg-emerald-500/5",
    IDLE: "border-slate-500/30 hover:border-slate-500 bg-slate-50/5 dark:bg-slate-500/5",
    BLOCKED: "border-amber-500/40 hover:border-amber-500 bg-amber-50/5 dark:bg-amber-500/5",
    STARVED: "border-orange-500/40 hover:border-orange-500 bg-orange-50/5 dark:bg-orange-500/5",
    DOWN: "border-rose-500/50 hover:border-rose-500 bg-rose-50/5 dark:bg-rose-500/5",
  };

  // Construct accessible title label
  const accessibilityLabel = `Station ${id}, ${name}, State: ${state}, Trust State: ${sensorTrustState}${
    isHighRiskFlow ? `, Bottleneck Risk: ${Math.round(flowPrediction.bottleneckRisk * 100)} percent` : ""
  }${vehicle ? `, Vehicle ${vehicle.id} ${vehicle.variant} present` : ""}.`;

  return (
    <Link
      href={`/app/live-twin/stations/${id}`}
      aria-label={accessibilityLabel}
      className={cn(
        "flex flex-col items-stretch text-left border rounded-md p-3 select-none transition-all duration-200 cursor-pointer min-w-[170px] max-w-[210px] shadow-sm relative focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        stateColors[state],
        isDimmed ? "opacity-30 scale-[0.98]" : "opacity-100 scale-100"
      )}
    >
      {/* Node Header */}
      <div className="flex items-center justify-between gap-2 border-b pb-1.5 mb-1.5 font-mono">
        <span className="text-xs font-bold text-foreground">{id}</span>
        <div className="flex items-center gap-1">
          <StateIcon className={cn(
            "h-3.5 w-3.5",
            state === "PROCESSING" && "text-emerald-500",
            state === "IDLE" && "text-slate-400",
            state === "BLOCKED" && "text-amber-500",
            state === "STARVED" && "text-orange-400",
            state === "DOWN" && "text-rose-500"
          )} />
          <span className="text-[9px] uppercase font-semibold text-muted-foreground">
            {state}
          </span>
        </div>
      </div>

      {/* Node Body */}
      <div className="space-y-2 flex-1 flex flex-col justify-between">
        <div>
          <h5 className="text-xs font-semibold text-foreground tracking-tight leading-tight truncate">
            {name}
          </h5>
          <div className="mt-1 flex items-center gap-1.5">
            <SensorTrustBadge trust={sensorTrustState} className="text-[8px] py-0 px-1" />
          </div>
        </div>

        {/* Dynamic Warning and Vehicle markers */}
        <div className="space-y-1 pt-1 border-t border-muted/50 mt-1.5">
          {/* Bottleneck Warning */}
          {isHighRiskFlow && (
            <Badge
              variant="outline"
              className="w-full text-center border-orange-500/20 text-orange-700 dark:text-orange-400 bg-orange-500/5 font-mono text-[9px] py-0 px-1 shrink-0 uppercase tracking-wider block font-bold"
            >
              Risk: {Math.round(flowPrediction.bottleneckRisk * 100)}%
            </Badge>
          )}

          {/* Vehicle marker */}
          {vehicle && (
            <div className={cn(
              "flex items-center justify-between px-1.5 py-0.5 rounded border text-[9px] font-mono",
              vehicle.qualityRisk >= 0.50
                ? "bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20"
                : "bg-muted text-muted-foreground"
            )}>
              <span className="font-bold truncate mr-1">{vehicle.id}</span>
              <span className="text-[8px] uppercase tracking-wider bg-background border px-0.5 rounded-sm">
                {vehicle.variant.replace("ICE_", "")}
              </span>
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
