/**
 * Quality Intelligence Page — /app/quality
 *
 * Tracks vehicle-level defect risk estimates, anomaly exposure cohorts,
 * process deviation evidence, and telemetry trust.
 */

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import {
  ShieldAlert,
  Car,
  Activity,
  Layers,
  HelpCircle,
  Users,
  Eye,
  AlertTriangle,
} from "lucide-react";
import {
  getQualityPredictions,
  getQualitySummary,
  getExposureCohorts,
  getVehicles,
} from "@/features/services";
import { HighRiskQualityCard } from "@/features/quality/components/high-risk-quality-card";
import { QualityDashboardContainer } from "@/features/quality/components/quality-dashboard-container";
import { ExposureCohortList } from "@/features/quality/components/exposure-cohort-list";
import { AnomalySummary } from "@/features/quality/components/anomaly-summary";
import { cn } from "@/lib/utils";

export const revalidate = 0;

export default async function QualityPage() {
  // Fetch all required data through the service layer
  const [predictions, summary, cohorts, vehicles] = await Promise.all([
    getQualityPredictions(),
    getQualitySummary(),
    getExposureCohorts(),
    getVehicles(),
  ]);

  // Find the prediction with the highest defect risk
  const highestRiskPrediction = predictions.reduce<any | null>((max, p) => {
    if (!max || p.defectRisk > max.defectRisk) return p;
    return max;
  }, null);

  // Build the vehicleRisks lookup map for ExposureCohortList
  const vehicleRisks: Record<string, { risk: number; status: string }> = {};
  predictions.forEach((p) => {
    vehicleRisks[p.vehicleId] = { risk: p.defectRisk, status: p.status };
  });
  // Fallback map from mockVehicles if a prediction doesn't exist
  vehicles.forEach((v) => {
    if (!vehicleRisks[v.id]) {
      vehicleRisks[v.id] = {
        risk: v.qualityRisk,
        status: v.status === "HIGH_RISK" ? "HIGH" : v.status === "WATCH" ? "WATCH" : "LOW",
      };
    }
  });

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-start justify-between gap-3 border-b pb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">
              Quality Intelligence
            </h1>
            <Badge
              variant="outline"
              className="text-xs font-normal text-muted-foreground"
            >
              Demo Data
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Track developing vehicle-level defect risk and process exposure before
            downstream quality inspection.
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

      {/* ── TOP QUALITY SUMMARY METRICS ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {/* Monitored Vehicles */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Car className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Vehicles Monitored
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums">
              {summary.totalMonitored}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              active assemblies
            </p>
          </CardContent>
        </Card>

        {/* High Risk Count */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-red-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                High-Risk Vehicles
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-red-700">
              {summary.highRiskCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              defect risk ≥50%
            </p>
          </CardContent>
        </Card>

        {/* Watch Vehicles */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Watch Vehicles
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-amber-700">
              {summary.watchCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              defect risk 20% – 50%
            </p>
          </CardContent>
        </Card>

        {/* Active Exposure Cohorts */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Exposure Cohorts
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-foreground">
              {summary.activeCohortCount}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              process anomalies
            </p>
          </CardContent>
        </Card>

        {/* Highest Defect Risk */}
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Highest Defect Risk
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-red-700">
              {Math.round(summary.highestRisk * 100)}%
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              peak probability
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── PRIMARY HIGH-RISK VEHICLE WARNING ── */}
      {highestRiskPrediction ? (
        <HighRiskQualityCard prediction={highestRiskPrediction} />
      ) : (
        <Card className="border shadow-none">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No high-risk quality deviations detected. Fleet is within nominal control limits.
          </CardContent>
        </Card>
      )}

      {/* ── MONITORED VEHICLE RISK TABLE + selected vehicle details side-by-side ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <CardTitle className="text-sm font-semibold">Monitored Vehicle Risks</CardTitle>
              <CardDescription className="text-xs mt-0.5">
                All vehicles active on the production line, ranked by defect risk. Click a row to view detailed telemetry analysis on the right panel.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-4 px-4 pb-4">
          <QualityDashboardContainer
            predictions={predictions}
            vehicles={vehicles}
          />
        </CardContent>
      </Card>

      {/* ── EXPOSURE COHORTS ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">Process Anomaly Exposure Cohorts</CardTitle>
          <CardDescription className="text-xs">
            Groupings of assemblies that passed through specific stations during identified anomaly windows. An anomaly-exposed vehicle is NOT automatically defective.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-4 px-4 pb-4">
          <ExposureCohortList
            cohorts={cohorts}
            vehicleRisks={vehicleRisks}
          />
        </CardContent>
      </Card>

      {/* ── ACTIVE PROCESS ANOMALIES SUMMARY ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold">Active Process Anomalies</CardTitle>
          <CardDescription className="text-xs">
            Summary of all active station process out-of-control conditions. Anomaly signals represent unusual process behavior, not defects.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <AnomalySummary cohorts={cohorts} />
        </CardContent>
      </Card>

      {/* ── ANOMALY VS DEFECT EXPLANATORY disclamer card ── */}
      <Card className="border shadow-none bg-slate-50 border-slate-200">
        <CardContent className="py-4 text-xs text-muted-foreground flex items-start gap-2">
          <HelpCircle className="h-4 w-4 shrink-0 text-slate-500 mt-0.5" />
          <div>
            <p className="font-semibold text-slate-700 mb-0.5">Statistical Anomaly vs. Quality Defect</p>
            <p>
              Process anomalies represent out-of-control signals detected at the station level (e.g., clamp pressure deviation, cycle-time spikes). Quality defect risk is calculated at the vehicle level by correlating telemetry gaps and sequence patterns across multiple stations. An assembly exposed to an anomaly is flagged for review but is not classified as defective unless downstream Quality Control (QC) inspection confirms a failure.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
