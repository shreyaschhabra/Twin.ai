import Link from "next/link";
import { Network } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import type { Station, StationState } from "@/types/station";

interface LineHealthSummaryProps {
  stations: Station[];
}

export function LineHealthSummary({ stations }: LineHealthSummaryProps) {
  // Aggregate station states
  const counts: Record<StationState, number> = {
    PROCESSING: 0,
    IDLE: 0,
    BLOCKED: 0,
    STARVED: 0,
    DOWN: 0,
  };

  for (const s of stations) {
    counts[s.state] = (counts[s.state] || 0) + 1;
  }

  const statesList: { label: string; state: StationState; colorClass: string }[] = [
    { label: "Active Processing", state: "PROCESSING", colorClass: "bg-emerald-500" },
    { label: "Idle / Standby", state: "IDLE", colorClass: "bg-slate-400" },
    { label: "Blocked Downstream", state: "BLOCKED", colorClass: "bg-amber-500" },
    { label: "Starved Upstream", state: "STARVED", colorClass: "bg-orange-400" },
    { label: "Offline / Down", state: "DOWN", colorClass: "bg-rose-500" },
  ];

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4">
        <div>
          <CardTitle className="text-base font-semibold">Assembly Line Health</CardTitle>
          <CardDescription className="text-xs text-muted-foreground">
            Aggregated station run-states across all 45 cells.
          </CardDescription>
        </div>
        <Link
          href="/app/live-twin"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-3 text-xs font-medium text-foreground hover:bg-accent transition-colors self-start sm:self-center"
        >
          <Network className="h-3.5 w-3.5" />
          View Live Twin
        </Link>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Status bars */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {statesList.map(({ label, state, colorClass }) => (
            <div
              key={state}
              className="flex flex-col gap-1.5 p-3 rounded-md border bg-muted/20 font-mono text-center"
            >
              <div className="flex items-center justify-center gap-1.5">
                <span className={`h-2.5 w-2.5 rounded-full ${colorClass}`} />
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  {state}
                </span>
              </div>
              <span className="text-xl font-bold tracking-tight">{counts[state]}</span>
              <span className="text-[9px] text-muted-foreground font-sans truncate">
                {label}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
