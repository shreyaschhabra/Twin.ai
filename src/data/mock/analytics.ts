/**
 * MOCK DATA — Development only.
 * Plant Manager analytics snapshot.
 */

import type { ManagerAnalytics, ShiftAnalytics, MaintenanceCandidate, AnomalyPattern } from "@/types/analytics";

export const mockManagerAnalytics: ManagerAnalytics = {
  asOf: "2026-08-30T10:55:00Z",

  activeFlowWarnings: 2,
  activeQualityFlags: 3,
  sensorGapStations: 2,

  throughputTrend: [
    { stationId: "S01", stationName: "Body Side Inner Weld", vehiclesPerHour: 58,
      trend: [
        { timestamp: "2026-08-30T06:00:00Z", value: 60 },
        { timestamp: "2026-08-30T07:00:00Z", value: 59 },
        { timestamp: "2026-08-30T08:00:00Z", value: 60 },
        { timestamp: "2026-08-30T09:00:00Z", value: 58 },
        { timestamp: "2026-08-30T10:00:00Z", value: 58 },
      ],
    },
    { stationId: "S18", stationName: "Underbody Dimensional", vehiclesPerHour: 36,
      trend: [
        { timestamp: "2026-08-30T06:00:00Z", value: 42 },
        { timestamp: "2026-08-30T07:00:00Z", value: 42 },
        { timestamp: "2026-08-30T08:00:00Z", value: 41 },
        { timestamp: "2026-08-30T09:00:00Z", value: 39 },
        { timestamp: "2026-08-30T10:00:00Z", value: 36 },
      ],
    },
  ],

  bottleneckHotspots: [
    {
      stationId: "S18", stationName: "Underbody Dimensional",
      occurrences: 3, avgDurationMin: 14, estimatedThroughputLoss: 4,
    },
    {
      stationId: "S13", stationName: "Seat Install Robot",
      occurrences: 1, avgDurationMin: 22, estimatedThroughputLoss: 6,
    },
  ],

  defectHotspots: [
    {
      stationId: "S12", stationName: "Instrument Panel Robot",
      defectRate: 0.04, highRiskVehicleCount: 1,
    },
    {
      stationId: "S11", stationName: "Door Hinge Robot",
      defectRate: 0.02, highRiskVehicleCount: 0,
    },
  ],

  falseAlertTrend: [
    { period: "2026-08-30T06:00", falseAlerts: 1, totalAlerts: 4, falseAlertRate: 0.25 },
    { period: "2026-08-30T07:00", falseAlerts: 0, totalAlerts: 3, falseAlertRate: 0.00 },
    { period: "2026-08-30T08:00", falseAlerts: 1, totalAlerts: 5, falseAlertRate: 0.20 },
    { period: "2026-08-30T09:00", falseAlerts: 0, totalAlerts: 2, falseAlertRate: 0.00 },
    { period: "2026-08-30T10:00", falseAlerts: 0, totalAlerts: 7, falseAlertRate: 0.00 },
  ],

  sensorGaps: [
    {
      stationId: "S11", stationName: "Door Hinge Robot",
      gapPercent: 55, lastGapAt: "2026-08-30T10:52:00Z",
    },
    {
      stationId: "S12", stationName: "Instrument Panel Robot",
      gapPercent: 12, lastGapAt: "2026-08-30T10:42:00Z",
    },
  ],
};

