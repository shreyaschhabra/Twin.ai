/**
 * Shift Summary Table Component
 *
 * Renders historical shift metrics table (Shift, Throughput, Bottleneck Events,
 * Defect Rate, False Alerts, Median Warning Lead Time, and UNKNOWN Coverage).
 */

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ShiftAnalytics } from "@/types/analytics";

interface ShiftSummaryTableProps {
  shifts: ShiftAnalytics[];
}

export function ShiftSummaryTable({ shifts }: ShiftSummaryTableProps) {
  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Shift</TableHead>
            <TableHead className="text-xs font-semibold text-center">Throughput</TableHead>
            <TableHead className="text-xs font-semibold text-center">Bottleneck Events</TableHead>
            <TableHead className="text-xs font-semibold text-center">Defect Rate</TableHead>
            <TableHead className="text-xs font-semibold text-center">False Alerts</TableHead>
            <TableHead className="text-xs font-semibold text-center">Warning Lead Time</TableHead>
            <TableHead className="text-xs font-semibold text-center">UNKNOWN Coverage</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shifts.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="text-center text-muted-foreground text-xs py-8">
                No shift history data available for the selected range.
              </TableCell>
            </TableRow>
          ) : (
            // Reverse order to show newest shifts on top of the list
            [...shifts].reverse().map((shift) => (
              <TableRow key={shift.shiftId} className="hover:bg-muted/10">
                <TableCell className="font-bold font-mono text-xs text-foreground whitespace-nowrap">
                  {shift.shiftId}
                </TableCell>
                <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                  {shift.throughput}
                </TableCell>
                <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                  {shift.bottleneckEvents}
                </TableCell>
                <TableCell className="text-xs text-center font-mono font-medium text-red-700">
                  {Math.round(shift.defectRate * 1000) / 10}%
                </TableCell>
                <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                  {shift.falseAlerts}
                </TableCell>
                <TableCell className="text-xs text-center font-mono font-medium text-foreground">
                  {shift.medianWarningLeadTime.toFixed(1)}m
                </TableCell>
                <TableCell className="text-xs text-center font-mono font-medium text-amber-700">
                  {Math.round(shift.unknownCoverage * 100)}%
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
