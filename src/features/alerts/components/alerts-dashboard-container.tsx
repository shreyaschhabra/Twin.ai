/**
 * Alerts Dashboard Container Component
 *
 * Coordinates client-side interactive state for the Unified Alerts Center:
 * - Selected alert ID details panel trigger
 * - Local React session-only reviewed alerts toggle list
 * - Requires Attention quick-action list showing critical warnings
 */

"use client";

import { useState } from "react";
import { AlertCircle, ShieldAlert, CheckSquare, Clock, Bell, Info, ShieldCheck } from "lucide-react";
import type { Alert } from "@/types/alert";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { AlertsTable } from "./alerts-table";
import { AlertDetailPanel } from "./alert-detail-panel";
import { AlertSeverityBadge } from "./alert-severity-badge";
import { AlertTypeBadge } from "./alert-type-badge";
import { cn } from "@/lib/utils";

interface AlertsDashboardContainerProps {
  initialAlerts: Alert[];
  summary: {
    activeCount: number;
    criticalCount: number;
    warningCount: number;
    watchCount: number;
    unreviewedCount: number;
  };
}

export function AlertsDashboardContainer({
  initialAlerts,
  summary,
}: AlertsDashboardContainerProps) {
  // Local session state for reviewed alerts
  const defaultReviewed = new Set<string>(
    initialAlerts.filter((a) => a.acknowledged).map((a) => a.id)
  );
  const [reviewedIds, setReviewedIds] = useState<Set<string>>(defaultReviewed);

  // Selected alert state (defaults to first alert in sorted order)
  const sortedAlerts = [...initialAlerts].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );
  const [selectedAlertId, setSelectedAlertId] = useState<string>(sortedAlerts[0]?.id || "");

  const selectedAlert = initialAlerts.find((a) => a.id === selectedAlertId) || initialAlerts[0];

  const handleToggleReview = (id: string) => {
    setReviewedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Derived metrics dynamically based on local review state
  const unreviewedCount = initialAlerts.filter((a) => !reviewedIds.has(a.id)).length;
  const criticalCount = initialAlerts.filter((a) => a.severity === "CRITICAL" && !reviewedIds.has(a.id)).length;
  const warningCount = initialAlerts.filter((a) => a.severity === "WARNING" && !reviewedIds.has(a.id)).length;

  // "Requires Attention" list (Unreviewed CRITICAL and WARNING alerts)
  const requiresAttentionAlerts = initialAlerts.filter(
    (a) => (a.severity === "CRITICAL" || a.severity === "WARNING") && !reviewedIds.has(a.id)
  );

  const getRelativeAge = (isoString: string) => {
    const minutes = Math.round(
      (new Date("2026-08-30T10:55:00Z").getTime() - new Date(isoString).getTime()) / 60000
    );
    return minutes <= 0 ? "Just now" : `${minutes}m ago`;
  };

  return (
    <div className="space-y-6">
      {/* ── TOP KPI SUMMARY FEED (derived from local reviewed state) ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {/* Total Active */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Total Alerts
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums">
              {initialAlerts.length}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              active shifts monitored
            </p>
          </CardContent>
        </Card>

        {/* Unreviewed Count */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-amber-600 animate-pulse" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Requires Attention
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className={cn("text-2xl font-bold tabular-nums", unreviewedCount > 0 ? "text-amber-700" : "text-emerald-700")}>
              {unreviewedCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              unreviewed warnings
            </p>
          </CardContent>
        </Card>

        {/* Critical Alerts */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-red-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Unresolved Critical
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className={cn("text-2xl font-bold tabular-nums", criticalCount > 0 ? "text-red-700" : "text-emerald-700")}>
              {criticalCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              critical priority
            </p>
          </CardContent>
        </Card>

        {/* Warning Alerts */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-orange-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Unresolved Warnings
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className={cn("text-2xl font-bold tabular-nums", warningCount > 0 ? "text-orange-700" : "text-emerald-700")}>
              {warningCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              warning priority
            </p>
          </CardContent>
        </Card>

        {/* Reviewed Count */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Reviewed
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-emerald-700">
              {reviewedIds.size}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              reviewed alerts
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── REQUIRES ATTENTION QUICK LIST ── */}
      {requiresAttentionAlerts.length > 0 && (
        <Card className="border border-red-200 bg-red-50/10 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-red-800 flex items-center gap-1.5">
              <ShieldAlert className="h-4 w-4 text-red-700" />
              Urgent Operational Warnings
            </CardTitle>
            <CardDescription className="text-xs">
              Immediate unreviewed WARNING and CRITICAL alerts requiring physical action or review.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-2 px-4 pb-4">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {requiresAttentionAlerts.map((alert) => (
                <div
                  key={alert.id}
                  onClick={() => setSelectedAlertId(alert.id)}
                  className={cn(
                    "p-3 rounded border text-xs cursor-pointer transition-all space-y-1.5 flex flex-col justify-between hover:bg-muted/10",
                    alert.id === selectedAlertId
                      ? "bg-red-500/10 border-red-500/30"
                      : "bg-background border-red-200"
                  )}
                >
                  <div className="flex justify-between items-start gap-1">
                    <span className="font-bold text-[11px] truncate flex-1">{alert.title}</span>
                    <AlertSeverityBadge severity={alert.severity} className="scale-75 origin-top-right shrink-0" />
                  </div>
                  <p className="text-[10px] text-muted-foreground line-clamp-2">
                    {alert.description}
                  </p>
                  <div className="flex items-center justify-between text-[10px] font-mono pt-1 text-muted-foreground">
                    <span className="bg-muted px-1 py-0.5 rounded font-sans scale-90">{alert.kind}</span>
                    <span>{getRelativeAge(alert.timestamp)}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── MAIN CONTENT LAYOUT ── */}
      <div className="grid gap-6 lg:grid-cols-3 items-start">
        {/* Table list area */}
        <div className="lg:col-span-2 space-y-4">
          <AlertsTable
            alerts={initialAlerts}
            reviewedAlertIds={reviewedIds}
            selectedAlertId={selectedAlertId}
            onSelectAlert={(a) => setSelectedAlertId(a.id)}
          />
        </div>

        {/* Selected alert details card */}
        <div className="lg:col-span-1">
          {selectedAlert ? (
            <AlertDetailPanel
              alert={selectedAlert}
              isReviewed={reviewedIds.has(selectedAlert.id)}
              onToggleReview={handleToggleReview}
            />
          ) : (
            <Card className="border border-dashed p-6 text-center text-xs text-muted-foreground h-48 flex items-center justify-center">
              Select an alert from the table to view details.
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
