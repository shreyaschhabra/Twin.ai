"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { StationNode } from "./station-node";
import { BufferNode } from "./buffer-node";
import { LiveTwinLegend } from "./live-twin-legend";
import type { Station } from "@/types/station";
import type { Buffer } from "@/types/buffer";
import type { Vehicle } from "@/types/vehicle";
import type { FlowPrediction } from "@/types/flow";
import { Button } from "@/components/ui/button";

interface LiveTwinCanvasProps {
  stations: Station[];
  buffers: Buffer[];
  vehicles: Vehicle[];
  flowPredictions: FlowPrediction[];
}

type ZoneConfig = {
  id: string;
  title: string;
  stationIds: string[];
};

const ZONES: ZoneConfig[] = [
  { id: "body-joining", title: "Zone 1: Body Shop / Joining", stationIds: ["S01", "S02", "S03", "S04", "S05", "S06"] },
  { id: "adhesive-sealing", title: "Zone 2: Adhesive / Sealing", stationIds: ["S07", "S08", "S09", "S10"] },
  { id: "robotic-assembly", title: "Zone 3: Robotic Handling / Assembly", stationIds: ["S11", "S12", "S13", "S14", "S15"] },
  { id: "dimensional-inspection", title: "Zone 4: Dimensional Inspection", stationIds: ["S16", "S17", "S18"] },
  { id: "paint-coating", title: "Zone 5: Paint / Coating", stationIds: ["S19", "S20", "S21", "S22", "S23"] },
  { id: "curing-environmental", title: "Zone 6: Curing / Environmental Process", stationIds: ["S24", "S25", "S26", "S27"] },
  { id: "manual-assembly", title: "Zone 7: Manual Assembly", stationIds: ["S28", "S29", "S30", "S31", "S32"] },
  { id: "torque-fastening", title: "Zone 8: Torque / Fastening", stationIds: ["S33", "S34", "S35", "S36"] },
  { id: "fluid-fill", title: "Zone 9: Fluid Fill & Charge (Branching)", stationIds: ["S37", "S38", "S39", "S40"] },
  { id: "eol-testing", title: "Zone 10: Inspection / End-of-Line Testing", stationIds: ["S41", "S42", "S43", "S44", "S45"] },
];

// Virtual EV branch node for S37 parallel pathway demonstration
const VIRTUAL_S37_EV: Station = {
  id: "S37-EV",
  name: "Battery Coolant Fill",
  type: "Fluid Fill / Functional Process",
  operation: "Automated high-voltage battery coolant fill cycle",
  state: "PROCESSING",
  baselineCycleTime: 65,
  currentCycleTime: 65,
  upstreamBufferId: "B36",
  downstreamBufferId: "B37",
  sensorMaturity: "RICH",
  sensorTrustState: "LIVE",
  confidence: "HIGH",
};

function verifyTopologyIntegrity(
  stations: Station[],
  buffers: Buffer[],
  vehicles: Vehicle[],
  flowPredictions: FlowPrediction[]
) {
  // 1. Exactly 45 stations in stations array
  if (stations.length !== 45) {
    throw new Error(`[Topology Integrity] Expected 45 stations, but getStations() returned ${stations.length}.`);
  }

  // 2. Check ZONES coverage
  const allZoneStationIds = ZONES.flatMap((z) => z.stationIds);
  
  // No duplicates in ZONES mapping
  const uniqueMappedIds = new Set(allZoneStationIds);
  if (uniqueMappedIds.size !== allZoneStationIds.length) {
    const dupes = allZoneStationIds.filter((id, i) => allZoneStationIds.indexOf(id) !== i);
    throw new Error(`[Topology Integrity] Duplicate station IDs mapped in ZONES: ${dupes.join(", ")}`);
  }

  // Check for any unmapped stations or unknown stations
  const stationIdsSet = new Set(stations.map((s) => s.id));
  for (const s of stations) {
    if (!uniqueMappedIds.has(s.id)) {
      throw new Error(`[Topology Integrity] Station ${s.id} is not mapped to any Zone in ZONES.`);
    }
  }

  for (const id of allZoneStationIds) {
    if (!stationIdsSet.has(id)) {
      throw new Error(`[Topology Integrity] Zone refers to unknown station ID: ${id}`);
    }
  }

  // 3. Resolve buffers
  for (const b of buffers) {
    if (b.upstreamStationId !== "B00" && !stationIdsSet.has(b.upstreamStationId)) {
      throw new Error(`[Topology Integrity] Buffer ${b.id} refers to unknown upstreamStationId: ${b.upstreamStationId}`);
    }
    if (!stationIdsSet.has(b.downstreamStationId)) {
      throw new Error(`[Topology Integrity] Buffer ${b.id} refers to unknown downstreamStationId: ${b.downstreamStationId}`);
    }
  }

  // 4. Resolve vehicles
  for (const v of vehicles) {
    if (!stationIdsSet.has(v.currentStationId) && v.currentStationId !== "S37-EV") {
      throw new Error(`[Topology Integrity] Vehicle ${v.id} references invalid station ID: ${v.currentStationId}`);
    }
  }

  // 5. Resolve flow predictions
  for (const fp of flowPredictions) {
    if (!stationIdsSet.has(fp.stationId)) {
      throw new Error(`[Topology Integrity] Flow prediction references invalid station ID: ${fp.stationId}`);
    }
  }

  // Print zone counts to developer console
  console.log("══════════════════════════════════════════");
  console.log("LIVE TWIN TOPOLOGY INTEGRITY CHECKS PASSED");
  ZONES.forEach((z) => {
    console.log(`- ${z.title}: ${z.stationIds.length} stations mapped`);
  });
  console.log("══════════════════════════════════════════");
}

