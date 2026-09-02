"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import type { FlowPrediction, FlowPredictionStatus } from "@/types/flow";
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
import { Search, ArrowUpDown, ExternalLink } from "lucide-react";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import { FlowRiskBadge } from "./flow-risk-badge";
import { cn } from "@/lib/utils";
import type { ConfidenceLevel } from "@/types/common";

interface FlowPredictionTableProps {
  predictions: FlowPrediction[];
}

type SortKey = "risk" | "onset" | "id";
type SortDir = "asc" | "desc";

function riskClass(risk: number) {
  if (risk >= 0.7) return "text-red-700 font-semibold";
  if (risk >= 0.2) return "text-amber-700 font-semibold";
  return "text-emerald-700 font-medium";
}

function onsetLabel(min: number, max: number): string {
  if (min === 0 && max === 0) return "Active now";
  if (min === max) return `${min} min`;
  if (min > 30) return `>${min} min`;
  return `${min}–${max} min`;
}

export function FlowPredictionTable({ predictions }: FlowPredictionTableProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [confidenceFilter, setConfidenceFilter] = useState<string>("all");
  const [onsetFilter, setOnsetFilter] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("risk");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const filtered = useMemo(() => {
    let list = [...predictions];

    // Search: station ID, name, status
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (p) =>
          p.stationId.toLowerCase().includes(q) ||
          p.stationName.toLowerCase().includes(q) ||
          p.status.toLowerCase().includes(q),
      );
    }

    // Status filter
    if (statusFilter !== "all") {
      list = list.filter((p) => p.status === statusFilter);
    }

    // Confidence filter
    if (confidenceFilter !== "all") {
      list = list.filter((p) => p.confidence === confidenceFilter);
    }

    // Onset filter
    if (onsetFilter === "lt10") {
      list = list.filter(
        (p) => p.expectedOnsetMax <= 10 && p.expectedOnsetMax >= 0,
      );
    } else if (onsetFilter === "elevated") {
      list = list.filter((p) => p.bottleneckRisk >= 0.2);
    }

    // Sort
    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "risk") cmp = a.bottleneckRisk - b.bottleneckRisk;
      else if (sortKey === "onset")
        cmp = a.expectedOnsetMin - b.expectedOnsetMin;
      else if (sortKey === "id") cmp = a.stationId.localeCompare(b.stationId);
      return sortDir === "asc" ? cmp : -cmp;
    });

    return list;
  }, [predictions, search, statusFilter, confidenceFilter, onsetFilter, sortKey, sortDir]);

  return (
    <div className="space-y-4">
      {/* ── Filter Bar ── */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative min-w-[200px]">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search station ID or name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-sm"
            aria-label="Search flow predictions"
          />
        </div>

        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[140px]" aria-label="Filter by status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="CRITICAL">Critical</SelectItem>
            <SelectItem value="WARNING">Warning</SelectItem>
            <SelectItem value="WATCH">Watch</SelectItem>
            <SelectItem value="CLEAR">Clear</SelectItem>
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

        <Select value={onsetFilter} onValueChange={(v) => setOnsetFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[160px]" aria-label="Filter by onset">
            <SelectValue placeholder="Onset" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any Onset</SelectItem>
            <SelectItem value="lt10">Impact &lt; 10 min</SelectItem>
            <SelectItem value="elevated">Elevated Risk Only</SelectItem>
          </SelectContent>
        </Select>

        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {filtered.length} prediction{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── Table ── */}
      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="text-xs">
                <button
                  onClick={() => toggleSort("id")}
                  className="inline-flex items-center gap-1 font-semibold hover:text-foreground transition-colors"
                  aria-label="Sort by station ID"
                >
                  Station <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead className="text-xs font-semibold">Status</TableHead>
              <TableHead className="text-xs">
                <button
                  onClick={() => toggleSort("risk")}
                  className="inline-flex items-center gap-1 font-semibold hover:text-foreground transition-colors"
                  aria-label="Sort by bottleneck risk"
                >
                  Risk <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead className="text-xs">
                <button
                  onClick={() => toggleSort("onset")}
                  className="inline-flex items-center gap-1 font-semibold hover:text-foreground transition-colors"
                  aria-label="Sort by expected onset"
                >
                  Expected Onset <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead className="text-xs font-semibold">Confidence</TableHead>
              <TableHead className="text-xs font-semibold">Primary Signal</TableHead>
              <TableHead className="w-[36px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center text-muted-foreground text-sm py-10"
                >
                  No predictions match the current filters.
                </TableCell>
              </TableRow>
            )}
            {filtered.map((pred) => {
              const primarySignal = pred.evidence.find(
                (e) => e.direction === "negative",
              ) ?? pred.evidence[0];

              return (
                <TableRow
                  key={pred.stationId}
                  className={cn(
                    "hover:bg-muted/20 transition-colors group cursor-pointer",
                    pred.status === "CRITICAL" && "bg-red-50/40",
                    pred.status === "WARNING" && "bg-orange-50/20",
                  )}
                >
                  <TableCell>
                    <div>
                      <Link
                        href={`/app/live-twin/stations/${pred.stationId}`}
                        className="font-mono font-semibold text-xs hover:underline"
                      >
                        {pred.stationId}
                      </Link>
                      <p className="text-[10px] text-muted-foreground truncate max-w-[140px]">
                        {pred.stationName}
                      </p>
                    </div>
                  </TableCell>
                  <TableCell>
                    <FlowRiskBadge status={pred.status} />
                  </TableCell>
                  <TableCell>
                    <span className={cn("text-sm tabular-nums", riskClass(pred.bottleneckRisk))}>
                      {Math.round(pred.bottleneckRisk * 100)}%
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {onsetLabel(pred.expectedOnsetMin, pred.expectedOnsetMax)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <ConfidenceBadge confidence={pred.confidence as ConfidenceLevel} />
                  </TableCell>
                  <TableCell>
                    {primarySignal ? (
                      <span className="text-xs font-mono text-muted-foreground">
                        {primarySignal.label}:{" "}
                        <span
                          className={cn(
                            "font-medium",
                            primarySignal.direction === "negative"
                              ? "text-red-700"
                              : primarySignal.direction === "positive"
                              ? "text-emerald-700"
                              : "text-foreground",
                          )}
                        >
                          {primarySignal.value}
                        </span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-xs">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/app/live-twin/stations/${pred.stationId}`}
                      className="opacity-0 group-hover:opacity-100 transition-opacity"
                      aria-label={`Open station detail for ${pred.stationId}`}
                    >
                      <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                    </Link>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
