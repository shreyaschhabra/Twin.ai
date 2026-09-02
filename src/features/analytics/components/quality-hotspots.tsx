/**
 * Quality Hotspots Component
 *
 * Renders recurrent quality hotspots.
 * Rankings reflect stations frequently associated with elevated quality-risk exposure.
 */

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface QualityHotspotsProps {}

export function QualityHotspots({}: QualityHotspotsProps) {
  // Pre-calculated mock quality hotspots data
  // S12: IP Robot, Exposed 148, High Risk 31, Defects 12, Rate 8.1%, Trend Worsening
  // S11: Door Hinge, Exposed 115, High Risk 14, Defects 4, Rate 3.4%, Trend Stable
  const displayHotspots = [
    {
      stationId: "S12",
      stationName: "Instrument Panel Robot",
      exposedCount: 148,
      highRiskCount: 31,
      confirmedDefects: 12,
      rate: 0.081,
      trend: "WORSENING",
    },
    {
      stationId: "S11",
      stationName: "Door Hinge Robot",
      exposedCount: 115,
      highRiskCount: 14,
      confirmedDefects: 4,
      rate: 0.034,
      trend: "STABLE",
    },
  ];

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Station / Process</TableHead>
            <TableHead className="text-xs font-semibold text-center">Exposed Assemblies</TableHead>
            <TableHead className="text-xs font-semibold text-center">High-Risk Flagged</TableHead>
            <TableHead className="text-xs font-semibold text-center">Confirmed Defects</TableHead>
            <TableHead className="text-xs font-semibold">Exposure Rate</TableHead>
            <TableHead className="text-xs font-semibold">Trend</TableHead>
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
                  <p className="text-[10px] text-muted-foreground font-sans truncate max-w-[150px]">
                    {item.stationName}
                  </p>
                </div>
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-medium">
                {item.exposedCount}
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-semibold text-amber-700">
                {item.highRiskCount}
              </TableCell>
              <TableCell className="text-xs text-center font-mono font-bold text-red-700">
                {item.confirmedDefects}
              </TableCell>
              <TableCell className="text-xs font-mono font-medium">
                {Math.round(item.rate * 1000) / 10}%
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={
                    item.trend === "WORSENING"
                      ? "bg-red-50 text-red-700 border-red-200 text-[9px] uppercase font-bold"
                      : "bg-slate-50 text-slate-700 border-slate-200 text-[9px] uppercase font-semibold"
                  }
                >
                  {item.trend}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
