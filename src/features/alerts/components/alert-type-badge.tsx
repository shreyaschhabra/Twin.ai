/**
 * Alert Type Badge Component
 *
 * Renders badges for FLOW, QUALITY, SENSOR, and ANOMALY alert kinds.
 */

import { Badge } from "@/components/ui/badge";
import type { AlertKind } from "@/types/common";
import { cn } from "@/lib/utils";

interface AlertTypeBadgeProps {
  kind: AlertKind;
  className?: string;
}

export function AlertTypeBadge({ kind, className }: AlertTypeBadgeProps) {
  const styles: Record<AlertKind, string> = {
    FLOW: "bg-blue-50 text-blue-700 border-blue-200",
    QUALITY: "bg-purple-50 text-purple-700 border-purple-200",
    SENSOR: "bg-slate-50 text-slate-700 border-slate-200",
    ANOMALY: "bg-amber-50 text-amber-700 border-amber-200",
  };

  const label: Record<AlertKind, string> = {
    FLOW: "Flow",
    QUALITY: "Quality",
    SENSOR: "Sensor Trust",
    ANOMALY: "Anomaly",
  };

  return (
    <Badge
      variant="outline"
      className={cn(
        "font-sans text-[10px] tracking-wide px-2 py-0.5 font-medium shrink-0",
        styles[kind],
        className
      )}
    >
      {label[kind]}
    </Badge>
  );
}