export function LiveTwinCanvas({
  stations,
  buffers,
  vehicles,
  flowPredictions,
}: LiveTwinCanvasProps) {
  // Run integrity check in development
  if (process.env.NODE_ENV !== "production") {
    verifyTopologyIntegrity(stations, buffers, vehicles, flowPredictions);
  }

  const [filter, setFilter] = useState<"all" | "issues" | "unknown">("all");

  const bufferMap = new Map<string, Buffer>(buffers.map((b) => [b.id, b]));
  const vehicleMap = new Map<string, Vehicle>(vehicles.map((v) => [v.currentStationId, v]));
  const flowMap = new Map<string, FlowPrediction>(flowPredictions.map((fp) => [fp.stationId, fp]));

  // Filter application helper
  const isNodeDimmed = (station: Station) => {
    if (filter === "all") return false;

    const flowPred = flowMap.get(station.id);
    const hasFlowWarning = flowPred && flowPred.bottleneckRisk >= 0.50;
    const hasIssue = station.state === "DOWN" || station.state === "BLOCKED" || station.state === "STARVED" || hasFlowWarning;

    if (filter === "issues") {
      return !hasIssue;
    }

    if (filter === "unknown") {
      return station.sensorTrustState !== "UNKNOWN";
    }

    return false;
  };

  return (
    <div className="space-y-6 select-none w-full">
      {/* Filter controls */}
      <div className="flex items-center justify-between border-b pb-4 gap-4 flex-wrap w-full">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground uppercase tracking-wider font-mono">
            Filters:
          </span>
          <div className="flex rounded-md border p-0.5 bg-muted/10">
            <Button
              variant={filter === "all" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setFilter("all")}
              className="h-7 text-xs font-semibold"
            >
              All Cells
            </Button>
            <Button
              variant={filter === "issues" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setFilter("issues")}
              className="h-7 text-xs font-semibold"
            >
              Issues Only
            </Button>
            <Button
              variant={filter === "unknown" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setFilter("unknown")}
              className="h-7 text-xs font-semibold"
            >
              Sensor Gaps
            </Button>
          </div>
        </div>
        <span className="text-[10px] text-muted-foreground font-mono">
          * Click a station card cell to open full diagnostics readout page.
        </span>
      </div>

      {/* Topology List of Zones */}
      <div className="space-y-6 w-full">
        {ZONES.map((zone, zoneIdx) => {
          const zoneStations = zone.stationIds
            .map((id) => stations.find((s) => s.id === id))
            .filter((s): s is Station => !!s);

          return (
            <div
              key={zone.title}
              className="p-4 border rounded-md bg-card text-card-foreground shadow-sm space-y-4 w-full"
            >
              {/* Zone header */}
              <div className="flex items-center justify-between border-b pb-2">
                <h4 className="text-xs font-bold text-foreground uppercase tracking-wider font-mono">
                  {zone.title}
                </h4>
                {zoneIdx < ZONES.length - 1 && (
                  <span className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono uppercase">
                    Next zone <ArrowRight className="h-3 w-3" />
                  </span>
                )}
              </div>

              {/* Horizontal flow line of cells */}
              <div className="flex items-center gap-4 overflow-x-auto py-2 scrollbar-thin">
                {/* ZONE 9 CUSTOM BRANCH REPRESENTATION */}
                {zone.title.includes("Zone 9") ? (
                  <div className="flex items-center gap-4 shrink-0">
                    {/* B36 Upstream buffer */}
                    {bufferMap.has("B36") && (
                      <BufferNode buffer={bufferMap.get("B36")!} />
                    )}
                    
                    {/* Split arrow */}
                    <span className="text-muted-foreground text-xs font-mono">┌→</span>

                    {/* Parallel Branches Container */}
                    <div className="flex flex-col gap-3 border-l pl-3 py-1">
                      {/* Upper path: ICE (S37) */}
                      <div className="flex items-center gap-3">
                        <span className="text-[8px] font-mono text-muted-foreground uppercase border px-1 rounded bg-muted/30">
                          ICE Path
                        </span>
                        <StationNode
                          station={stations.find((s) => s.id === "S37")!}
                          vehicle={vehicleMap.get("S37") || null}
                          flowPrediction={flowMap.get("S37") || null}
                          isDimmed={isNodeDimmed(stations.find((s) => s.id === "S37")!)}
                        />
                      </div>
                      {/* Lower path: EV (Virtual Battery Coolant Fill) */}
                      <div className="flex items-center gap-3">
                        <span className="text-[8px] font-mono text-muted-foreground uppercase border px-1 rounded bg-muted/30">
                          EV Path
                        </span>
                        <StationNode
                          station={VIRTUAL_S37_EV}
                          vehicle={vehicleMap.get("S37-EV") || null}
                          flowPrediction={flowMap.get("S37-EV") || null}
                          isDimmed={filter !== "all"}
                        />
                      </div>
                    </div>

                    {/* Re-converge arrow */}
                    <span className="text-muted-foreground text-xs font-mono">└→</span>

                    {/* B37 Downstream Buffer */}
                    {bufferMap.has("B37") && (
                      <BufferNode buffer={bufferMap.get("B37")!} />
                    )}

                    {/* S38 Station */}
                    <StationNode
                      station={stations.find((s) => s.id === "S38")!}
                      vehicle={vehicleMap.get("S38") || null}
                      flowPrediction={flowMap.get("S38") || null}
                      isDimmed={isNodeDimmed(stations.find((s) => s.id === "S38")!)}
                    />

                    {/* B38 Downstream Buffer */}
                    {bufferMap.has("B38") && (
                      <BufferNode buffer={bufferMap.get("B38")!} />
                    )}

                    {/* S39 Station */}
                    <StationNode
                      station={stations.find((s) => s.id === "S39")!}
                      vehicle={vehicleMap.get("S39") || null}
                      flowPrediction={flowMap.get("S39") || null}
                      isDimmed={isNodeDimmed(stations.find((s) => s.id === "S39")!)}
                    />

                    {/* B39 Downstream Buffer */}
                    {bufferMap.has("B39") && (
                      <BufferNode buffer={bufferMap.get("B39")!} />
                    )}

                    {/* S40 Station */}
                    <StationNode
                      station={stations.find((s) => s.id === "S40")!}
                      vehicle={vehicleMap.get("S40") || null}
                      flowPrediction={flowMap.get("S40") || null}
                      isDimmed={isNodeDimmed(stations.find((s) => s.id === "S40")!)}
                    />
                  </div>
                ) : (
                  /* REGULAR LINEAR ZONE REPRESENTATION */
                  zoneStations.map((station, idx) => {
                    const nextBufferId = station.downstreamBufferId;
                    const nextBuffer = nextBufferId ? bufferMap.get(nextBufferId) : null;

                    return (
                      <div key={station.id} className="flex items-center gap-4 shrink-0">
                        {/* Station Cell Link */}
                        <StationNode
                          station={station}
                          vehicle={vehicleMap.get(station.id) || null}
                          flowPrediction={flowMap.get(station.id) || null}
                          isDimmed={isNodeDimmed(station)}
                        />

                        {/* Arrow connector and buffer node if downstream exists inside this zone */}
                        {nextBuffer && idx < zoneStations.length - 1 && (
                          <>
                            <span className="text-muted-foreground text-xs font-mono">→</span>
                            <BufferNode buffer={nextBuffer} />
                            <span className="text-muted-foreground text-xs font-mono">→</span>
                          </>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── FULL-WIDTH RESPONSIVE LEGEND ── */}
      <div className="w-full pt-4">
        <LiveTwinLegend />
      </div>
    </div>
  );
}
