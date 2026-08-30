/**
 * Alert Severity Badge Component
 *
 * Renders badges for CRITICAL, WARNING, WATCH, and INFO alert severities.
 * Visual status is distinguished by label, styling, and icon rather than color alone.
 */

import { AlertOctagon, AlertTriangle, Eye, Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AlertSeverity } from "@/types/common";
import { cn } from "@/lib/utils";

interface AlertSeverityBadgeProps {
  severity: AlertSeverity;
  className?: string;
}

export function AlertSeverityBadge({ severity, className }: AlertSeverityBadgeProps) {
  const styles: Record<AlertSeverity, string> = {
    CRITICAL: "bg-red-50 text-red-700 border-red-200 font-bold",
    WARNING: "bg-orange-50 text-orange-700 border-orange-200 font-semibold",
    WATCH: "bg-amber-50 text-amber-700 border-amber-200 font-medium",
    INFO: "bg-slate-50 text-slate-700 border-slate-200 font-medium",
  };

  const icons: Record<AlertSeverity, React.ReactNode> = {
    CRITICAL: <AlertOctagon className="h-3 w-3 text-red-700 shrink-0" aria-label="Critical Alert" />,
    WARNING: <AlertTriangle className="h-3 w-3 text-orange-700 shrink-0" aria-label="Warning Alert" />,
    WATCH: <Eye className="h-3 w-3 text-amber-700 shrink-0" aria-label="Watch Alert" />,
    INFO: <Info className="h-3 w-3 text-slate-700 shrink-0" aria-label="Info Alert" />,
  };

  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono text-[9px] tracking-wider uppercase px-2 py-0.5 inline-flex items-center gap-1 shrink-0",
        styles[severity],
        className
      )}
    >
      {icons[severity]}
      <span>{severity}</span>
    </Badge>
  );
}
