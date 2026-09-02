/**
 * Maintenance Candidates Component
 *
 * Surfaces stations for potential operational/quality investigation candidates.
 * Uses cautious wording suited for diagnostic review rather than predictive alerts.
 */

import Link from "next/link";
import { ArrowUpRight, Wrench } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { MaintenanceCandidate } from "@/types/analytics";

interface MaintenanceCandidatesProps {
  candidates: MaintenanceCandidate[];
}

export function MaintenanceCandidates({ candidates }: MaintenanceCandidatesProps) {
  if (candidates.length === 0) {
    return (
      <div className="text-center py-6 text-xs text-muted-foreground italic border rounded bg-slate-50/50">
        No maintenance candidates identified. Tool wear parameters nominal.
      </div>
    );
  }

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Station</TableHead>
            <TableHead className="text-xs font-semibold">Reason for Review</TableHead>
            <TableHead className="text-xs font-semibold text-center">Flow Warnings</TableHead>
            <TableHead className="text-xs font-semibold text-center">Quality Exposure</TableHead>
            <TableHead className="text-xs font-semibold text-center">Minor Stops</TableHead>
            <TableHead className="text-xs font-semibold">Tool Wear Estimate</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {candidates.map((item) => (
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
                  <p className="text-[10px] text-muted-foreground font-sans truncate max-w-[150px]">
                    {item.stationName}
                  </p>
                </div>
              </TableCell>
              <TableCell className="text-xs text-foreground font-medium max-w-[200px]">
                {item.reason}
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                {item.flowEvents}
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                {item.qualityExposure}
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                {item.minorStops}
              </TableCell>
              <TableCell>
                <div className="space-y-1 py-1">
                  <div className="flex items-center justify-between text-[9px] font-mono text-muted-foreground">
                    <span>Age</span>
                    <span className={item.maintenanceAgePercent >= 80 ? "text-amber-700 font-bold" : ""}>
                      {item.maintenanceAgePercent}%
                    </span>
                  </div>
                  <div className="w-20 bg-muted h-1 rounded-full overflow-hidden">
                    <div
                      className={
                        item.maintenanceAgePercent >= 80
                          ? "bg-amber-600 h-full rounded-full"
                          : "bg-slate-500 h-full rounded-full"
                      }
                      style={{ width: `${item.maintenanceAgePercent}%` }}
                    />
                  </div>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
