/**
 * Flow Intelligence Page — /app/flow
 *
 * Predictive operational intelligence for developing production constraints.
 *
 * Architecture:
 *   page (server) → service layer → mock data
 *   Client interaction (search/filter/sort) handled by FlowPredictionTable
 *
 * Future:
 *   service layer → real Flow ML model API
 *   No page changes required.
 */

import Link from "next/link";
import {
  getFlowPredictions,
  getFlowSummary,
  getRelevantBuffersForFlow,
} from "@/features/services";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Activity,
  AlertTriangle,
  BarChart2,
  Clock,
  Layers,
  TrendingUp,
  Info,
} from "lucide-react";
import { HighestFlowRiskCard } from "@/features/flow/components/highest-flow-risk-card";
import { FlowPredictionTable } from "@/features/flow/components/flow-prediction-table";
import { BufferPressureTable } from "@/features/flow/components/buffer-pressure-table";
import { BenignVariationCard } from "@/features/flow/components/benign-variation-card";
import { cn } from "@/lib/utils";

export const revalidate = 0;

export default async function FlowPage() {
  // ── Data fetch via service layer only ─────────────────────────────────────
  const [predictions, summary, relevantBuffers] = await Promise.all([
    getFlowPredictions(),
    getFlowSummary(),
    getRelevantBuffersForFlow(),
  ]);

  // Sort predictions by risk descending (for display priority)
  const sortedPredictions = [...predictions].sort(
    (a, b) => b.bottleneckRisk - a.bottleneckRisk,
  );

  // Highest-risk prediction (precursor-first: exclude 0-onset unless it's the only one)
  const highestRisk =
    sortedPredictions.find(
      (p) => p.expectedOnsetMin > 0 && p.bottleneckRisk >= 0.7,
    ) ??
    sortedPredictions[0] ??
    null;

  // Get buffer adjacent to highest-risk station (feeding into it)
  const allBuffers = await import("@/data/mock/buffers").then((m) =>
    m.mockBuffers,
  );
  const highestRiskBuffer = highestRisk
    ? allBuffers.find(
        (b) => b.downstreamStationId === highestRisk.stationId,
      ) ?? null
    : null;

  // Benign variations: WATCH status only, low risk
  const benignVariations = predictions.filter(
    (p) => p.status === "WATCH" && p.bottleneckRisk < 0.5,
  );

  // Active escalations: WARNING or CRITICAL
  const activeEscalations = predictions.filter(
    (p) => p.status === "WARNING" || p.status === "CRITICAL",
  );

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-start justify-between gap-3 border-b pb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">
              Flow Intelligence
            </h1>
            <Badge
              variant="outline"
              className="text-xs font-normal text-muted-foreground"
            >
              Demo Data
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Predict developing production constraints before blocking, starvation
            or throughput loss occurs.
          </p>
        </div>
        <Link
          href="/app/live-twin"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors hover:underline shrink-0"
        >
          <Layers className="h-3.5 w-3.5" />
          View in Live Twin
        </Link>
      </div>

      {/* ── TOP KPI SUMMARY ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Monitored
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums">
              {summary.totalMonitored}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              stations tracked
            </p>
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-amber-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Elevated Risk
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-amber-700">
              {summary.elevatedCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Watch or above
            </p>
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Critical / High
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-red-700">
              {summary.criticalHighCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              require action
            </p>
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Median Onset
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {summary.medianOnsetMin !== null ? (
              <>
                <p className="text-2xl font-bold tabular-nums">
                  {summary.medianOnsetMin}
                  <span className="text-sm font-normal text-muted-foreground">
                    {" "}min
                  </span>
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  estimated
                </p>
              </>
            ) : (
              <>
                <p className="text-lg font-semibold text-muted-foreground">—</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  not projected
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <BarChart2 className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Buffers Pressured
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p
              className={cn(
                "text-2xl font-bold tabular-nums",
                summary.buffersNearCapacity > 0 ? "text-amber-700" : "text-emerald-700",
              )}
            >
              {summary.buffersNearCapacity}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              ≥75% capacity
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── HIGHEST PRIORITY WARNING ── */}
      {highestRisk ? (
        <HighestFlowRiskCard
          prediction={highestRisk}
          adjacentBuffer={highestRiskBuffer}
        />
      ) : (
        <Card className="border shadow-none">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No developing bottlenecks detected. Production flow is nominal.
          </CardContent>
        </Card>
      )}

      {/* ── ALL FLOW PREDICTIONS TABLE ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <CardTitle className="text-sm">Developing Bottlenecks</CardTitle>
              <CardDescription className="text-xs mt-0.5">
                All monitored flow predictions, ranked by operational importance.
                Risk and Confidence are independent values.
              </CardDescription>
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground border rounded px-2 py-1">
              <Info className="h-3 w-3" />
              Frontend categorization — demo data
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <FlowPredictionTable predictions={sortedPredictions} />
        </CardContent>
      </Card>

      {/* ── BUFFER PRESSURE ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Buffer Pressure</CardTitle>
          <CardDescription className="text-xs">
            Buffers adjacent to elevated-risk stations. Occupancy bar is a
            frontend display — thresholds are not model-calibrated.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <BufferPressureTable buffers={relevantBuffers} />
        </CardContent>
      </Card>

      {/* ── ACTIVE ESCALATIONS DETAIL ── */}
      {activeEscalations.length > 0 && (
        <Card className="border shadow-none">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Active Escalations</CardTitle>
            <CardDescription className="text-xs">
              Stations in WARNING or CRITICAL state with full evidence breakdown.
              Current state and predicted bottleneck risk are shown separately.
            </CardDescription>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-4">
            {activeEscalations.map((pred) => {
              const isBlockage =
                pred.expectedOnsetMin === 0 && pred.expectedOnsetMax === 0;
              return (
                <div
                  key={pred.stationId}
                  className={cn(
                    "rounded-md border p-4 space-y-3",
                    pred.status === "CRITICAL"
                      ? "border-red-200 bg-red-50/40"
                      : "border-orange-200 bg-orange-50/20",
                  )}
                >
                  {/* Header */}
                  <div className="flex items-start justify-between flex-wrap gap-2">
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <Link
                          href={`/app/live-twin/stations/${pred.stationId}`}
                          className="font-mono font-bold text-sm hover:underline"
                        >
                          {pred.stationId}
                        </Link>
                        <span className="text-sm text-muted-foreground">
                          {pred.stationName}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={cn(
                          "text-lg font-extrabold tabular-nums",
                          pred.bottleneckRisk >= 0.7
                            ? "text-red-700"
                            : "text-amber-700",
                        )}
                      >
                        {Math.round(pred.bottleneckRisk * 100)}%
                      </span>
                      <span className="text-xs text-muted-foreground">
                        bottleneck risk
                      </span>
                    </div>
                  </div>

                  {/* Current state vs prediction — clearly separated */}
                  <div className="flex flex-wrap gap-4 text-xs">
                    <div>
                      <p className="text-muted-foreground uppercase text-[10px] tracking-wide">
                        Current State
                      </p>
                      <p className="font-semibold">
                        {isBlockage ? "BLOCKED" : "PROCESSING"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground uppercase text-[10px] tracking-wide">
                        {isBlockage ? "Impact" : "Predicted Impact"}
                      </p>
                      <p className="font-semibold">
                        {isBlockage
                          ? "Active now"
                          : `${pred.expectedOnsetMin}–${pred.expectedOnsetMax} min`}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground uppercase text-[10px] tracking-wide">
                        Confidence
                      </p>
                      <p
                        className={cn(
                          "font-semibold",
                          pred.confidence === "HIGH"
                            ? "text-emerald-700"
                            : pred.confidence === "MEDIUM"
                            ? "text-amber-700"
                            : "text-red-700",
                        )}
                      >
                        {pred.confidence}
                      </p>
                    </div>
                  </div>

                  {/* Evidence */}
                  <div className="space-y-1">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                      Contributing Signals
                    </p>
                    <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                      {pred.evidence.map((item, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between p-1.5 rounded border bg-background text-xs font-mono"
                        >
                          <span className="text-muted-foreground truncate mr-2">
                            {item.label}
                          </span>
                          <span
                            className={cn(
                              "font-medium shrink-0",
                              item.direction === "negative"
                                ? "text-red-700"
                                : item.direction === "positive"
                                ? "text-emerald-700"
                                : "text-muted-foreground",
                            )}
                          >
                            {item.value}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Propagation */}
                  {(pred.affectedUpstreamStations.length > 0 ||
                    pred.affectedDownstreamStations.length > 0) && (
                    <div className="space-y-1 border-t pt-2">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                        Potential Propagation
                      </p>
                      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                        {pred.affectedUpstreamStations.length > 0 && (
                          <span>
                            Upstream likely pressure:{" "}
                            {pred.affectedUpstreamStations.map((sid, i) => (
                              <span key={sid}>
                                <Link
                                  href={`/app/live-twin/stations/${sid}`}
                                  className="font-mono text-foreground hover:underline"
                                >
                                  {sid}
                                </Link>
                                {i < pred.affectedUpstreamStations.length - 1 && ", "}
                              </span>
                            ))}
                          </span>
                        )}
                        {pred.affectedDownstreamStations.length > 0 && (
                          <span>
                            Downstream starvation risk:{" "}
                            {pred.affectedDownstreamStations.map((sid, i) => (
                              <span key={sid}>
                                <Link
                                  href={`/app/live-twin/stations/${sid}`}
                                  className="font-mono text-foreground hover:underline"
                                >
                                  {sid}
                                </Link>
                                {i < pred.affectedDownstreamStations.length - 1 && ", "}
                              </span>
                            ))}
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Nav */}
                  <div className="flex gap-3 pt-1">
                    <Link
                      href={`/app/live-twin/stations/${pred.stationId}`}
                      className="text-xs font-medium hover:underline"
                    >
                      View Station Detail →
                    </Link>
                    <Link
                      href="/app/live-twin"
                      className="text-xs text-muted-foreground hover:text-foreground hover:underline transition-colors"
                    >
                      View in Live Twin
                    </Link>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* ── BENIGN VARIATIONS ── */}
      {benignVariations.length > 0 && (
        <div className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold">Monitored Variations</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Elevated cycle-time observations that are NOT projected to create
              system-level bottleneck impact. Shown to prevent false-alarm
              escalation.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {benignVariations.map((pred) => (
              <BenignVariationCard key={pred.stationId} prediction={pred} />
            ))}
          </div>
        </div>
      )}

      {/* ── EMPTY STATE ── */}
      {predictions.length === 0 && (
        <Card className="border shadow-none">
          <CardContent className="py-12 text-center space-y-2">
            <p className="text-sm font-medium">No active flow predictions</p>
            <p className="text-xs text-muted-foreground">
              No stations are currently being monitored or no predictions are
              available.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
