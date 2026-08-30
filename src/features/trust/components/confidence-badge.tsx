import { Badge } from "@/components/ui/badge";
import type { ConfidenceLevel } from "@/types/common";
import { cn } from "@/lib/utils";

interface ConfidenceBadgeProps {
  confidence: ConfidenceLevel;
  className?: string;
}

export function ConfidenceBadge({ confidence, className }: ConfidenceBadgeProps) {
  const styles: Record<ConfidenceLevel, string> = {
    HIGH: "bg-emerald-50/50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400 border-emerald-500/20 dark:border-emerald-400/20",
    MEDIUM: "bg-amber-50/50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400 border-amber-500/20 dark:border-amber-400/20",
    LOW: "bg-rose-50/50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-400 border-rose-500/20 dark:border-rose-400/20",
  };

  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono text-[10px] tracking-wide uppercase px-2 py-0.5",
        styles[confidence],
        className
      )}
    >
      {confidence} CONFIDENCE
    </Badge>
  );
}
