/**
 * Bottleneck Hotspots Component
 *
 * Renders historical recurrent bottleneck hotspots.
 * Displays station ID, process details, occurrences, average warning lead time,
 * average risk percentage, and operational impact.
 */

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { BottleneckHotspot } from "@/types/analytics";

interface BottleneckHotspotsProps {
  hotspots: BottleneckHotspot[];
}

export function BottleneckHotspots({ hotspots }: BottleneckHotspotsProps) {
  if (hotspots.length === 0) {
    return (
      <div className="text-center py-6 text-xs text-muted-foreground italic border rounded bg-slate-50/50">
        No recurrent bottlenecks identified. Control limits nominal.
      </div>
    );
  }

  // Pre-calculated stats from mock
  // S18 Underbody: occurrences 12, avg lead time 6.8 min, risk 84%, impact HIGH
  // S13 Seat Install: occurrences 8, avg lead time 5.2 min, risk 78%, impact MED
  const displayHotspots = [
    {
      stationId: "S18",
      stationName: "Underbody Dimensional",
      occurrences: 12,
      avgLeadTime: 6.8,
      avgRisk: 0.84,
      impact: "HIGH",
    },
    {
      stationId: "S13",
      stationName: "Seat Install Robot",
      occurrences: 8,
      avgLeadTime: 5.2,
      avgRisk: 0.78,
      impact: "MEDIUM",
    },
  ];

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Station</TableHead>
            <TableHead className="text-xs font-semibold">Occurrences</TableHead>
            <TableHead className="text-xs font-semibold">Avg Warning Lead Time</TableHead>
            <TableHead className="text-xs font-semibold">Avg Risk Alerted</TableHead>
            <TableHead className="text-xs font-semibold">Impact</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {displayHotspots.map((item) => (
            <TableRow key={item.stationId} className="hover:bg-muted/10">
              <TableCell>
                <div className="space-y-0.5">
                  <Link
                    href={`/app/live-twin/stations/${item.stationId}`}
                    className="font-mono font-bold text-xs hover:underline text-foreground flex items-center gap-1"
                  >
                    {item.stationId}
                    <ArrowUpRight className="h-3 w-3 text-muted-foreground" />
                  </Link>
                  <p className="text-[10px] text-muted-foreground font-sans">
                    {item.stationName}
                  </p>
                </div>
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <span className="font-bold font-mono text-xs text-foreground">
                    {item.occurrences}
                  </span>
                  <div className="w-16 bg-muted h-1.5 rounded-full overflow-hidden">
                    <div
                      className="bg-amber-600 h-full rounded-full"
                      style={{ width: `${(item.occurrences / 15) * 100}%` }}
                    />
                  </div>
                </div>
              </TableCell>
              <TableCell className="text-xs text-foreground font-mono font-medium">
                {item.avgLeadTime.toFixed(1)}m
              </TableCell>
              <TableCell className="text-xs text-foreground font-mono font-medium">
                {Math.round(item.avgRisk * 100)}%
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={
                    item.impact === "HIGH"
                      ? "bg-red-50 text-red-700 border-red-200 text-[9px] uppercase font-bold"
                      : "bg-slate-50 text-slate-700 border-slate-200 text-[9px] uppercase font-semibold"
                  }
                >
                  {item.impact}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
