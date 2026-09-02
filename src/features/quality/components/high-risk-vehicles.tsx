import Link from "next/link";
import { Car } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { ConfidenceBadge } from "@/features/trust/components/confidence-badge";
import type { QualityPrediction } from "@/types/quality";
import { cn } from "@/lib/utils";

interface HighRiskVehiclesProps {
  predictions: QualityPrediction[];
}

export function HighRiskVehicles({ predictions }: HighRiskVehiclesProps) {
  // Sort by defect risk descending, pick top 5
  const topVehicles = [...predictions]
    .sort((a, b) => b.defectRisk - a.defectRisk)
    .slice(0, 5);

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4">
        <div>
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <Car className="h-4 w-4 text-orange-500 shrink-0" />
            High-Risk Vehicles Cohort
          </CardTitle>
          <CardDescription className="text-xs text-muted-foreground">
            Active assemblies carrying the highest accumulated defect risk probabilities.
          </CardDescription>
        </div>
        <Link
          href="/app/vehicles"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-3 text-xs font-medium text-foreground hover:bg-accent transition-colors self-start sm:self-center"
        >
          View All Vehicles
        </Link>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto select-none">
          <table className="w-full text-sm text-left border-t">
            <thead className="text-[10px] text-muted-foreground uppercase tracking-wider bg-muted/20 font-mono">
              <tr>
                <th className="px-6 py-3 border-b">Vehicle ID</th>
                <th className="px-6 py-3 border-b">Variant</th>
                <th className="px-6 py-3 border-b">Current Stage</th>
                <th className="px-6 py-3 border-b text-right">Defect Risk</th>
                <th className="px-6 py-3 border-b text-right">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y font-mono">
              {topVehicles.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-xs text-muted-foreground">
                    No high-risk vehicles detected. All tracking assemblies normal.
                  </td>
                </tr>
              ) : (
                topVehicles.map((vehicle) => {
                  const riskPercent = Math.round(vehicle.defectRisk * 100);
                  const isCritical = vehicle.defectRisk >= 0.7;
                  const isWarning = vehicle.defectRisk >= 0.2 && vehicle.defectRisk < 0.7;

                  return (
                    <tr key={vehicle.vehicleId} className="hover:bg-muted/10">
                      <td className="px-6 py-3 font-semibold text-foreground">
                        {vehicle.vehicleId}
                      </td>
                      <td className="px-6 py-3 text-xs uppercase text-muted-foreground font-sans">
                        {vehicle.variant.replace("_", " ")}
                      </td>
                      <td className="px-6 py-3 text-xs text-muted-foreground font-sans">
                        {vehicle.currentStage}
                      </td>
                      <td className={cn(
                        "px-6 py-3 text-right text-base font-bold",
                        isCritical
                          ? "text-rose-600 dark:text-rose-400"
                          : isWarning
                          ? "text-amber-600 dark:text-amber-400"
                          : "text-emerald-600 dark:text-emerald-400"
                      )}>
                        {riskPercent}%
                      </td>
                      <td className="px-6 py-3 text-right">
                        <ConfidenceBadge confidence={vehicle.confidence} />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
