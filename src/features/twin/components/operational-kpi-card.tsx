import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface OperationalKpiCardProps {
  label: string;
  value: string | number;
  contextText?: string;
  status?: "normal" | "watch" | "warning" | "critical";
  className?: string;
}

export function OperationalKpiCard({
  label,
  value,
  contextText,
  status = "normal",
  className,
}: OperationalKpiCardProps) {
  const borderStyles = {
    normal: "border-border",
    watch: "border-amber-500/20 dark:border-amber-400/20",
    warning: "border-orange-500/40 dark:border-orange-400/40",
    critical: "border-rose-500/50 dark:border-rose-400/50",
  };

  const dotColors = {
    normal: "bg-emerald-500",
    watch: "bg-amber-500",
    warning: "bg-orange-500",
    critical: "bg-rose-500",
  };

  return (
    <Card className={cn("border bg-card text-card-foreground shadow-sm relative overflow-hidden", borderStyles[status], className)}>
      <CardContent className="p-4 md:p-6 space-y-1">
        {/* Status indicator pill on top right */}
        <div className="absolute top-4 right-4 flex items-center gap-1.5">
          <span className={cn("h-2 w-2 rounded-full", dotColors[status])} />
          <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            {status}
          </span>
        </div>

        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {label}
        </p>
        <h4 className="text-2xl font-bold tracking-tight text-foreground pt-1">
          {value}
        </h4>
        {contextText && (
          <p className="text-xs text-muted-foreground font-medium pt-1">
            {contextText}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
