"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import type { QualityPrediction, QualityRiskStatus } from "@/types/quality";
import type { VehicleVariant } from "@/types/vehicle";
import type { ConfidenceLevel } from "@/types/common";
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
import { Search, ArrowUpDown, ExternalLink } from "lucide-react";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import { cn } from "@/lib/utils";

interface QualityRiskTableProps {
  predictions: QualityPrediction[];
  selectedVehicleId?: string;
  onSelectVehicle?: (id: string) => void;
}

type SortKey = "risk" | "id" | "stage";
type SortDir = "asc" | "desc";

const STATUS_STYLES: Record<QualityRiskStatus, string> = {
  HIGH: "bg-red-50 text-red-700 border-red-200 font-semibold",
  WATCH: "bg-amber-50 text-amber-700 border-amber-200 font-medium",
  LOW: "bg-emerald-50 text-emerald-700 border-emerald-200 font-medium",
};

const VARIANT_LABEL: Record<VehicleVariant, string> = {
  ICE_SEDAN: "ICE Sedan",
  ICE_SUV: "ICE SUV",
  EV: "EV",
};

function riskColor(risk: number) {
  if (risk >= 0.5) return "text-red-700 font-semibold";
  if (risk >= 0.2) return "text-amber-700 font-semibold";
  return "text-emerald-700 font-medium";
}

export function QualityRiskTable({
  predictions,
  selectedVehicleId,
  onSelectVehicle,
}: QualityRiskTableProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [variantFilter, setVariantFilter] = useState("all");
  const [confidenceFilter, setConfidenceFilter] = useState("all");
  const [exposureFilter, setExposureFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("risk");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("desc"); }
  };

  const filtered = useMemo(() => {
    let list = [...predictions];

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (p) =>
          p.vehicleId.toLowerCase().includes(q) ||
          p.currentStage.toLowerCase().includes(q),
      );
    }

    if (statusFilter !== "all")
      list = list.filter((p) => p.status === statusFilter);

    if (variantFilter !== "all")
      list = list.filter((p) => p.variant === variantFilter);

    if (confidenceFilter !== "all")
      list = list.filter((p) => p.confidence === confidenceFilter);

    if (exposureFilter === "exposed")
      list = list.filter((p) => !!p.exposureCohortId);
    else if (exposureFilter === "not_exposed")
      list = list.filter((p) => !p.exposureCohortId);

    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "risk") cmp = a.defectRisk - b.defectRisk;
      else if (sortKey === "id") cmp = a.vehicleId.localeCompare(b.vehicleId);
      else if (sortKey === "stage")
        cmp = a.currentStage.localeCompare(b.currentStage);
      return sortDir === "asc" ? cmp : -cmp;
    });

    return list;
  }, [predictions, search, statusFilter, variantFilter, confidenceFilter, exposureFilter, sortKey, sortDir]);

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative min-w-[180px]">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Vehicle ID or stage…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-sm"
            aria-label="Search vehicles"
          />
        </div>

        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]" aria-label="Filter by risk status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="HIGH">High Risk</SelectItem>
            <SelectItem value="WATCH">Watch</SelectItem>
            <SelectItem value="LOW">Low Risk</SelectItem>
          </SelectContent>
        </Select>

        <Select value={variantFilter} onValueChange={(v) => setVariantFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]" aria-label="Filter by variant">
            <SelectValue placeholder="Variant" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Variants</SelectItem>
            <SelectItem value="EV">EV</SelectItem>
            <SelectItem value="ICE_SEDAN">ICE Sedan</SelectItem>
            <SelectItem value="ICE_SUV">ICE SUV</SelectItem>
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

        <Select value={exposureFilter} onValueChange={(v) => setExposureFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[150px]" aria-label="Filter by anomaly exposure">
            <SelectValue placeholder="Exposure" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any Exposure</SelectItem>
            <SelectItem value="exposed">Anomaly Exposed</SelectItem>
            <SelectItem value="not_exposed">Not Exposed</SelectItem>
          </SelectContent>
        </Select>

        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {filtered.length} vehicle{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Table */}
      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="text-xs">
                <button
                  onClick={() => toggleSort("id")}
                  className="inline-flex items-center gap-1 font-semibold hover:text-foreground"
                  aria-label="Sort by vehicle ID"
                >
                  Vehicle <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead className="text-xs font-semibold">Variant</TableHead>
              <TableHead className="text-xs">
                <button
                  onClick={() => toggleSort("stage")}
                  className="inline-flex items-center gap-1 font-semibold hover:text-foreground"
                  aria-label="Sort by current stage"
                >
                  Stage <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead className="text-xs font-semibold">Status</TableHead>
              <TableHead className="text-xs">
                <button
                  onClick={() => toggleSort("risk")}
                  className="inline-flex items-center gap-1 font-semibold hover:text-foreground"
                  aria-label="Sort by defect risk"
                >
                  Defect Risk <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead className="text-xs font-semibold">Confidence</TableHead>
              <TableHead className="text-xs font-semibold">Exposure</TableHead>
              <TableHead className="w-[36px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground text-sm py-10">
                  No vehicles match the current filters.
                </TableCell>
              </TableRow>
            )}
            {filtered.map((pred) => {
              const isSelected = pred.vehicleId === selectedVehicleId;
              return (
                <TableRow
                  key={pred.vehicleId}
                  onClick={() => onSelectVehicle?.(pred.vehicleId)}
                  className={cn(
                    "hover:bg-muted/20 transition-colors group cursor-pointer",
                    isSelected
                      ? "bg-slate-100 dark:bg-slate-800 border-l-2 border-l-slate-700"
                      : pred.status === "HIGH"
                      ? "bg-red-50/30"
                      : pred.status === "WATCH"
                      ? "bg-amber-50/20"
                      : ""
                  )}
                >
                  <TableCell>
                  <Link
                    href={`/app/vehicles/${pred.vehicleId}`}
                    className="font-mono font-semibold text-xs hover:underline"
                  >
                    {pred.vehicleId}
                  </Link>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {VARIANT_LABEL[pred.variant]}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {pred.currentStage}
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={cn("text-[10px] uppercase tracking-wide px-2 py-0.5", STATUS_STYLES[pred.status])}
                  >
                    {pred.status === "HIGH" ? "High Risk" : pred.status === "WATCH" ? "Watch" : "Low"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <span className={cn("text-sm tabular-nums", riskColor(pred.defectRisk))}>
                    {Math.round(pred.defectRisk * 100)}%
                  </span>
                </TableCell>
                <TableCell>
                  <ConfidenceBadge confidence={pred.confidence as ConfidenceLevel} />
                </TableCell>
                <TableCell>
                  {pred.exposureCohortId ? (
                    <span className="text-[10px] font-mono text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded">
                      Exposed
                    </span>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <Link
                    href={`/app/vehicles/${pred.vehicleId}`}
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                    aria-label={`Open vehicle detail for ${pred.vehicleId}`}
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
