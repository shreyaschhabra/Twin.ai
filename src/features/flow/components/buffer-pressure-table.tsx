/**
 * Buffer Pressure Table
 *
 * Shows buffers adjacent to elevated flow-risk stations.
 * Occupancy bar uses restrained display — frontend thresholds only.
 */

import Link from "next/link";
import type { Buffer } from "@/types/buffer";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

interface BufferPressureTableProps {
  buffers: Buffer[];
}

function occupancyBar(ratio: number) {
  const pct = Math.round(ratio * 100);
  const filled = Math.round(ratio * 10);
  const empty = 10 - filled;
  const barClass =
    pct >= 85
      ? "text-red-600"
      : pct >= 65
      ? "text-amber-600"
      : "text-emerald-600";
  return (
    <span className={cn("font-mono text-xs", barClass)} aria-label={`${pct}% occupied`}>
      {"█".repeat(filled)}{"░".repeat(empty)} {pct}%
    </span>
  );
}

function trendLabel(growthRate?: number) {
  if (growthRate === undefined || growthRate === null) return "—";
  if (growthRate > 0) return <span className="text-red-700 text-xs font-medium">Growing ↑</span>;
  if (growthRate < 0) return <span className="text-emerald-700 text-xs font-medium">Draining ↓</span>;
  return <span className="text-muted-foreground text-xs">Stable</span>;
}

function statusLabel(status: string) {
  switch (status) {
    case "FILLING":
      return <span className="text-red-700 font-medium text-xs">Filling</span>;
    case "CRITICAL":
      return <span className="text-red-700 font-bold text-xs">Critical</span>;
    case "EMPTY":
      return <span className="text-muted-foreground text-xs">Empty</span>;
    default:
      return <span className="text-emerald-700 text-xs">Normal</span>;
  }
}

export function BufferPressureTable({ buffers }: BufferPressureTableProps) {
  if (buffers.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic text-center py-6">
        No buffers near capacity for monitored flow predictions.
      </p>
    );
  }

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Buffer</TableHead>
            <TableHead className="text-xs font-semibold">Route</TableHead>
            <TableHead className="text-xs font-semibold">WIP / Cap</TableHead>
            <TableHead className="text-xs font-semibold">Occupancy</TableHead>
            <TableHead className="text-xs font-semibold">Trend</TableHead>
            <TableHead className="text-xs font-semibold">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {buffers.map((buf) => (
            <TableRow
              key={buf.id}
              className={cn(
                "hover:bg-muted/20 transition-colors",
                buf.occupancyRatio >= 0.85 && "bg-red-50/40",
                buf.occupancyRatio >= 0.65 && buf.occupancyRatio < 0.85 && "bg-amber-50/20",
              )}
            >
              <TableCell className="font-mono font-semibold text-xs">
                {buf.id}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <Link
                    href={`/app/live-twin/stations/${buf.upstreamStationId}`}
                    className="font-mono hover:underline text-foreground"
                  >
                    {buf.upstreamStationId}
                  </Link>
                  <span>→</span>
                  <Link
                    href={`/app/live-twin/stations/${buf.downstreamStationId}`}
                    className="font-mono hover:underline text-foreground"
                  >
                    {buf.downstreamStationId}
                  </Link>
                </span>
              </TableCell>
              <TableCell className="text-xs tabular-nums font-semibold">
                {buf.currentWip}{" "}
                <span className="text-muted-foreground font-normal">/ {buf.capacity}</span>
              </TableCell>
              <TableCell>{occupancyBar(buf.occupancyRatio)}</TableCell>
              <TableCell>{trendLabel(buf.growthRate)}</TableCell>
              <TableCell>{statusLabel(buf.status)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
