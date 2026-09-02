/**
 * Flow Risk Badge
 *
 * Visual status indicator for a flow prediction's operational urgency.
 * Based on FlowPredictionStatus — not a model threshold label.
 * Frontend/demo categorization only.
 */

import { Badge } from "@/components/ui/badge";
import type { FlowPredictionStatus } from "@/types/flow";
import { cn } from "@/lib/utils";

interface FlowRiskBadgeProps {
  status: FlowPredictionStatus;
  className?: string;
}

export function FlowRiskBadge({ status, className }: FlowRiskBadgeProps) {
  const styles: Record<FlowPredictionStatus, string> = {
    CLEAR:
      "bg-emerald-50 text-emerald-700 border-emerald-200 font-medium",
    WATCH:
      "bg-amber-50 text-amber-700 border-amber-200 font-medium",
    WARNING:
      "bg-orange-50 text-orange-700 border-orange-200 font-semibold",
    CRITICAL:
      "bg-red-50 text-red-700 border-red-200 font-semibold",
  };

  const label: Record<FlowPredictionStatus, string> = {
    CLEAR: "Clear",
    WATCH: "Watch",
    WARNING: "Warning",
    CRITICAL: "Critical",
  };

  return (
    <Badge
      variant="outline"
      className={cn("text-[10px] uppercase tracking-wide px-2 py-0.5", styles[status], className)}
    >
      {label[status]}
    </Badge>
  );
}
