/**
 * Alert Detail Panel Component
 *
 * Detailed side panel showing information for the selected operational alert.
 * Supports FLOW, QUALITY, SENSOR, and ANOMALY kinds with specific layouts.
 * Includes review status toggles and cross-navigation links.
 */

import Link from "next/link";
import { AlertCircle, Calendar, Clock, ArrowRight, CheckCircle, ExternalLink, HelpCircle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertSeverityBadge } from "./alert-severity-badge";
import { AlertTypeBadge } from "./alert-type-badge";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import { SensorTrustBadge } from "@/features/trust/components/sensor-trust-badge";
import type { Alert } from "@/types/alert";
import { cn } from "@/lib/utils";

interface AlertDetailPanelProps {
  alert: Alert;
  isReviewed: boolean;
  onToggleReview: (id: string) => void;
}

function riskColor(risk: number) {
  if (risk >= 0.5) return "text-red-700 dark:text-red-400";
  if (risk >= 0.2) return "text-amber-700 dark:text-amber-400";
  return "text-emerald-700 dark:text-emerald-400";
}

export function AlertDetailPanel({
  alert,
  isReviewed,
  onToggleReview,
}: AlertDetailPanelProps) {
  const formatExactTime = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleString("en-US", { timeZone: "UTC" });
    } catch {
      return isoString;
    }
  };

  const alertAgeMin = Math.round(
    (new Date("2026-08-30T10:55:00Z").getTime() - new Date(alert.timestamp).getTime()) / 60000
  );

  return (
    <Card className="border shadow-none bg-card h-full flex flex-col">
      <CardHeader className="pb-3 border-b shrink-0">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <AlertTypeBadge kind={alert.kind} />
            <AlertSeverityBadge severity={alert.severity} />
          </div>
          <span className="text-[10px] text-muted-foreground font-mono">
            {alert.id}
          </span>
        </div>
        <CardTitle className="text-sm font-bold mt-2 leading-snug">
          {alert.title}
        </CardTitle>
        <div className="flex items-center gap-3 pt-1.5 text-[10px] text-muted-foreground font-mono">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {alertAgeMin <= 0 ? "Just now" : `${alertAgeMin}m ago`}
          </span>
          <span className="flex items-center gap-1">
            <Calendar className="h-3 w-3" />
            {formatExactTime(alert.timestamp)}
          </span>
        </div>
      </CardHeader>

      <CardContent className="pt-4 space-y-4 flex-1 overflow-y-auto">
        <p className="text-xs text-foreground leading-normal">
          {alert.description}
        </p>

        {/* ── FLOW-SPECIFIC LAYOUT ── */}
        {alert.kind === "FLOW" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg border bg-muted/10">
              {alert.risk !== undefined && (
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
                    Bottleneck Risk
                  </span>
                  <span className={cn("text-xl font-black tracking-tight font-mono", riskColor(alert.risk))}>
                    {Math.round(alert.risk * 100)}%
                  </span>
                </div>
              )}
              {alert.confidence && (
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
                    Confidence
                  </span>
                  <div className="mt-1">
                    <ConfidenceBadge confidence={alert.confidence} />
                  </div>
                </div>
              )}
            </div>

            {/* Expected impact timing */}
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
                Expected Onset Window
              </span>
              <p className="text-xs font-semibold">
                {alert.risk && alert.risk >= 0.9 ? "Active Constraint" : "6–8 minutes (predicted range)"}
              </p>
            </div>

            {/* Telemetry coverage state */}
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
                Station Sensor Trust
              </span>
              <div className="mt-1">
                <SensorTrustBadge trust={alert.stationId === "S12" ? "INFERRED" : "LIVE"} />
              </div>
            </div>
          </div>
        )}

        {/* ── QUALITY-SPECIFIC LAYOUT ── */}
        {alert.kind === "QUALITY" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg border bg-muted/10">
              {alert.risk !== undefined && (
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
                    Defect Risk Estimate
                  </span>
                  <span className={cn("text-xl font-black tracking-tight font-mono", riskColor(alert.risk))}>
                    {Math.round(alert.risk * 100)}%
                  </span>
                </div>
              )}
              {alert.confidence && (
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
                    Confidence
                  </span>
                  <div className="mt-1">
                    <ConfidenceBadge confidence={alert.confidence} />
                  </div>
                </div>
              )}
            </div>

            {/* Process anomaly exposure details */}
            <div className="rounded border bg-amber-50/20 border-amber-200 p-2.5 space-y-1 text-xs">
              <div className="text-[9px] font-semibold text-amber-700 uppercase font-mono tracking-wider">
                Process Anomaly Exposure Context
              </div>
              <p className="text-muted-foreground">
                Exposed to camera dropout anomaly window at <span className="font-mono font-semibold text-foreground">S12</span>.
              </p>
              <div className="grid grid-cols-2 text-[10px] pt-1">
                <div>
                  <span className="text-muted-foreground">QC Inspection:</span>{" "}
                  <span className="font-semibold text-foreground">Pending</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Variant:</span>{" "}
                  <span className="font-semibold text-foreground">EV</span>
                </div>
              </div>
            </div>

            <p className="text-[10px] text-muted-foreground italic">
              * Risk value is an estimate of downstream defect probability. The assembly is not confirmed as defective prior to QC outcomes.
            </p>
          </div>
        )}

        {/* ── SENSOR-SPECIFIC LAYOUT ── */}
        {alert.kind === "SENSOR" && (
          <div className="space-y-3">
            <div className="rounded border p-2.5 space-y-2 text-xs">
              <div className="text-[9px] font-semibold text-slate-700 uppercase font-mono tracking-wider">
                Sensor Trust State Change
              </div>
              <div className="flex items-center gap-2 font-mono">
                <SensorTrustBadge trust="LIVE" />
                <span className="text-muted-foreground text-xs">→</span>
                <SensorTrustBadge trust={alert.stationId === "S12" ? "INFERRED" : "UNKNOWN"} />
              </div>
              <p className="text-muted-foreground text-[11px] leading-normal pt-1">
                {alert.stationId === "S12"
                  ? "Current signal is being estimated from validated adjacent context. Model prediction confidence reduced to MEDIUM."
                  : "Continuous telemetry gap detected. Signal unavailable. Physical review recommended."}
              </p>
            </div>
          </div>
        )}

        {/* ── ANOMALY-SPECIFIC LAYOUT ── */}
        {alert.kind === "ANOMALY" && (
          <div className="space-y-3">
            <div className="rounded border p-2.5 space-y-2 text-xs">
              <div className="text-[9px] font-semibold text-amber-700 uppercase font-mono tracking-wider">
                Observed Abnormal Behavior
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                <div>
                  <span className="text-muted-foreground">Station:</span>{" "}
                  <span className="text-foreground font-semibold">{alert.stationId}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Exposed:</span>{" "}
                  <span className="text-foreground font-semibold">12 vehicles</span>
                </div>
                <div className="col-span-2">
                  <span className="text-muted-foreground">Window:</span>{" "}
                  <span className="text-foreground font-semibold">10:31 – 10:42</span>
                </div>
              </div>
              <p className="text-muted-foreground text-[10px] italic pt-1 border-t">
                Anomaly alerts trace process limit deviations, which does not constitute confirmed vehicle defects.
              </p>
            </div>
          </div>
        )}

        {/* ── Evidence List ── */}
        {alert.evidence && alert.evidence.length > 0 && (
          <div className="space-y-1.5 border-t pt-3">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider block font-semibold">
              Evidence / Observed conditions
            </span>
            <div className="space-y-1">
              {alert.evidence.map((item, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 rounded border bg-background text-xs font-mono"
                >
                  <span className="text-muted-foreground truncate mr-2">{item.label}</span>
                  <span
                    className={cn(
                      "font-semibold shrink-0",
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

        {/* ── Disclaimer card ── */}
        <div className="rounded border bg-slate-50 border-slate-200 p-2.5 text-[10px] text-muted-foreground leading-normal">
          <p className="font-semibold text-slate-700 mb-0.5">Operator Advisory</p>
          Process anomalies represent unusual limit behaviors (e.g. cycle times, drift limits). Causal claims and defect predictions are derived separately.
        </div>
      </CardContent>

      <CardFooter className="border-t pt-3 pb-4 px-4 bg-muted/10 shrink-0 flex flex-col gap-3">
        {/* Review status buttons */}
        <Button
          onClick={() => onToggleReview(alert.id)}
          className={cn(
            "w-full h-8 text-xs font-semibold",
            isReviewed
              ? "bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200"
              : "bg-foreground hover:bg-foreground/95 text-background"
          )}
        >
          {isReviewed ? "Mark as unreviewed" : "Mark as reviewed"}
        </Button>

        {/* Cross-navigation links */}
        <div className="w-full flex flex-col gap-1.5 text-xs">
          {alert.stationId && (
            <Link
              href={`/app/live-twin/stations/${alert.stationId}`}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground hover:underline transition-colors"
            >
              View Station Detail ({alert.stationId})
              <ArrowRight className="h-3 w-3" />
            </Link>
          )}

          {alert.vehicleId && (
            <Link
              href={`/app/vehicles/${alert.vehicleId}`}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground hover:underline transition-colors"
            >
              View Vehicle Detail ({alert.vehicleId})
              <ArrowRight className="h-3 w-3" />
            </Link>
          )}

          {alert.kind === "FLOW" && (
            <Link
              href="/app/flow"
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground hover:underline transition-colors"
            >
              View Flow Intelligence
              <ArrowRight className="h-3 w-3" />
            </Link>
          )}

          {alert.kind === "QUALITY" && (
            <Link
              href="/app/quality"
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground hover:underline transition-colors"
            >
              View Quality Intelligence
              <ArrowRight className="h-3 w-3" />
            </Link>
          )}
        </div>
      </CardFooter>
    </Card>
  );
}
