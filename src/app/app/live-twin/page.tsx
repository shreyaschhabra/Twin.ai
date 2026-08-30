import {
  getStations,
  getBuffers,
  getVehicles,
  getFlowPredictions,
} from "@/features/services";
import { LiveTwinCanvas } from "@/features/twin/components/live-twin-canvas";
import type { StationState } from "@/types/station";
import type { SensorTrustState } from "@/types/common";
import { cn } from "@/lib/utils";

export const revalidate = 0; // Disable server rendering cache for active updates

export default async function LiveTwinPage() {
  // Fetch mock-backed data from feature services server-side
  const stations = await getStations();
  const buffers = await getBuffers();
  const vehicles = await getVehicles();
  const flowPreds = await getFlowPredictions();

  // DERIVE OPERATIONAL STATUS COUNTS FOR SUMMARY HEADER
  const stateCounts: Record<StationState, number> = {
    PROCESSING: 0, IDLE: 0, BLOCKED: 0, STARVED: 0, DOWN: 0,
  };
  const trustCounts: Record<SensorTrustState, number> = {
    LIVE: 0, INFERRED: 0, UNKNOWN: 0,
  };

  for (const s of stations) {
    stateCounts[s.state] = (stateCounts[s.state] || 0) + 1;
    trustCounts[s.sensorTrustState] = (trustCounts[s.sensorTrustState] || 0) + 1;
  }

  const activeStateList: { label: string; count: number; colorClass: string }[] = [
    { label: "Processing", count: stateCounts.PROCESSING, colorClass: "bg-emerald-500" },
    { label: "Idle", count: stateCounts.IDLE, colorClass: "bg-slate-400" },
    { label: "Blocked", count: stateCounts.BLOCKED, colorClass: "bg-amber-500" },
    { label: "Starved", count: stateCounts.STARVED, colorClass: "bg-orange-400" },
    { label: "Down", count: stateCounts.DOWN, colorClass: "bg-rose-500" },
  ];

  const activeTrustList: { label: string; count: number; badgeColorClass: string }[] = [
    { label: "LIVE", count: trustCounts.LIVE, badgeColorClass: "border-emerald-500/20 text-emerald-700 dark:text-emerald-400 bg-emerald-500/5" },
    { label: "INFERRED", count: trustCounts.INFERRED, badgeColorClass: "border-blue-500/20 text-blue-700 dark:text-blue-400 bg-blue-500/5" },
    { label: "UNKNOWN", count: trustCounts.UNKNOWN, badgeColorClass: "border-slate-500/20 text-slate-700 dark:text-slate-400 bg-slate-500/5" },
  ];

  return (
    <div className="space-y-6">
      {/* ── ROUTE HEADER ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Live Twin Topology</h1>
          <p className="text-xs text-muted-foreground mt-1">
            Real-time operational layout of the {stations.length}-station production line.
          </p>
        </div>
      </div>

      {/* ── RUN-STATE & TRUST COUNTS SUMMARY PANEL ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 border p-4 rounded bg-card text-card-foreground shadow-sm font-mono text-[10px] select-none">
        {/* Total stats */}
        <div className="flex flex-col justify-center border-b pb-3 sm:border-b-0 sm:pb-0 sm:border-r sm:pr-4">
          <span className="text-muted-foreground uppercase font-semibold">Total Line Scope</span>
          <span className="text-xl font-bold text-foreground mt-1">{stations.length} stations</span>
          <span className="text-muted-foreground">{buffers.length} buffers · {vehicles.length} tracked</span>
        </div>

        {/* Operating States breakdown */}
        <div className="flex flex-col justify-center border-b pb-3 sm:border-b-0 sm:pb-0 sm:border-r sm:pr-4 col-span-2">
          <span className="text-muted-foreground uppercase font-semibold mb-2">Cell Run-states</span>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {activeStateList.map(({ label, count, colorClass }) => (
              <div key={label} className="flex items-center gap-1.5 text-xs font-semibold">
                <span className={`h-2 w-2 rounded-full ${colorClass}`} />
                <span className="text-muted-foreground font-sans font-normal">{label}:</span>
                <span className="text-foreground">{count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Sensor Trust breakdown */}
        <div className="flex flex-col justify-center">
          <span className="text-muted-foreground uppercase font-semibold mb-2">Telemetry Trust Summary</span>
          <div className="flex items-center gap-3">
            {activeTrustList.map(({ label, count, badgeColorClass }) => (
              <div key={label} className={cn("flex flex-col items-center border rounded px-2 py-0.5 min-w-[45px] bg-muted/10", badgeColorClass)}>
                <span className="text-[8px] font-sans font-normal text-muted-foreground leading-none">{label}</span>
                <span className="text-xs font-bold leading-none mt-1">{count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── TOPOLOGY CANVAS AND SELECTION SHEET ── */}
      <LiveTwinCanvas
        stations={stations}
        buffers={buffers}
        vehicles={vehicles}
        flowPredictions={flowPreds}
      />
    </div>
  );
}
