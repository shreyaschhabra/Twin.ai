import { CheckCircle2, Circle, AlertTriangle, Info, AlertCircle } from "lucide-react";
import { SensorTrustBadge } from "@/features/trust/components/sensor-trust-badge";
import { Badge } from "@/components/ui/badge";
import type { SensorTrustState } from "@/types/common";

export function LiveTwinLegend() {
  const states = [
    { name: "Processing", desc: "Active cell operations", icon: CheckCircle2, colorClass: "text-emerald-500" },
    { name: "Idle", desc: "Awaiting vehicle entry", icon: Circle, colorClass: "text-slate-400" },
    { name: "Blocked", desc: "Downstream line constrained", icon: AlertTriangle, colorClass: "text-amber-500" },
    { name: "Starved", desc: "Upstream supply limited", icon: Info, colorClass: "text-orange-400" },
    { name: "Offline / Down", desc: "Cell down or maintenance", icon: AlertCircle, colorClass: "text-rose-500" },
  ];

  const trusts: { value: SensorTrustState; desc: string }[] = [
    { value: "LIVE", desc: "Primary telemetry feed active" },
    { value: "INFERRED", desc: "Sensor dropout proxy model" },
    { value: "UNKNOWN", desc: "Telemetry signal missing" },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-6 p-5 border rounded-md bg-card text-card-foreground select-none text-xs w-full">
      {/* ── Group 1: Run-states ── */}
      <div className="space-y-3">
        <h6 className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px] font-mono border-b pb-1.5">
          Station Run States
        </h6>
        <ul className="space-y-2">
          {states.map(({ name, desc, icon: Icon, colorClass }) => (
            <li key={name} className="flex items-start gap-2.5">
              <Icon className={`h-4 w-4 shrink-0 mt-0.5 ${colorClass}`} />
              <div className="flex flex-col">
                <span className="font-semibold text-foreground leading-none">{name}</span>
                <span className="text-[10px] text-muted-foreground leading-normal mt-0.5">{desc}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {/* ── Group 2: Trust-states ── */}
      <div className="space-y-3">
        <h6 className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px] font-mono border-b pb-1.5">
          Telemetry Trust States
        </h6>
        <ul className="space-y-3">
          {trusts.map(({ value, desc }) => (
            <li key={value} className="flex items-start gap-2.5">
              <SensorTrustBadge trust={value} className="shrink-0 mt-0.5 whitespace-nowrap" />
              <div className="flex flex-col">
                <span className="font-semibold text-foreground leading-none">{value}</span>
                <span className="text-[10px] text-muted-foreground leading-normal mt-0.5">{desc}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {/* ── Group 3: Indicators and Warnings ── */}
      <div className="space-y-3 sm:col-span-2 xl:col-span-1">
        <h6 className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px] font-mono border-b pb-1.5">
          Disruption Warnings
        </h6>
        <ul className="space-y-3">
          <li className="flex items-start gap-2.5">
            <Badge
              variant="outline"
              className="border-orange-500/20 text-orange-700 dark:text-orange-400 bg-orange-500/5 text-[8px] py-0.5 px-1.5 font-bold shrink-0 mt-0.5 whitespace-nowrap font-mono tracking-wider"
            >
              RISK: 87%
            </Badge>
            <div className="flex flex-col">
              <span className="font-semibold text-foreground leading-none">Bottleneck Risk</span>
              <span className="text-[10px] text-muted-foreground leading-normal mt-0.5">
                Elevated cycle-time bottleneck risk probability warning.
              </span>
            </div>
          </li>
          <li className="flex items-start gap-2.5">
            <div className="flex items-center justify-between px-1.5 py-0.5 rounded border border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-400 text-[8px] font-bold shrink-0 mt-0.5 whitespace-nowrap font-mono">
              V2048 <span className="text-[7px] uppercase tracking-wider ml-1 bg-background border px-0.5 rounded-sm">EV</span>
            </div>
            <div className="flex flex-col">
              <span className="font-semibold text-foreground leading-none">High Quality Risk</span>
              <span className="text-[10px] text-muted-foreground leading-normal mt-0.5">
                Active assembly carrying elevated defect probability.
              </span>
            </div>
          </li>
        </ul>
      </div>
    </div>
  );
}
