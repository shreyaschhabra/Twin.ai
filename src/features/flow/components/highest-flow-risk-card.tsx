/**
 * Highest Flow Risk Card
 *
 * Prominent priority warning for the highest-risk developing bottleneck.
 * Separated from bottleneck-risk-card (used in overview) — this version
 * includes propagation paths, current state, and cross-navigation links.
 */

import Link from "next/link";
import { ArrowRight, AlertTriangle, TrendingUp, ArrowUpRight, ArrowDownRight } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import { FlowRiskBadge } from "./flow-risk-badge";
import type { FlowPrediction } from "@/types/flow";
import type { Buffer } from "@/types/buffer";
import { cn } from "@/lib/utils";

interface HighestFlowRiskCardProps {
  prediction: FlowPrediction;
  adjacentBuffer: Buffer | null;
}

function riskClass(risk: number) {
  if (risk >= 0.7) return "text-red-700";
  if (risk >= 0.2) return "text-amber-700";
  return "text-emerald-700";
}

function onsetLabel(min: number, max: number): string {
  if (min === 0 && max === 0) return "Active now";
  if (min === max) return `${min} min`;
  return `${min}–${max} min`;
}

export function HighestFlowRiskCard({
  prediction,
  adjacentBuffer,
}: HighestFlowRiskCardProps) {
  const riskPct = Math.round(prediction.bottleneckRisk * 100);
  const isActiveBlockage =
    prediction.expectedOnsetMin === 0 && prediction.expectedOnsetMax === 0;

  return (
    <Card className="border-2 border-red-200 shadow-none bg-red-50/30">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" aria-hidden="true" />
              <CardTitle className="text-sm font-semibold">
                Highest Priority Flow Warning
              </CardTitle>
            </div>
            <CardDescription className="text-xs">
              Most urgent developing bottleneck currently monitored.
              {" "}
              <span className="text-muted-foreground">
                Frontend categorization — demo data.
              </span>
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <FlowRiskBadge status={prediction.status} />
            <ConfidenceBadge confidence={prediction.confidence} />
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* ── Station + Core Metrics ── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {/* Station */}
          <div className="col-span-2 sm:col-span-1 space-y-0.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Station
            </p>
            <p className="text-lg font-bold font-mono">{prediction.stationId}</p>
            <p className="text-xs text-muted-foreground truncate">
              {prediction.stationName}
            </p>
          </div>

          {/* Bottleneck Risk — SEPARATE from Confidence */}
          <div className="space-y-0.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Bottleneck Risk
            </p>
            <p className={cn("text-3xl font-extrabold tabular-nums", riskClass(prediction.bottleneckRisk))}>
              {riskPct}%
            </p>
            <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full",
                  riskPct >= 70 ? "bg-red-500" : riskPct >= 20 ? "bg-amber-500" : "bg-emerald-500",
                )}
                style={{ width: `${riskPct}%` }}
              />
            </div>
          </div>

          {/* Expected Impact — clearly "predicted", not "current" */}
          <div className="space-y-0.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              {isActiveBlockage ? "Current State" : "Predicted Impact"}
            </p>
            {isActiveBlockage ? (
              <Badge className="bg-red-100 text-red-800 border-red-200 font-semibold">
                BLOCKED — Active
              </Badge>
            ) : (
              <>
                <p className="text-2xl font-bold tabular-nums text-foreground">
                  {onsetLabel(prediction.expectedOnsetMin, prediction.expectedOnsetMax)}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  estimated onset window
                </p>
              </>
            )}
          </div>

          {/* Adjacent buffer */}
          {adjacentBuffer && (
            <div className="space-y-0.5">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                Upstream Buffer
              </p>
              <p className="text-2xl font-bold tabular-nums">
                {adjacentBuffer.currentWip}
                <span className="text-sm font-normal text-muted-foreground">
                  {" "}/ {adjacentBuffer.capacity}
                </span>
              </p>
              <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full",
                    adjacentBuffer.occupancyRatio >= 0.85
                      ? "bg-red-500"
                      : adjacentBuffer.occupancyRatio >= 0.65
                      ? "bg-amber-500"
                      : "bg-emerald-500",
                  )}
                  style={{ width: `${Math.round(adjacentBuffer.occupancyRatio * 100)}%` }}
                />
              </div>
              <p className="text-[10px] text-muted-foreground">
                {Math.round(adjacentBuffer.occupancyRatio * 100)}% capacity
                {adjacentBuffer.growthRate && adjacentBuffer.growthRate > 0 ? " · growing" : ""}
              </p>
            </div>
          )}
        </div>

        {/* ── Evidence ── */}
        <div className="border-t pt-3 space-y-2">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
            Contributing Signals
          </p>
          <ul className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {prediction.evidence.map((item, idx) => (
              <li
                key={idx}
                className="flex items-center justify-between p-2 rounded border bg-background text-xs font-mono"
              >
                <span className="text-muted-foreground truncate mr-2">{item.label}</span>
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
              </li>
            ))}
          </ul>
        </div>

        {/* ── Propagation ── */}
        {(prediction.affectedUpstreamStations.length > 0 ||
          prediction.affectedDownstreamStations.length > 0) && (
          <div className="border-t pt-3 space-y-2">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              Potential Propagation
            </p>
            <div className="flex flex-wrap gap-4 text-xs">
              {prediction.affectedUpstreamStations.length > 0 && (
                <div className="space-y-1">
                  <span className="inline-flex items-center gap-1 text-muted-foreground">
                    <ArrowUpRight className="h-3 w-3" />
                    Upstream pressure
                  </span>
                  <div className="flex gap-1 flex-wrap">
                    {prediction.affectedUpstreamStations.map((sid) => (
                      <Link
                        key={sid}
                        href={`/app/live-twin/stations/${sid}`}
                        className="font-mono text-[10px] px-1.5 py-0.5 rounded border bg-amber-50 text-amber-700 border-amber-200 hover:underline"
                      >
                        {sid}
                      </Link>
                    ))}
                  </div>
                </div>
              )}
              {prediction.affectedDownstreamStations.length > 0 && (
                <div className="space-y-1">
                  <span className="inline-flex items-center gap-1 text-muted-foreground">
                    <ArrowDownRight className="h-3 w-3" />
                    Downstream starvation risk
                  </span>
                  <div className="flex gap-1 flex-wrap">
                    {prediction.affectedDownstreamStations.map((sid) => (
                      <Link
                        key={sid}
                        href={`/app/live-twin/stations/${sid}`}
                        className="font-mono text-[10px] px-1.5 py-0.5 rounded border bg-blue-50 text-blue-700 border-blue-200 hover:underline"
                      >
                        {sid}
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Navigation ── */}
        <div className="border-t pt-3 flex flex-wrap gap-3">
          <Link
            href={`/app/live-twin/stations/${prediction.stationId}`}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground hover:underline"
          >
            <TrendingUp className="h-3.5 w-3.5" />
            View Station Detail ({prediction.stationId})
          </Link>
          <Link
            href="/app/live-twin"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground hover:underline transition-colors"
          >
            View in Live Twin
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
