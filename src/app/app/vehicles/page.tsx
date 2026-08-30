import { getVehicles } from "@/features/services";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertTriangle, Car, ShieldAlert, Eye, BarChart2 } from "lucide-react";
import { VehicleListTable } from "@/features/vehicles/components/vehicle-list-table";

export const revalidate = 0;

export default async function VehiclesPage() {
  const vehicles = await getVehicles();

  // ── KPI calculations ───────────────────────────────────────────────────────
  const vehiclesInLine = vehicles.length;
  const highRisk = vehicles.filter((v) => v.status === "HIGH_RISK").length;
  const watch = vehicles.filter((v) => v.status === "WATCH").length;
  const anomalyExposed = vehicles.filter((v) =>
    v.genealogy.some((e) => e.anomalyExposure),
  ).length;
  const avgRisk =
    vehicles.reduce((sum, v) => sum + v.qualityRisk, 0) / vehicles.length;

  return (
    <div className="space-y-6">
      {/* ── PAGE HEADER ── */}
      <div className="flex items-center justify-between border-b pb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-xl font-semibold tracking-tight">Vehicles</h1>
            <Badge variant="outline" className="text-xs font-normal text-muted-foreground">
              Demo Data
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Live vehicle monitoring — quality risk, sensor trust, and full build genealogy.
          </p>
        </div>
      </div>

      {/* ── KPI SUMMARY CARDS ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Car className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                In Line
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums">{vehiclesInLine}</p>
            <p className="text-xs text-muted-foreground mt-0.5">vehicles on line</p>
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-red-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                High Risk
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-red-700">{highRisk}</p>
            <p className="text-xs text-muted-foreground mt-0.5">require attention</p>
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <Eye className="h-4 w-4 text-amber-600" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Watch
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-amber-700">{watch}</p>
            <p className="text-xs text-muted-foreground mt-0.5">under observation</p>
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Anomaly Exposed
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-bold tabular-nums text-amber-700">{anomalyExposed}</p>
            <p className="text-xs text-muted-foreground mt-0.5">passed anomaly window</p>
          </CardContent>
        </Card>

        <Card className="border shadow-none">
          <CardHeader className="pb-1 pt-4 px-4">
            <div className="flex items-center gap-2">
              <BarChart2 className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Avg Risk
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p
              className={
                avgRisk >= 0.3
                  ? "text-2xl font-bold tabular-nums text-red-700"
                  : avgRisk >= 0.15
                  ? "text-2xl font-bold tabular-nums text-amber-700"
                  : "text-2xl font-bold tabular-nums text-emerald-700"
              }
            >
              {(avgRisk * 100).toFixed(1)}%
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">fleet average</p>
          </CardContent>
        </Card>
      </div>

      {/* ── VEHICLE TABLE ── */}
      <Card className="border shadow-none">
        <CardContent className="px-4 py-4">
          <VehicleListTable vehicles={vehicles} />
        </CardContent>
      </Card>
    </div>
  );
}
