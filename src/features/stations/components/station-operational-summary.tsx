import { Card, CardContent } from "@/components/ui/card";
import { SensorTrustBadge } from "@/features/trust/components/sensor-trust-badge";
import type { Station } from "@/types/station";
import type { Vehicle } from "@/types/vehicle";
import { cn } from "@/lib/utils";

interface StationOperationalSummaryProps {
  station: Station;
  vehicle: Vehicle | null;
}

export function StationOperationalSummary({
  station,
  vehicle,
}: StationOperationalSummaryProps) {
  const { state, currentCycleTime, baselineCycleTime, sensorTrustState } = station;

  const deviation = currentCycleTime - baselineCycleTime;
  const deviationPct = baselineCycleTime > 0 ? (deviation / baselineCycleTime) * 100 : 0;
  const isElevated = deviationPct >= 10;
  const isDown = state === "DOWN";

  return (
    <div className="grid gap-4 grid-cols-2 lg:grid-cols-6">
      {/* 1. Operating State */}
      <Card className="border bg-card shadow-sm">
        <CardContent className="p-4 font-mono">
          <p className="text-[10px] uppercase text-muted-foreground font-sans font-semibold">
            Current State
          </p>
          <p className={cn(
            "text-base font-bold tracking-tight mt-1.5",
            state === "PROCESSING" && "text-emerald-600 dark:text-emerald-400",
            state === "IDLE" && "text-slate-500",
            state === "BLOCKED" && "text-amber-500",
            state === "STARVED" && "text-orange-400",
            state === "DOWN" && "text-rose-500"
          )}>
            {state}
          </p>
        </CardContent>
      </Card>

      {/* 2. Current Cycle Time */}
      <Card className="border bg-card shadow-sm">
        <CardContent className="p-4 font-mono">
          <p className="text-[10px] uppercase text-muted-foreground font-sans font-semibold">
            Cycle Time
          </p>
          <p className="text-base font-bold tracking-tight mt-1.5 text-foreground">
            {isDown ? "—" : `${currentCycleTime} sec`}
          </p>
        </CardContent>
      </Card>

      {/* 3. Baseline Cycle Time */}
      <Card className="border bg-card shadow-sm">
        <CardContent className="p-4 font-mono">
          <p className="text-[10px] uppercase text-muted-foreground font-sans font-semibold">
            Baseline Target
          </p>
          <p className="text-base font-bold tracking-tight mt-1.5 text-muted-foreground">
            {baselineCycleTime} sec
          </p>
        </CardContent>
      </Card>

      {/* 4. Deviation */}
      <Card className={cn("border bg-card shadow-sm", isElevated && !isDown && "border-rose-500/20 bg-rose-500/5")}>
        <CardContent className="p-4 font-mono">
          <p className="text-[10px] uppercase text-muted-foreground font-sans font-semibold">
            Deviation
          </p>
          <p className={cn(
            "text-base font-bold tracking-tight mt-1.5",
            isDown
              ? "text-muted-foreground"
              : deviationPct > 0
              ? "text-rose-600 dark:text-rose-400"
              : deviationPct < 0
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-muted-foreground"
          )}>
            {isDown ? "—" : deviationPct > 0 ? `+${deviationPct.toFixed(1)}%` : `${deviationPct.toFixed(1)}%`}
          </p>
        </CardContent>
      </Card>

      {/* 5. Current Vehicle */}
      <Card className="border bg-card shadow-sm">
        <CardContent className="p-4 font-mono">
          <p className="text-[10px] uppercase text-muted-foreground font-sans font-semibold">
            Current Vehicle
          </p>
          <p className="text-base font-bold tracking-tight mt-1.5 text-foreground">
            {vehicle ? vehicle.id : "—"}
          </p>
        </CardContent>
      </Card>

      {/* 6. Sensor Trust */}
      <Card className="border bg-card shadow-sm">
        <CardContent className="p-4 font-mono flex flex-col justify-between h-full">
          <p className="text-[10px] uppercase text-muted-foreground font-sans font-semibold">
            Sensor Trust
          </p>
          <div className="mt-2.5">
            <SensorTrustBadge trust={sensorTrustState} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
