/**
 * Sensor Coverage Gaps Component
 *
 * Displays stations where telemetry limitations affect Twin AI predictions.
 * Shows sensor maturity status alongside runtime trust coverage percentages.
 */

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface SensorGapAnalysisProps {}

export function SensorGapAnalysis({}: SensorGapAnalysisProps) {
  // Pre-calculated mock sensor gaps data
  const displayGaps = [
    {
      stationId: "S11",
      stationName: "Door Hinge Robot",
      maturity: "PARTIAL",
      livePct: 35,
      inferredPct: 45,
      unknownPct: 20,
      impact: "HIGH",
    },
    {
      stationId: "S12",
      stationName: "Instrument Panel Robot",
      maturity: "RICH",
      livePct: 76,
      inferredPct: 12,
      unknownPct: 12,
      impact: "MODERATE",
    },
    {
      stationId: "S34",
      stationName: "Battery Mounting Robot",
      maturity: "POOR",
      livePct: 31,
      inferredPct: 42,
      unknownPct: 27,
      impact: "HIGH",
    },
  ];

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Station</TableHead>
            <TableHead className="text-xs font-semibold">Maturity</TableHead>
            <TableHead className="text-xs font-semibold min-w-[160px]">Telemetry Coverage (LIVE / INF / UNK)</TableHead>
            <TableHead className="text-xs font-semibold">Confidence Impact</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {displayGaps.map((item) => (
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
              <TableCell>
                <Badge variant="outline" className="text-[9px] uppercase font-semibold font-mono">
                  {item.maturity}
                </Badge>
              </TableCell>
              <TableCell>
                <div className="space-y-1.5 py-1">
                  {/* Stacked bar representation */}
                  <div className="h-2 w-full bg-slate-200 rounded-full overflow-hidden flex">
                    <div
                      className="bg-emerald-500 h-full"
                      style={{ width: `${item.livePct}%` }}
                      title={`LIVE: ${item.livePct}%`}
                    />
                    <div
                      className="bg-blue-500 h-full"
                      style={{ width: `${item.inferredPct}%` }}
                      title={`INFERRED: ${item.inferredPct}%`}
                    />
                    <div
                      className="bg-slate-400 h-full"
                      style={{ width: `${item.unknownPct}%` }}
                      title={`UNKNOWN: ${item.unknownPct}%`}
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[9px] font-mono text-muted-foreground">
                    <div>LIVE: {item.livePct}%</div>
                    <div>INF: {item.inferredPct}%</div>
                    <div>UNK: {item.unknownPct}%</div>
                  </div>
                </div>
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={
                    item.impact === "HIGH"
                      ? "bg-red-50 text-red-700 border-red-200 text-[9px] uppercase font-bold"
                      : "bg-amber-50 text-amber-700 border-amber-200 text-[9px] uppercase font-semibold"
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
