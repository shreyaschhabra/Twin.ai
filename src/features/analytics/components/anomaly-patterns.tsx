/**
 * Anomaly Patterns Component
 *
 * Displays recurrent anomaly patterns (such as signal drift or deviation events)
 * at stations along with frequency metrics, duration, and exposed vehicle counts.
 */

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { AnomalyPattern } from "@/types/analytics";

interface AnomalyPatternsProps {
  patterns: AnomalyPattern[];
}

export function AnomalyPatterns({ patterns }: AnomalyPatternsProps) {
  if (patterns.length === 0) {
    return (
      <div className="text-center py-6 text-xs text-muted-foreground italic border rounded bg-slate-50/50">
        No recurring anomaly patterns identified.
      </div>
    );
  }

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Station</TableHead>
            <TableHead className="text-xs font-semibold">Anomaly Pattern</TableHead>
            <TableHead className="text-xs font-semibold text-center">Occurrences</TableHead>
            <TableHead className="text-xs font-semibold">Avg Duration</TableHead>
            <TableHead className="text-xs font-semibold text-center">Exposed Assemblies</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {patterns.map((item, idx) => (
            <TableRow key={idx} className="hover:bg-muted/10">
              <TableCell>
                <div className="space-y-0.5">
                  <Link
                    href={`/app/live-twin/stations/${item.stationId}`}
                    className="font-mono font-bold text-xs hover:underline text-foreground flex items-center gap-1"
                  >
                    {item.stationId}
                    <ArrowUpRight className="h-3 w-3 text-muted-foreground" />
                  </Link>
                  <p className="text-[10px] text-muted-foreground font-sans truncate max-w-[150px]">
                    {item.stationName}
                  </p>
                </div>
              </TableCell>
              <TableCell className="text-xs text-foreground font-medium font-mono">
                {item.anomalyType}
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-semibold text-foreground">
                {item.occurrences}
              </TableCell>
              <TableCell className="text-xs text-foreground font-mono font-medium">
                {item.avgDurationMin} min
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                {item.vehiclesExposed}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
