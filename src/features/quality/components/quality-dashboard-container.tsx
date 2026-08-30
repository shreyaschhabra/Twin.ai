/**
 * Quality Dashboard Container Component
 *
 * Toggles and holds client-side state for the selected vehicle on the
 * Quality Intelligence dashboard.
 */

"use client";

import { useState } from "react";
import type { QualityPrediction, ExposureCohort } from "@/types/quality";
import type { Vehicle } from "@/types/vehicle";
import { QualityRiskTable } from "./quality-risk-table";
import { QualityDetailsPanel } from "./quality-details-panel";

interface QualityDashboardContainerProps {
  predictions: QualityPrediction[];
  vehicles: Vehicle[];
}

export function QualityDashboardContainer({
  predictions,
  vehicles,
}: QualityDashboardContainerProps) {
  // Default selected vehicle ID to the one with the highest defect risk
  const sortedPredictions = [...predictions].sort((a, b) => b.defectRisk - a.defectRisk);
  const defaultSelectedId = sortedPredictions[0]?.vehicleId || "";

  const [selectedId, setSelectedId] = useState<string>(defaultSelectedId);

  const selectedPrediction = predictions.find((p) => p.vehicleId === selectedId) || predictions[0];
  const selectedVehicle = vehicles.find((v) => v.id === selectedId) || vehicles[0];

  return (
    <div className="grid gap-6 lg:grid-cols-3 items-start">
      {/* ── Monitored vehicle risk table (2/3 width on desktop) ── */}
      <div className="lg:col-span-2 space-y-4">
        <QualityRiskTable
          predictions={predictions}
          selectedVehicleId={selectedId}
          onSelectVehicle={setSelectedId}
        />
      </div>

      {/* ── Selected-vehicle risk progression & evidence (1/3 width on desktop) ── */}
      <div className="lg:col-span-1">
        {selectedPrediction ? (
          <QualityDetailsPanel
            prediction={selectedPrediction}
            sensorCoverage={selectedVehicle?.sensorCoverage}
          />
        ) : (
          <div className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">
            Select a vehicle from the table to view detailed quality analysis.
          </div>
        )}
      </div>
    </div>
  );
}
