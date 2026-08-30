"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import type { Vehicle, VehicleVariant, VehicleStatus } from "@/types/vehicle";
import { Badge } from "@/components/ui/badge";
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
import { Search, ArrowUpDown, AlertTriangle, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface VehicleListTableProps {
  vehicles: Vehicle[];
}

type SortKey = "qualityRisk" | "id" | "currentStage";
type SortDir = "asc" | "desc";

function statusBadge(status: VehicleStatus) {
  switch (status) {
    case "HIGH_RISK":
      return (
        <Badge className="bg-red-100 text-red-800 border-red-200 font-medium">
          High Risk
        </Badge>
      );
    case "WATCH":
      return (
        <Badge className="bg-amber-100 text-amber-800 border-amber-200 font-medium">
          Watch
        </Badge>
      );
    case "ON_TRACK":
      return (
        <Badge className="bg-emerald-100 text-emerald-800 border-emerald-200 font-medium">
          On Track
        </Badge>
      );
    case "COMPLETE":
      return (
        <Badge className="bg-slate-100 text-slate-600 border-slate-200 font-medium">
          Complete
        </Badge>
      );
  }
}

function variantLabel(v: VehicleVariant) {
  switch (v) {
    case "ICE_SEDAN":
      return "ICE Sedan";
    case "ICE_SUV":
      return "ICE SUV";
    case "EV":
      return "EV";
  }
}

function riskColor(risk: number) {
  if (risk >= 0.5) return "text-red-700 font-semibold";
  if (risk >= 0.2) return "text-amber-700 font-semibold";
  return "text-emerald-700 font-medium";
}

function confidenceLabel(c: string) {
  switch (c) {
    case "HIGH":
      return <span className="text-emerald-700 font-medium">High</span>;
    case "MEDIUM":
      return <span className="text-amber-700 font-medium">Medium</span>;
    case "LOW":
      return <span className="text-red-700 font-medium">Low</span>;
    default:
      return <span className="text-muted-foreground">—</span>;
  }
}

function trustCoverage(v: Vehicle) {
  return v.sensorCoverage.livePercent + v.sensorCoverage.inferredPercent;
}

export function VehicleListTable({ vehicles }: VehicleListTableProps) {
  const [search, setSearch] = useState("");
  const [variantFilter, setVariantFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [anomalyFilter, setAnomalyFilter] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("qualityRisk");
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
    let list = [...vehicles];

    if (search.trim()) {
      const q = search.trim().toUpperCase();
      list = list.filter((v) => v.id.toUpperCase().includes(q));
    }
    if (variantFilter !== "all") {
      list = list.filter((v) => v.variant === variantFilter);
    }
    if (statusFilter !== "all") {
      list = list.filter((v) => v.status === statusFilter);
    }
    if (anomalyFilter === "exposed") {
      list = list.filter((v) => v.genealogy.some((e) => e.anomalyExposure));
    } else if (anomalyFilter === "clean") {
      list = list.filter((v) => v.genealogy.every((e) => !e.anomalyExposure));
    }

    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "qualityRisk") cmp = a.qualityRisk - b.qualityRisk;
      else if (sortKey === "id") cmp = a.id.localeCompare(b.id);
      else if (sortKey === "currentStage") cmp = a.currentStage.localeCompare(b.currentStage);
      return sortDir === "asc" ? cmp : -cmp;
    });

    return list;
  }, [vehicles, search, variantFilter, statusFilter, anomalyFilter, sortKey, sortDir]);

  return (
    <div className="space-y-4">
      {/* Filter Bar */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative min-w-[180px]">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search by vehicle ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-sm"
          />
        </div>

        <Select value={variantFilter} onValueChange={(v) => setVariantFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]">
            <SelectValue placeholder="Variant" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Variants</SelectItem>
            <SelectItem value="ICE_SEDAN">ICE Sedan</SelectItem>
            <SelectItem value="ICE_SUV">ICE SUV</SelectItem>
            <SelectItem value="EV">EV</SelectItem>
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[130px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="ON_TRACK">On Track</SelectItem>
            <SelectItem value="WATCH">Watch</SelectItem>
            <SelectItem value="HIGH_RISK">High Risk</SelectItem>
          </SelectContent>
        </Select>

        <Select value={anomalyFilter} onValueChange={(v) => setAnomalyFilter(v ?? "all")}>
          <SelectTrigger className="h-8 text-sm w-[160px]">
            <SelectValue placeholder="Anomaly Exposure" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any Exposure</SelectItem>
            <SelectItem value="exposed">Anomaly Exposed</SelectItem>
            <SelectItem value="clean">No Exposure</SelectItem>
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
              <TableHead className="w-[90px]">
                <button
                  onClick={() => toggleSort("id")}
                  className="inline-flex items-center gap-1 text-xs font-semibold hover:text-foreground transition-colors"
                >
                  Vehicle <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead>Variant</TableHead>
              <TableHead>
                <button
                  onClick={() => toggleSort("currentStage")}
                  className="inline-flex items-center gap-1 text-xs font-semibold hover:text-foreground transition-colors"
                >
                  Stage <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead>Station</TableHead>
              <TableHead>
                <button
                  onClick={() => toggleSort("qualityRisk")}
                  className="inline-flex items-center gap-1 text-xs font-semibold hover:text-foreground transition-colors"
                >
                  Defect Risk <ArrowUpDown className="h-3 w-3" />
                </button>
              </TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead>Trust Coverage</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-[40px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={9}
                  className="text-center text-muted-foreground text-sm py-10"
                >
                  No vehicles match the current filters.
                </TableCell>
              </TableRow>
            )}
            {filtered.map((vehicle) => {
              const hasAnomaly = vehicle.genealogy.some((e) => e.anomalyExposure);
              const coverage = trustCoverage(vehicle);
              return (
                <TableRow
                  key={vehicle.id}
                  className={cn(
                    "hover:bg-muted/30 transition-colors cursor-pointer group",
                    vehicle.status === "HIGH_RISK" && "bg-red-50/40",
                  )}
                >
                  <TableCell className="font-mono font-semibold text-xs">
                    <Link
                      href={`/app/vehicles/${vehicle.id}`}
                      className="hover:underline text-foreground"
                    >
                      {vehicle.id}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {variantLabel(vehicle.variant)}
                  </TableCell>
                  <TableCell className="text-xs">{vehicle.currentStage}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    <Link
                      href={`/app/live-twin/stations/${vehicle.currentStationId}`}
                      className="hover:underline hover:text-foreground transition-colors"
                    >
                      {vehicle.currentStationId}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <span className={cn("text-sm tabular-nums", riskColor(vehicle.qualityRisk))}>
                      {(vehicle.qualityRisk * 100).toFixed(0)}%
                    </span>
                  </TableCell>
                  <TableCell className="text-xs">{confidenceLabel(vehicle.confidence)}</TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "text-xs tabular-nums",
                        coverage < 60
                          ? "text-red-700 font-medium"
                          : coverage < 85
                          ? "text-amber-700"
                          : "text-emerald-700",
                      )}
                    >
                      {coverage}%
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      {statusBadge(vehicle.status)}
                      {hasAnomaly && (
                        <AlertTriangle className="h-3 w-3 text-amber-600" aria-label="Anomaly Exposed" />
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/app/vehicles/${vehicle.id}`}
                      className="opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
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
