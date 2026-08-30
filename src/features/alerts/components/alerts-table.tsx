/**
 * Alerts Table Component
 *
 * Scannable table rendering current active alerts on the production floor.
 * Supports query searches, severity, type, and confidence filtering.
 * Toggles sorted values by priority, timing, and risk.
 */

"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { Search, ArrowUpDown, ExternalLink, Check, CircleAlert } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { AlertSeverityBadge } from "./alert-severity-badge";
import { AlertTypeBadge } from "./alert-type-badge";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import type { Alert } from "@/types/alert";
import type { AlertSeverity, AlertKind, ConfidenceLevel } from "@/types/common";
import { cn } from "@/lib/utils";

interface AlertsTableProps {
  alerts: Alert[];
  reviewedAlertIds: Set<string>;
  selectedAlertId?: string;
  onSelectAlert: (alert: Alert) => void;
}

type SortKey = "priority" | "newest" | "oldest" | "risk";

function riskColor(risk: number) {
  if (risk >= 0.5) return "text-red-700 font-semibold";
  if (risk >= 0.2) return "text-amber-700 font-semibold";
  return "text-emerald-700 font-medium";
}

export function AlertsTable({
  alerts,
  reviewedAlertIds,
  selectedAlertId,
  onSelectAlert,
}: AlertsTableProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all"); // active, reviewed, all
  const [severityFilter, setSeverityFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [confidenceFilter, setConfidenceFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("priority");

  // Relative timestamp calculation relative to the mock reference shift time
  const getRelativeAge = (isoString: string) => {
    const minutes = Math.round(
      (new Date("2026-08-30T10:55:00Z").getTime() - new Date(isoString).getTime()) / 60000
    );
    return minutes <= 0 ? "Just now" : `${minutes}m ago`;
  };

  const getSeverityValue = (sev: AlertSeverity) => {
    switch (sev) {
      case "CRITICAL": return 4;
      case "WARNING": return 3;
      case "WATCH": return 2;
      case "INFO": return 1;
      default: return 0;
    }
  };

  const filteredAlerts = useMemo(() => {
    let list = [...alerts];

    // 1. Search filter
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (a) =>
          a.title.toLowerCase().includes(q) ||
          a.description.toLowerCase().includes(q) ||
          (a.stationId && a.stationId.toLowerCase().includes(q)) ||
          (a.vehicleId && a.vehicleId.toLowerCase().includes(q))
      );
    }

    // 2. Status filter (Active = unreviewed, Reviewed, All)
    if (statusFilter === "active") {
      list = list.filter((a) => !reviewedAlertIds.has(a.id));
    } else if (statusFilter === "reviewed") {
      list = list.filter((a) => reviewedAlertIds.has(a.id));
    }

    // 3. Severity filter
    if (severityFilter !== "all") {
      list = list.filter((a) => a.severity === severityFilter);
    }

    // 4. Type (Kind) filter
    if (typeFilter !== "all") {
      list = list.filter((a) => a.kind === typeFilter);
    }

    // 5. Confidence filter
    if (confidenceFilter !== "all") {
      list = list.filter((a) => a.confidence === confidenceFilter);
    }

    // 6. Sorting
    list.sort((a, b) => {
      if (sortKey === "newest") {
        return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
      }
      if (sortKey === "oldest") {
        return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
      }
      if (sortKey === "risk") {
        const riskA = a.risk ?? -1;
        const riskB = b.risk ?? -1;
        return riskB - riskA;
      }
      // Default: Priority (Severity desc, timing desc)
      const sevDiff = getSeverityValue(b.severity) - getSeverityValue(a.severity);
      if (sevDiff !== 0) return sevDiff;

      // Unresolved/Unreviewed first
      const revA = reviewedAlertIds.has(a.id) ? 1 : 0;
      const revB = reviewedAlertIds.has(b.id) ? 1 : 0;
      if (revA !== revB) return revA - revB;

      // Timestamps
      return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    });

    return list;
  }, [alerts, search, statusFilter, severityFilter, typeFilter, confidenceFilter, sortKey, reviewedAlertIds]);

  return (
    <div className="space-y-4">
      {/* ── Filter bar ── */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative min-w-[180px]">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search alerts…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-sm"
            aria-label="Search alerts"
          />
        </div>

        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]" aria-label="Filter by status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Alerts</SelectItem>
            <SelectItem value="active">Active (Unreviewed)</SelectItem>
            <SelectItem value="reviewed">Reviewed</SelectItem>
          </SelectContent>
        </Select>

        <Select value={severityFilter} onValueChange={(v) => setSeverityFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]" aria-label="Filter by severity">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Severities</SelectItem>
            <SelectItem value="CRITICAL">Critical</SelectItem>
            <SelectItem value="WARNING">Warning</SelectItem>
            <SelectItem value="WATCH">Watch</SelectItem>
            <SelectItem value="INFO">Info</SelectItem>
          </SelectContent>
        </Select>

        <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]" aria-label="Filter by type">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="FLOW">Flow</SelectItem>
            <SelectItem value="QUALITY">Quality</SelectItem>
            <SelectItem value="SENSOR">Sensor Trust</SelectItem>
            <SelectItem value="ANOMALY">Anomaly</SelectItem>
          </SelectContent>
        </Select>

        <Select value={confidenceFilter} onValueChange={(v) => setConfidenceFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]" aria-label="Filter by confidence">
            <SelectValue placeholder="Confidence" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Confidence</SelectItem>
            <SelectItem value="HIGH">High</SelectItem>
            <SelectItem value="MEDIUM">Medium</SelectItem>
            <SelectItem value="LOW">Low</SelectItem>
          </SelectContent>
        </Select>

        <Select value={sortKey} onValueChange={(v) => setSortKey((v as SortKey) ?? "priority")}>
          <SelectTrigger className="h-8 text-sm w-[130px]" aria-label="Sort alerts">
            <SelectValue placeholder="Sort By" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="priority">Priority</SelectItem>
            <SelectItem value="newest">Newest</SelectItem>
            <SelectItem value="oldest">Oldest</SelectItem>
            <SelectItem value="risk">Defect Risk</SelectItem>
          </SelectContent>
        </Select>

        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {filteredAlerts.length} alert{filteredAlerts.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── Table List ── */}
      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="w-[120px] text-xs font-semibold">Severity</TableHead>
              <TableHead className="w-[110px] text-xs font-semibold">Type</TableHead>
              <TableHead className="text-xs font-semibold">Warning Title</TableHead>
              <TableHead className="w-[120px] text-xs font-semibold">Target</TableHead>
              <TableHead className="w-[80px] text-xs font-semibold">Risk / Conf</TableHead>
              <TableHead className="w-[90px] text-xs font-semibold">Timing</TableHead>
              <TableHead className="w-[90px] text-xs font-semibold">Status</TableHead>
              <TableHead className="w-[36px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredAlerts.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground text-xs py-12">
                  No operational alerts match the current filters.
                </TableCell>
              </TableRow>
            ) : (
              filteredAlerts.map((alert) => {
                const isSelected = alert.id === selectedAlertId;
                const isReviewed = reviewedAlertIds.has(alert.id);

                return (
                  <TableRow
                    key={alert.id}
                    onClick={() => onSelectAlert(alert)}
                    className={cn(
                      "hover:bg-muted/20 transition-colors group cursor-pointer",
                      isSelected
                        ? "bg-slate-100 dark:bg-slate-800 border-l-2 border-l-slate-700"
                        : isReviewed
                        ? "opacity-60 bg-slate-50/50"
                        : alert.severity === "CRITICAL"
                        ? "bg-red-50/30"
                        : alert.severity === "WARNING"
                        ? "bg-orange-50/20"
                        : ""
                    )}
                  >
                    {/* Severity Badge */}
                    <TableCell>
                      <AlertSeverityBadge severity={alert.severity} />
                    </TableCell>

                    {/* Type Badge */}
                    <TableCell>
                      <AlertTypeBadge kind={alert.kind} />
                    </TableCell>

                    {/* Alert Title */}
                    <TableCell>
                      <div className="space-y-0.5 max-w-[280px] sm:max-w-xs md:max-w-md lg:max-w-lg">
                        <p className={cn("text-xs font-bold text-foreground truncate", isReviewed && "font-semibold")}>
                          {alert.title}
                        </p>
                        <p className="text-[10px] text-muted-foreground truncate">
                          {alert.description}
                        </p>
                      </div>
                    </TableCell>

                    {/* Station / Vehicle Target */}
                    <TableCell>
                      {alert.vehicleId ? (
                        <Link
                          href={`/app/vehicles/${alert.vehicleId}`}
                          onClick={(e) => e.stopPropagation()}
                          className="font-mono text-xs font-bold hover:underline text-foreground block"
                        >
                          {alert.vehicleId}
                        </Link>
                      ) : alert.stationId ? (
                        <Link
                          href={`/app/live-twin/stations/${alert.stationId}`}
                          onClick={(e) => e.stopPropagation()}
                          className="font-mono text-xs font-bold hover:underline text-foreground block"
                        >
                          {alert.stationId}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>

                    {/* Risk / Confidence */}
                    <TableCell>
                      {alert.risk !== undefined ? (
                        <div className="space-y-0.5">
                          <span className={cn("text-xs font-bold font-mono", riskColor(alert.risk))}>
                            {Math.round(alert.risk * 100)}%
                          </span>
                          {alert.confidence && (
                            <div className="scale-75 origin-left">
                              <ConfidenceBadge confidence={alert.confidence} />
                            </div>
                          )}
                        </div>
                      ) : alert.confidence ? (
                        <div className="scale-75 origin-left">
                          <ConfidenceBadge confidence={alert.confidence} />
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>

                    {/* Timestamp relative age */}
                    <TableCell className="text-xs text-muted-foreground font-mono whitespace-nowrap">
                      {getRelativeAge(alert.timestamp)}
                    </TableCell>

                    {/* Review status */}
                    <TableCell>
                      {isReviewed ? (
                        <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200 text-[9px] uppercase font-mono py-0.5 px-1.5 inline-flex items-center gap-0.5">
                          <Check className="h-2.5 w-2.5 text-slate-500" />
                          Reviewed
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="bg-amber-50 text-amber-800 border-amber-200 text-[9px] uppercase font-bold py-0.5 px-1.5 inline-flex items-center gap-0.5">
                          <CircleAlert className="h-2.5 w-2.5 text-amber-600 animate-pulse" />
                          New
                        </Badge>
                      )}
                    </TableCell>

                    {/* Detail icon */}
                    <TableCell>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectAlert(alert);
                        }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
                        aria-label="View alert detail"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </button>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
