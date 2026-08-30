/**
 * MOCK DATA — Development only.
 *
 * Flow (bottleneck) prediction scenarios:
 * 1. S18  — developing bottleneck, HIGH confidence (87% risk, onset 6–8 min)
 * 2. S13  — current blockage (already blocked)
 * 3. S28  — benign vehicle-mix variation (ICE SUV cycle time increase, WATCH only)
 */

import type { FlowPrediction } from "@/types/flow";

export const mockFlowPredictions: FlowPrediction[] = [
  // ── SCENARIO 1: DEVELOPING BOTTLENECK AT S18 ─────────────────────────────
  {
    stationId: "S18",
    stationName: "Underbody Dimensional",
    bottleneckRisk: 0.87,
    expectedOnsetMin: 6,
    expectedOnsetMax: 8,
    confidence: "HIGH",
    status: "WARNING",
    evidence: [
      { label: "Buffer occupancy",       value: "6 / 7 (86%)",      direction: "negative" },
      { label: "Buffer growth rate",      value: "+1 unit / cycle",  direction: "negative" },
      { label: "Cycle-time trend",        value: "+16% vs baseline", direction: "negative" },
      { label: "Arrival rate",            value: "> departure rate", direction: "negative" },
      { label: "Upstream departure rate", value: "On baseline",      direction: "neutral"  },
    ],
    affectedUpstreamStations: ["S17", "S16", "S15"],
    affectedDownstreamStations: ["S19", "S20"],
  },

  // ── SCENARIO 2: ACTIVE BLOCKAGE AT S13 ───────────────────────────────────
  {
    stationId: "S13",
    stationName: "Seat Install Robot",
    bottleneckRisk: 0.99,
    expectedOnsetMin: 0,
    expectedOnsetMax: 0,
    confidence: "HIGH",
    status: "CRITICAL",
    evidence: [
      { label: "Station state",     value: "BLOCKED",               direction: "negative" },
      { label: "Buffer B12",        value: "4 / 5 (80%, filling)",  direction: "negative" },
      { label: "Downstream buffer", value: "2 / 6 (33%) — slack",   direction: "positive" },
    ],
    affectedUpstreamStations: ["S12", "S11", "S10"],
    affectedDownstreamStations: ["S14"],
  },

  // ── SCENARIO 3: BENIGN VEHICLE-MIX VARIATION AT S28 ─────────────────────
  // ICE SUV mix is high this shift. S28 cycle times are up 7%, but
  // buffer occupancy is stable and no onset risk exists.
  // Demonstrates false-alert suppression — this should NOT become a WARNING.
  {
    stationId: "S28",
    stationName: "Trim Line A",
    bottleneckRisk: 0.22,
    expectedOnsetMin: 25,
    expectedOnsetMax: 40,
    confidence: "HIGH",
    status: "WATCH",
    evidence: [
      { label: "Cycle-time trend",  value: "+7% vs baseline",       direction: "negative" },
      { label: "Vehicle mix",       value: "71% ICE SUV this shift", direction: "neutral"  },
      { label: "Buffer occupancy",  value: "3 / 5 (60%) — stable",  direction: "neutral"  },
      { label: "Growth rate",       value: "0 — not filling",        direction: "positive" },
    ],
    affectedUpstreamStations: [],
    affectedDownstreamStations: [],
  },

  // ── CLEAR STATIONS (sample) ───────────────────────────────────────────────
  {
    stationId: "S01",
    stationName: "Body Side Inner Weld",
    bottleneckRisk: 0.04,
    expectedOnsetMin: 60,
    expectedOnsetMax: 90,
    confidence: "HIGH",
    status: "CLEAR",
    evidence: [
      { label: "Buffer occupancy", value: "2 / 4 (50%)", direction: "neutral" },
      { label: "Cycle time",       value: "On baseline",  direction: "positive" },
    ],
    affectedUpstreamStations: [],
    affectedDownstreamStations: [],
  },
];

export const flowPredictionByStation = new Map<string, FlowPrediction>(
  mockFlowPredictions.map((fp) => [fp.stationId, fp]),
);
