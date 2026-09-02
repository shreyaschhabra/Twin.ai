import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  AlertTriangle,
  Car,
  ShieldAlert,
  Eye,
  Activity,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  getVehicleById,
  getVehicleGenealogy,
  getQualityPredictionByVehicle,
  getExposureCohortById,
} from "@/features/services";
import { RiskProgressionChart } from "@/features/vehicles/components/risk-progression-chart";
import { VehicleGenealogyTimeline } from "@/features/vehicles/components/vehicle-genealogy-timeline";
import { cn } from "@/lib/utils";

export const revalidate = 0;

interface VehicleDetailPageProps {
  params: Promise<{ vehicleId: string }>;
}

function variantLabel(v: string) {
  switch (v) {
    case "ICE_SEDAN":
      return "ICE Sedan";
    case "ICE_SUV":
      return "ICE SUV";
    case "EV":
      return "EV";
    default:
      return v;
  }
}

function statusBadge(status: string) {
  switch (status) {
    case "HIGH_RISK":
      return (
        <Badge className="bg-red-100 text-red-800 border-red-200 gap-1">
          <ShieldAlert className="h-3 w-3" />
          High Risk
        </Badge>
      );
    case "WATCH":
      return (
        <Badge className="bg-amber-100 text-amber-800 border-amber-200 gap-1">
          <Eye className="h-3 w-3" />
          Watch
        </Badge>
      );
    case "ON_TRACK":
      return (
        <Badge className="bg-emerald-100 text-emerald-800 border-emerald-200 gap-1">
          On Track
        </Badge>
      );
    case "COMPLETE":
      return (
        <Badge className="bg-slate-100 text-slate-600 border-slate-200">
          Complete
        </Badge>
      );
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function riskClass(risk: number) {
  if (risk >= 0.5) return "text-red-700";
  if (risk >= 0.2) return "text-amber-700";
  return "text-emerald-700";
}

export default async function VehicleDetailPage({
  params,
}: VehicleDetailPageProps) {
  const { vehicleId } = await params;

  const vehicle = await getVehicleById(vehicleId);
  if (!vehicle) notFound();

  const genealogy = await getVehicleGenealogy(vehicleId);
  const qualityPred = await getQualityPredictionByVehicle(vehicleId);

  // If vehicle has an exposure cohort on its quality prediction, load it
  const cohort = qualityPred?.exposureCohortId
    ? await getExposureCohortById(qualityPred.exposureCohortId)
    : null;

  const hasAnomaly = genealogy.some((e) => e.anomalyExposure);

  return (
    <div className="space-y-6">
      {/* ── HEADER NAVIGATION ── */}
      <div className="space-y-2 border-b pb-4">
        <Link
          href="/app/vehicles"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground font-semibold transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Vehicles
        </Link>

        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-semibold font-mono tracking-tight">
                {vehicle.id}
              </h1>
              {statusBadge(vehicle.status)}
              <Badge variant="outline" className="text-xs font-normal text-muted-foreground">
                Demo Data
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {variantLabel(vehicle.variant)} · {vehicle.currentStage} ·{" "}
              <Link
                href={`/app/live-twin/stations/${vehicle.currentStationId}`}
                className="font-mono text-foreground hover:underline"
              >
                {vehicle.currentStationId}
              </Link>
            </p>
          </div>

          {hasAnomaly && (
            <div className="flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2.5 py-1.5">
              <AlertTriangle className="h-3.5 w-3.5" />
              Anomaly Exposure on Record
            </div>
          )}
        </div>
      </div>

      {/* ── TOP ROW — Quality Risk + Sensor Trust ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Quality Risk Card */}
        <Card className="border shadow-none">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm">Quality Risk</CardTitle>
            </div>
            <CardDescription className="text-xs">
              Current cumulative defect risk from the prediction model.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-end gap-3">
              <span
                className={cn(
                  "text-4xl font-bold tabular-nums",
                  riskClass(vehicle.qualityRisk),
                )}
              >
                {(vehicle.qualityRisk * 100).toFixed(0)}%
              </span>
              <div className="mb-1 space-y-0.5">
                <p className="text-xs text-muted-foreground">defect risk</p>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">
                    Confidence:
                  </span>
                  <span
                    className={cn(
                      "text-xs font-medium",
                      vehicle.confidence === "HIGH"
                        ? "text-emerald-700"
                        : vehicle.confidence === "MEDIUM"
                        ? "text-amber-700"
                        : "text-red-700",
                    )}
                  >
                    {vehicle.confidence}
                  </span>
                </div>
              </div>
            </div>

            {/* Risk bar */}
            <div className="space-y-1">
              <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                <div
                  className={cn(
                    "h-2 rounded-full transition-all",
                    vehicle.qualityRisk >= 0.5
                      ? "bg-red-500"
                      : vehicle.qualityRisk >= 0.2
                      ? "bg-amber-500"
                      : "bg-emerald-500",
                  )}
                  style={{ width: `${vehicle.qualityRisk * 100}%` }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>0%</span>
                <span className="text-amber-600">20% Watch</span>
                <span className="text-red-600">50% High Risk</span>
                <span>100%</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Sensor Trust History */}
        <Card className="border shadow-none">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Car className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm">Sensor Trust Coverage</CardTitle>
            </div>
            <CardDescription className="text-xs">
              Breakdown of measurement source across this vehicle's production
              history.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Stacked bar */}
            <div className="h-5 w-full flex rounded-full overflow-hidden">
              <div
                className="bg-emerald-500 h-full"
                style={{ width: `${vehicle.sensorCoverage.livePercent}%` }}
                title={`Live: ${vehicle.sensorCoverage.livePercent}%`}
              />
              <div
                className="bg-amber-400 h-full"
                style={{ width: `${vehicle.sensorCoverage.inferredPercent}%` }}
                title={`Inferred: ${vehicle.sensorCoverage.inferredPercent}%`}
              />
              <div
                className="bg-slate-300 h-full"
                style={{ width: `${vehicle.sensorCoverage.unknownPercent}%` }}
                title={`Unknown: ${vehicle.sensorCoverage.unknownPercent}%`}
              />
            </div>

            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <p className="text-sm font-semibold text-emerald-700 tabular-nums">
                  {vehicle.sensorCoverage.livePercent}%
                </p>
                <p className="text-[10px] text-muted-foreground">Live</p>
              </div>
              <div>
                <p className="text-sm font-semibold text-amber-700 tabular-nums">
                  {vehicle.sensorCoverage.inferredPercent}%
                </p>
                <p className="text-[10px] text-muted-foreground">
                  Inferred (proxy)
                </p>
              </div>
              <div>
                <p
                  className={cn(
                    "text-sm font-semibold tabular-nums",
                    vehicle.sensorCoverage.unknownPercent > 10
                      ? "text-red-700"
                      : "text-slate-600",
                  )}
                >
                  {vehicle.sensorCoverage.unknownPercent}%
                </p>
                <p className="text-[10px] text-muted-foreground">Unavailable</p>
              </div>
            </div>

            {vehicle.sensorCoverage.unknownPercent > 0 && (
              <p className="text-[10px] text-muted-foreground border-t pt-2">
                Unavailable measurements could not be verified or reconstructed.
                Risk estimates for affected stations should be treated with
                additional caution.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── RISK PROGRESSION CHART ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Risk Progression</CardTitle>
          <CardDescription className="text-xs">
            Cumulative defect risk score after each station passage. Amber
            outlined dots indicate anomaly exposure windows.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RiskProgressionChart genealogy={genealogy} />
        </CardContent>
      </Card>

      {/* ── GENEALOGY TIMELINE ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Build Genealogy</CardTitle>
          <CardDescription className="text-xs">
            Full production history — one entry per station visited. Future
            stations are not shown.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <VehicleGenealogyTimeline
            genealogy={genealogy}
            currentStationId={vehicle.currentStationId}
          />
        </CardContent>
      </Card>

      {/* ── ANOMALY EXPOSURE COHORT ── */}
      {cohort && (
        <Card className="border border-amber-200 shadow-none bg-amber-50/40">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              <CardTitle className="text-sm">Anomaly Exposure Cohort</CardTitle>
            </div>
            <CardDescription className="text-xs">
              This vehicle was in the production line during a detected anomaly
              window at {cohort.stationId}. Cohort ID:{" "}
              <span className="font-mono">{cohort.id}</span>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">{cohort.description}</p>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {(cohort.evidence ?? []).map((ev) => (
                <div
                  key={ev.label}
                  className="rounded border bg-background p-2 space-y-0.5"
                >
                  <p className="text-[10px] text-muted-foreground">{ev.label}</p>
                  <p
                    className={cn(
                      "text-xs font-medium",
                      ev.direction === "negative"
                        ? "text-red-700"
                        : ev.direction === "positive"
                        ? "text-emerald-700"
                        : "text-foreground",
                    )}
                  >
                    {ev.value}
                  </p>
                </div>
              ))}
            </div>

            <div className="flex gap-3 flex-wrap text-xs text-muted-foreground border-t pt-2">
              <span>
                Window:{" "}
                <span className="font-mono text-foreground">
                  {new Date(cohort.startTime).toLocaleTimeString("en-GB", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}{" "}
                  –{" "}
                  {new Date(cohort.endTime).toLocaleTimeString("en-GB", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </span>
              <span>
                Affected vehicles:{" "}
                <span className="text-foreground font-medium">
                  {cohort.affectedVehicleIds.length}
                </span>
              </span>
            </div>

            <Link
              href="/app/quality"
              className="inline-flex items-center gap-1 text-xs text-blue-700 hover:underline font-medium"
            >
              View Quality Intelligence dashboard →
            </Link>
          </CardContent>
        </Card>
      )}

      {/* ── QUALITY EVIDENCE ── */}
      {qualityPred && qualityPred.evidence && qualityPred.evidence.length > 0 && (
        <Card className="border shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Quality Evidence</CardTitle>
            <CardDescription className="text-xs">
              Contributing signals observed for this vehicle. These are
              correlations — not causal determinations.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="divide-y">
              {qualityPred.evidence.map((ev) => (
                <div
                  key={ev.label}
                  className="flex items-center justify-between py-2 gap-3"
                >
                  <span className="text-xs text-muted-foreground">
                    {ev.label}
                  </span>
                  <span
                    className={cn(
                      "text-xs font-medium text-right",
                      ev.direction === "negative"
                        ? "text-red-700"
                        : ev.direction === "positive"
                        ? "text-emerald-700"
                        : "text-foreground",
                    )}
                  >
                    {ev.value}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── CROSS NAVIGATION ── */}
      <div className="flex flex-wrap gap-3 border-t pt-4">
        <Link
          href={`/app/live-twin/stations/${vehicle.currentStationId}`}
          className="inline-flex items-center gap-1.5 text-sm text-blue-700 hover:underline font-medium"
        >
          View current station ({vehicle.currentStationId}) →
        </Link>
        <Link
          href="/app/quality"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground hover:underline transition-colors"
        >
          Quality Intelligence →
        </Link>
        <Link
          href="/app/vehicles"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground hover:underline transition-colors"
        >
          ← All Vehicles
        </Link>
      </div>
    </div>
  );
}
