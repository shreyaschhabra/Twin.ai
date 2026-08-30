import { Wrench } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import type { StationMaintenance } from "@/types/station";
import { cn } from "@/lib/utils";

interface StationMaintenanceCardProps {
  maintenance: StationMaintenance | null;
}

export function StationMaintenanceCard({ maintenance }: StationMaintenanceCardProps) {
  if (!maintenance) {
    return (
      <Card className="border bg-card text-card-foreground shadow-sm">
        <CardContent className="p-8 text-center text-xs text-muted-foreground font-mono">
          No maintenance logging available for this station.
        </CardContent>
      </Card>
    );
  }

  const { hoursSinceMaintenance, toolAgePercent, recentMinorStopsCount, needsAttention } = maintenance;

  return (
    <Card className={cn("border bg-card text-card-foreground shadow-sm", needsAttention && "border-amber-500/20 bg-amber-500/5")}>
      <CardHeader className="pb-4">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <Wrench className="h-4 w-4 text-slate-500 shrink-0" />
          Maintenance Context
        </CardTitle>
        <CardDescription className="text-xs text-muted-foreground">
          Observed asset life stats and minor stoppages indicators.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 font-mono text-xs select-none">
        {/* Hours since maintenance */}
        <div className="flex items-center justify-between border-b pb-2">
          <span className="text-muted-foreground font-sans">Operating Hours Since Service</span>
          <span className="font-bold text-foreground">{hoursSinceMaintenance} hrs</span>
        </div>

        {/* Recent stops */}
        <div className="flex items-center justify-between border-b pb-2">
          <span className="text-muted-foreground font-sans">Minor Stops (Last 30 Min)</span>
          <span className={cn(
            "font-bold",
            recentMinorStopsCount > 2 ? "text-rose-500" : "text-foreground"
          )}>
            {recentMinorStopsCount}
          </span>
        </div>

        {/* Tool Age Progress */}
        <div className="space-y-2 pt-1">
          <div className="flex justify-between font-mono text-xs">
            <span className="text-muted-foreground font-sans">Mechanical Tool Age Wear</span>
            <span className="font-bold text-foreground">{toolAgePercent}%</span>
          </div>
          <div className="w-full bg-muted dark:bg-muted/30 rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-sky-500 h-full rounded-full transition-all duration-300"
              style={{ width: `${toolAgePercent}%` }}
            />
          </div>
        </div>

        {/* Needs attention warning banner */}
        {needsAttention && (
          <div className="p-3 border border-amber-500/20 bg-amber-500/5 rounded text-[11px] text-amber-700 dark:text-amber-400 font-sans leading-normal">
            <strong>Advisory condition observed:</strong> Scheduled mechanical wear limits approach. Minor calibration or lubrication cycles may be planned during upcoming changeovers.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
