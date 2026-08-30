/**
 * MOCK DATA — Development only.
 * Alert feed representing active alerts across flow, quality, sensor and anomaly kinds.
 */

import type { Alert } from "@/types/alert";

export const mockAlerts: Alert[] = [
  // ── FLOW: S18 DEVELOPING BOTTLENECK ──────────────────────────────────────
  {
    id: "ALT-F-001",
    kind: "FLOW",
    severity: "WARNING",
    title: "Bottleneck forming — S18 Underbody Dimensional",
    description: "Buffer B17 at 86% capacity and filling. Cycle time +16% vs baseline. Predicted onset in 6–8 minutes.",
    timestamp: "2026-08-30T10:45:00Z",
    stationId: "S18",
    risk: 0.87,
    confidence: "HIGH",
    evidence: [
      { label: "Buffer occupancy", value: "6 / 7 (86%)",      direction: "negative" },
      { label: "Cycle-time trend", value: "+16% vs baseline",  direction: "negative" },
    ],
    acknowledged: false,
  },

  // ── FLOW: S13 ACTIVE BLOCKAGE ─────────────────────────────────────────────
  {
    id: "ALT-F-002",
    kind: "FLOW",
    severity: "CRITICAL",
    title: "Station BLOCKED — S13 Seat Install Robot",
    description: "S13 is blocked. Downstream is full. Upstream buffer B12 filling (4/5).",
    timestamp: "2026-08-30T10:38:00Z",
    stationId: "S13",
    risk: 0.99,
    confidence: "HIGH",
    evidence: [
      { label: "Station state", value: "BLOCKED",               direction: "negative" },
      { label: "Buffer B12",    value: "4 / 5 (80%, filling)",  direction: "negative" },
    ],
    acknowledged: false,
  },

  // ── QUALITY: V2048 HIGH RISK ─────────────────────────────────────────────
  {
    id: "ALT-Q-001",
    kind: "QUALITY",
    severity: "CRITICAL",
    title: "High defect risk — V2048 (EV)",
    description: "Quality risk spiked to 79% following anomaly exposure at S12. Recommend inspection hold before S16.",
    timestamp: "2026-08-30T10:42:00Z",
    vehicleId: "V2048",
    stationId: "S12",
    risk: 0.79,
    confidence: "HIGH",
    evidence: [
      { label: "Anomaly exposure", value: "S12 — camera dropout",  direction: "negative" },
      { label: "Risk jump",        value: "+58 pp at S12",         direction: "negative" },
    ],
    acknowledged: false,
  },

  // ── SENSOR: S12 CAMERA DROPOUT ───────────────────────────────────────────
  {
    id: "ALT-S-001",
    kind: "SENSOR",
    severity: "WARNING",
    title: "Sensor dropout — S12 vision system",
    description: "Camera system at S12 (Instrument Panel Robot) lost signal 10:31–10:42. Trust state: INFERRED. Affected vehicles: V2048–V2052.",
    timestamp: "2026-08-30T10:31:00Z",
    stationId: "S12",
    confidence: "MEDIUM",
    evidence: [
      { label: "Sensor trust state", value: "INFERRED → UNKNOWN",          direction: "negative" },
      { label: "Affected window",    value: "10:31–10:42 (11 min)",         direction: "negative" },
      { label: "Affected vehicles",  value: "5 (V2048, V2049, V2050, V2051, V2052)", direction: "negative" },
    ],
    acknowledged: true,
  },

  // ── ANOMALY: S12 ─────────────────────────────────────────────────────────
  {
    id: "ALT-A-001",
    kind: "ANOMALY",
    severity: "WARNING",
    title: "Anomaly detected — S12 cycle-time spike",
    description: "S12 cycle time exceeded 3-sigma threshold for 11 consecutive cycles. Root cause: camera alignment fault.",
    timestamp: "2026-08-30T10:31:00Z",
    stationId: "S12",
    risk: 0.82,
    confidence: "HIGH",
    evidence: [
      { label: "Anomaly type", value: "Cycle-time 3-sigma exceedance", direction: "negative" },
      { label: "Duration",     value: "11 consecutive cycles",          direction: "negative" },
    ],
    acknowledged: true,
  },

  // ── SENSOR: S11 DROPOUT (IN PROGRESS) ────────────────────────────────────
  {
    id: "ALT-S-002",
    kind: "SENSOR",
    severity: "WATCH",
    title: "Sensor degrading — S11 Door Hinge Robot",
    description: "S11 sensor trust transitioning LIVE → INFERRED. Coverage declining. Monitor for further degradation.",
    timestamp: "2026-08-30T10:50:00Z",
    stationId: "S11",
    confidence: "MEDIUM",
    evidence: [
      { label: "Trust state", value: "INFERRED (was LIVE)",  direction: "negative" },
      { label: "Live coverage", value: "45% (was 95%)",      direction: "negative" },
    ],
    acknowledged: false,
  },

  // ── FLOW: S28 BENIGN MIX VARIATION (INFO) ────────────────────────────────
  {
    id: "ALT-F-003",
    kind: "FLOW",
    severity: "INFO",
    title: "Cycle-time increase — S28 (vehicle mix, not a bottleneck)",
    description: "S28 cycle time +7% due to ICE SUV mix (71%). Buffer occupancy stable. No bottleneck risk.",
    timestamp: "2026-08-30T10:40:00Z",
    stationId: "S28",
    risk: 0.22,
    confidence: "HIGH",
    evidence: [
      { label: "Vehicle mix",      value: "71% ICE SUV",              direction: "neutral"  },
      { label: "Cycle-time trend", value: "+7% vs baseline",          direction: "negative" },
      { label: "Buffer occupancy", value: "3 / 5 (60%) — not growing", direction: "positive" },
    ],
    acknowledged: false,
  },
];

export const alertById = new Map<string, Alert>(
  mockAlerts.map((a) => [a.id, a]),
);
