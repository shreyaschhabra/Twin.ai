/**
 * Anomaly Summary Component
 *
 * Displays a table of active process anomalies, their duration, type/description,
 * number of vehicles exposed, and detection status.
 */

import Link from "next/link";
import { AlertCircle, Eye } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { ExposureCohort } from "@/types/quality";
import { cn } from "@/lib/utils";

interface AnomalySummaryProps {
  cohorts: ExposureCohort[];
}

export function AnomalySummary({ cohorts }: AnomalySummaryProps) {
  const formatTime = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString("en-US", { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="text-xs font-semibold">Station</TableHead>
            <TableHead className="text-xs font-semibold">Time Window</TableHead>
            <TableHead className="text-xs font-semibold">Anomaly Description</TableHead>
            <TableHead className="text-xs font-semibold">Vehicles Exposed</TableHead>
            <TableHead className="text-xs font-semibold">Detection Status</TableHead>
            <TableHead className="w-[36px]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {cohorts.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground text-xs py-8">
                No active process anomalies detected. Process control limits nominal.
              </TableCell>
            </TableRow>
          ) : (
            cohorts.map((cohort) => (
              <TableRow key={cohort.id} className="hover:bg-muted/10">
                <TableCell>
                  <Link
                    href={`/app/live-twin/stations/${cohort.stationId}`}
                    className="font-mono font-semibold text-xs text-foreground hover:underline"
                  >
                    {cohort.stationId}
                  </Link>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground font-mono whitespace-nowrap">
                  {formatTime(cohort.startTime)} – {formatTime(cohort.endTime)}
                </TableCell>
                <TableCell className="text-xs text-foreground min-w-[200px]">
                  {cohort.description.split(".")[0] || cohort.description}
                </TableCell>
                <TableCell className="text-xs font-semibold font-mono text-center sm:text-left">
                  {cohort.affectedVehicleIds.length}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-200 text-[10px] uppercase font-semibold">
                    DETECTED
                  </Badge>
                </TableCell>
                <TableCell>
                  <Link
                    href={`/app/live-twin/stations/${cohort.stationId}`}
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={`View station detail for ${cohort.stationId}`}
                  >
                    <Eye className="h-3.5 w-3.5" />
                  </Link>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