export const mockShiftAnalytics: ShiftAnalytics[] = [
  { shiftId: "Shift 86", throughput: 442, bottleneckEvents: 3, defectRate: 0.041, falseAlerts: 1, medianWarningLeadTime: 7.2, unknownCoverage: 0.06 },
  { shiftId: "Shift 87", throughput: 440, bottleneckEvents: 2, defectRate: 0.045, falseAlerts: 0, medianWarningLeadTime: 7.5, unknownCoverage: 0.07 },
  { shiftId: "Shift 88", throughput: 446, bottleneckEvents: 4, defectRate: 0.038, falseAlerts: 2, medianWarningLeadTime: 6.9, unknownCoverage: 0.08 },
  { shiftId: "Shift 89", throughput: 445, bottleneckEvents: 1, defectRate: 0.039, falseAlerts: 0, medianWarningLeadTime: 7.1, unknownCoverage: 0.09 },
  { shiftId: "Shift 90", throughput: 448, bottleneckEvents: 2, defectRate: 0.042, falseAlerts: 1, medianWarningLeadTime: 7.3, unknownCoverage: 0.05 },
  { shiftId: "Shift 91", throughput: 450, bottleneckEvents: 1, defectRate: 0.035, falseAlerts: 0, medianWarningLeadTime: 7.6, unknownCoverage: 0.04 },
  { shiftId: "Shift 92", throughput: 443, bottleneckEvents: 2, defectRate: 0.048, falseAlerts: 1, medianWarningLeadTime: 7.0, unknownCoverage: 0.06 },
  { shiftId: "Shift 93", throughput: 439, bottleneckEvents: 3, defectRate: 0.052, falseAlerts: 2, medianWarningLeadTime: 6.4, unknownCoverage: 0.08 },
  { shiftId: "Shift 94", throughput: 447, bottleneckEvents: 2, defectRate: 0.040, falseAlerts: 1, medianWarningLeadTime: 7.1, unknownCoverage: 0.07 },
  { shiftId: "Shift 95", throughput: 451, bottleneckEvents: 1, defectRate: 0.036, falseAlerts: 0, medianWarningLeadTime: 7.4, unknownCoverage: 0.05 },
  { shiftId: "Shift 96", throughput: 452, bottleneckEvents: 2, defectRate: 0.038, falseAlerts: 1, medianWarningLeadTime: 7.2, unknownCoverage: 0.06 },
  { shiftId: "Shift 97", throughput: 449, bottleneckEvents: 0, defectRate: 0.031, falseAlerts: 0, medianWarningLeadTime: 8.0, unknownCoverage: 0.04 },
  { shiftId: "Shift 98", throughput: 446, bottleneckEvents: 2, defectRate: 0.038, falseAlerts: 1, medianWarningLeadTime: 7.4, unknownCoverage: 0.08 },
  { shiftId: "Shift 99", throughput: 453, bottleneckEvents: 1, defectRate: 0.034, falseAlerts: 0, medianWarningLeadTime: 7.7, unknownCoverage: 0.05 },
  { shiftId: "Shift 100", throughput: 456, bottleneckEvents: 1, defectRate: 0.032, falseAlerts: 0, medianWarningLeadTime: 7.9, unknownCoverage: 0.03 },
];

export const mockMaintenanceCandidates: MaintenanceCandidate[] = [
  {
    stationId: "S18",
    stationName: "Underbody Dimensional",
    reason: "Repeated Flow constraints, moderate quality risk exposure, elevated tool age.",
    flowEvents: 12,
    qualityExposure: 148,
    minorStops: 7,
    maintenanceAgePercent: 86,
  },
  {
    stationId: "S12",
    stationName: "Instrument Panel Robot",
    reason: "Recurring camera sensor dropouts creating unknown telemetry trust gaps.",
    flowEvents: 2,
    qualityExposure: 83,
    minorStops: 14,
    maintenanceAgePercent: 64,
  },
  {
    stationId: "S11",
    stationName: "Door Hinge Robot",
    reason: "Frequent process deviations and rising minor stops over the last 10 shifts.",
    flowEvents: 4,
    qualityExposure: 55,
    minorStops: 9,
    maintenanceAgePercent: 78,
  },
];

export const mockAnomalyPatterns: AnomalyPattern[] = [
  {
    stationId: "S12",
    stationName: "Instrument Panel Robot",
    anomalyType: "Camera alignmentcurrent drift",
    occurrences: 7,
    avgDurationMin: 9,
    vehiclesExposed: 83,
  },
  {
    stationId: "S31",
    stationName: "Rear Bumper Fastening",
    anomalyType: "Hydraulic pressure deviation",
    occurrences: 4,
    avgDurationMin: 14,
    vehiclesExposed: 38,
  },
];

