import type { Buffer } from "@/types/buffer";
import { cn } from "@/lib/utils";

interface BufferNodeProps {
  buffer: Buffer;
  className?: string;
}

export function BufferNode({ buffer, className }: BufferNodeProps) {
  const { id, currentWip, capacity } = buffer;

  const occupancyRatio = currentWip / capacity;

  const isFull = currentWip === capacity;
  const isNearCapacity = occupancyRatio >= 0.8 && !isFull;
  const isElevated = occupancyRatio >= 0.5 && occupancyRatio < 0.8;
  const isEmpty = currentWip === 0;

  // Semantic styles for buffer indicators
  const borderStyles = isFull
    ? "border-rose-500 bg-rose-500/10 text-rose-700 dark:text-rose-400 font-bold"
    : isNearCapacity
    ? "border-orange-500 bg-orange-500/10 text-orange-700 dark:text-orange-400 font-bold"
    : isElevated
    ? "border-amber-500 bg-amber-500/5 text-amber-700 dark:text-amber-400 font-medium"
    : isEmpty
    ? "border-slate-500/20 bg-slate-500/5 text-slate-400 dark:text-slate-500"
    : "border-border bg-muted/30 text-muted-foreground";

  return (
    <div
      title={`Buffer ${id} occupancy: ${currentWip} of ${capacity}`}
      className={cn(
        "flex flex-col items-center justify-center border rounded px-2 py-1.5 font-mono select-none text-center min-w-[50px] shadow-sm",
        borderStyles,
        className
      )}
    >
      <span className="text-[8px] font-semibold text-muted-foreground uppercase tracking-widest leading-none">
        {id}
      </span>
      <span className="text-xs font-bold leading-none mt-1">
        {currentWip}/{capacity}
      </span>
    </div>
  );
}
