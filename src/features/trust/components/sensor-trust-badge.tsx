import { Badge } from "@/components/ui/badge";
import type { SensorTrustState } from "@/types/common";
import { cn } from "@/lib/utils";

interface SensorTrustBadgeProps {
  trust: SensorTrustState;
  className?: string;
}

export function SensorTrustBadge({ trust, className }: SensorTrustBadgeProps) {
  const styles: Record<SensorTrustState, string> = {
    LIVE: "bg-emerald-50/50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400 border-emerald-500/20 dark:border-emerald-400/20",
    INFERRED: "bg-blue-50/50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-400 border-blue-500/20 dark:border-blue-400/20",
    UNKNOWN: "bg-slate-50/50 text-slate-700 dark:bg-slate-500/10 dark:text-slate-400 border-slate-500/20 dark:border-slate-400/20",
  };

  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono text-[10px] tracking-wide uppercase px-2 py-0.5",
        styles[trust],
        className
      )}
    >
      {trust}
    </Badge>
  );
}
