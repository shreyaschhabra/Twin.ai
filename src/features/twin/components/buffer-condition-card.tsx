import { Database } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import type { Buffer } from "@/types/buffer";
import { cn } from "@/lib/utils";

interface BufferConditionCardProps {
  upstream: Buffer | null;
  downstream: Buffer | null;
}

export function BufferConditionCard({ upstream, downstream }: BufferConditionCardProps) {
  const renderBufferDetails = (buffer: Buffer | null, label: "Upstream Buffer" | "Downstream Buffer") => {
    if (!buffer) {
      return (
        <div className="p-4 border border-dashed rounded text-center text-xs text-muted-foreground font-mono bg-muted/5">
          [ No {label.toLowerCase()} linked ]
        </div>
      );
    }

    const { id, currentWip, capacity } = buffer;
    const ratio = currentWip / capacity;

    const isFull = currentWip === capacity;
    const isNearCapacity = ratio >= 0.8 && !isFull;
    const isElevated = ratio >= 0.5 && ratio < 0.8;
    const isEmpty = currentWip === 0;

    const statusText = isFull
      ? "Full"
      : isNearCapacity
      ? "Near Capacity"
      : isElevated
      ? "Elevated"
      : isEmpty
      ? "Empty"
      : "Normal";

    const blockColorClass = isFull
      ? "bg-rose-500 border-rose-600"
      : isNearCapacity
      ? "bg-orange-500 border-orange-600"
      : isElevated
      ? "bg-amber-500 border-amber-600"
      : "bg-emerald-500 border-emerald-600";

    return (
      <div className="p-4 border rounded-md bg-muted/10 space-y-3 font-mono">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground font-sans uppercase font-bold">
            {label} ({id})
          </span>
          <span className={cn(
            "text-[9px] uppercase font-bold px-1.5 py-0.5 rounded border font-sans",
            isFull && "border-rose-500/20 text-rose-700 bg-rose-500/5 dark:text-rose-400",
            isNearCapacity && "border-orange-500/20 text-orange-700 bg-orange-500/5 dark:text-orange-400",
            isElevated && "border-amber-500/20 text-amber-700 bg-amber-500/5 dark:text-amber-400",
            isEmpty && "border-slate-500/20 text-slate-600 bg-slate-500/5 dark:text-slate-400",
            !isFull && !isNearCapacity && !isElevated && !isEmpty && "border-emerald-500/20 text-emerald-700 bg-emerald-500/5 dark:text-emerald-400"
          )}>
            {statusText}
          </span>
        </div>

        <div className="flex items-baseline justify-between">
          <span className="text-sm font-bold text-foreground">
            {currentWip} / {capacity}
          </span>
          <span className="text-[10px] text-muted-foreground font-semibold">
            {Math.round(ratio * 100)}% WIP Load
          </span>
        </div>

        {/* Custom occupancy block meter */}
        <div className="flex items-center gap-1">
          {Array.from({ length: capacity }).map((_, i) => (
            <span
              key={i}
              className={cn(
                "h-4 w-2.5 rounded-sm border shrink-0",
                i < currentWip ? blockColorClass : "bg-muted border-border"
              )}
            />
          ))}
        </div>
      </div>
    );
  };

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <Database className="h-4 w-4 text-slate-500 shrink-0" />
          Buffer Conditions
        </CardTitle>
        <CardDescription className="text-xs text-muted-foreground">
          Upstream and downstream storage WIP constraints.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {renderBufferDetails(upstream, "Upstream Buffer")}
        {renderBufferDetails(downstream, "Downstream Buffer")}
      </CardContent>
    </Card>
  );
}
