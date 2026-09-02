/**
 * Exposure Cohort List Component
 *
 * Displays a list of process anomaly exposure cohorts.
 * Allows selecting a cohort to view the list of affected vehicles and their defect risks.
 */

"use client";

import { useState } from "react";
import Link from "next/link";
import { Layers, Calendar, Users, AlertTriangle, ArrowRight, ShieldCheck } from "lucide-react";
import type { ExposureCohort } from "@/types/quality";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Lookup helpers for vehicle risk/status
interface VehicleRiskSummary {
  id: string;
  risk: number;
  status: string;
}

interface ExposureCohortListProps {
  cohorts: ExposureCohort[];
  vehicleRisks: Record<string, { risk: number; status: string }>;
}

export function ExposureCohortList({ cohorts, vehicleRisks }: ExposureCohortListProps) {
  const [selectedCohortId, setSelectedCohortId] = useState<string>(cohorts[0]?.id || "");

  const selectedCohort = cohorts.find((c) => c.id === selectedCohortId);

  const formatTime = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString("en-US", { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
    } catch {
      return isoString;
    }
  };

  const getVehicleRisk = (vehicleId: string): number => {
    return vehicleRisks[vehicleId]?.risk ?? 0.05; // Fallback default risk
  };

  const getVehicleStatus = (vehicleId: string): string => {
    return vehicleRisks[vehicleId]?.status ?? "LOW";
  };

  const sortedCohortVehicles = selectedCohort
    ? [...selectedCohort.affectedVehicleIds].sort((a, b) => getVehicleRisk(b) - getVehicleRisk(a))
    : [];

  return (
    <div className="grid gap-6 md:grid-cols-3">
      {/* ── COHORT LIST SIDE ── */}
      <div className="md:col-span-1 space-y-3">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Active Cohorts
        </p>
        <div className="space-y-2">
          {cohorts.length === 0 ? (
            <Card className="border shadow-none">
              <CardContent className="p-6 text-center text-xs text-muted-foreground">
                No active exposure cohorts.
              </CardContent>
            </Card>
          ) : (
            cohorts.map((cohort) => {
              const isSelected = cohort.id === selectedCohortId;
              return (
                <button
                  key={cohort.id}
                  onClick={() => setSelectedCohortId(cohort.id)}
                  className={cn(
                    "w-full text-left p-3 rounded-lg border transition-all text-xs space-y-1.5",
                    isSelected
                      ? "bg-amber-500/10 border-amber-500/30 text-foreground ring-1 ring-amber-500/20"
                      : "bg-card border-muted hover:bg-muted/10 text-muted-foreground hover:text-foreground"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-foreground">
                      {cohort.stationId}
                    </span>
                    <span className="text-[10px] text-muted-foreground flex items-center gap-1 font-mono">
                      <Calendar className="h-3 w-3" />
                      {formatTime(cohort.startTime)}–{formatTime(cohort.endTime)}
                    </span>
                  </div>
                  <p className="line-clamp-2 text-xs text-muted-foreground">
                    {cohort.description}
                  </p>
                  <div className="flex items-center gap-3 pt-0.5 text-[10px] text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Users className="h-3 w-3" />
                      {cohort.affectedVehicleIds.length} exposed
                    </span>
                    {cohort.highRiskVehicleIds.length > 0 && (
                      <span className="text-red-700 font-semibold">
                        {cohort.highRiskVehicleIds.length} high-risk
                      </span>
                    )}
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* ── COHORT DETAIL SIDE ── */}
      <div className="md:col-span-2">
        {selectedCohort ? (
          <Card className="border shadow-none bg-card">
            <CardHeader className="pb-3 border-b">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-1.5 text-amber-700 text-[10px] font-semibold uppercase tracking-wider font-mono">
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                    Process Anomaly Exposure details
                  </div>
                  <CardTitle className="text-sm font-semibold flex items-center gap-2 mt-1">
                    Station {selectedCohort.stationId} Cohort
                  </CardTitle>
                </div>
                <Badge variant="outline" className="font-mono text-[10px] uppercase">
                  ID: {selectedCohort.id}
                </Badge>
              </div>
              <CardDescription className="text-xs text-foreground mt-2">
                {selectedCohort.description}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              {/* Evidence summary */}
              {selectedCohort.evidence && selectedCohort.evidence.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                    Cohort Evidence / Observed Conditions
                  </p>
                  <div className="grid gap-1.5 sm:grid-cols-2">
                    {selectedCohort.evidence.map((item, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-2 rounded border bg-muted/10 text-xs font-mono"
                      >
                        <span className="text-muted-foreground truncate mr-2">{item.label}</span>
                        <span
                          className={cn(
                            "font-semibold",
                            item.direction === "negative"
                              ? "text-red-700"
                              : item.direction === "positive"
                                ? "text-emerald-700"
                                : "text-muted-foreground"
                          )}
                        >
                          {item.value}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Affected vehicles list */}
              <div className="space-y-1.5 border-t pt-3">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                  Exposed Assemblies &amp; Defect Risks
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {sortedCohortVehicles.map((vehicleId) => {
                    const risk = getVehicleRisk(vehicleId);
                    const status = getVehicleStatus(vehicleId);
                    const riskPct = Math.round(risk * 100);

                    return (
                      <div
                        key={vehicleId}
                        className={cn(
                          "flex items-center justify-between p-2.5 rounded border text-xs",
                          status === "HIGH"
                            ? "border-red-200 bg-red-50/20"
                            : status === "WATCH"
                              ? "border-amber-200 bg-amber-50/20"
                              : "border-muted bg-background"
                        )}
                      >
                        <div className="space-y-0.5">
                          <Link
                            href={`/app/vehicles/${vehicleId}`}
                            className="font-mono font-bold hover:underline text-foreground block"
                          >
                            {vehicleId}
                          </Link>
                          <span className="text-[10px] text-muted-foreground font-sans uppercase">
                            {status === "HIGH" ? "High Risk" : status === "WATCH" ? "Watch" : "Normal"}
                          </span>
                        </div>
                        <div className="text-right">
                          <span
                            className={cn(
                              "text-sm font-extrabold font-mono",
                              status === "HIGH"
                                ? "text-red-700"
                                : status === "WATCH"
                                  ? "text-amber-700"
                                  : "text-emerald-700"
                            )}
                          >
                            {riskPct}%
                          </span>
                          <p className="text-[9px] text-muted-foreground font-sans">defect risk</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card className="border shadow-none h-full flex items-center justify-center py-10">
            <CardContent className="text-center text-xs text-muted-foreground">
              Select an exposure cohort to view its details.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
