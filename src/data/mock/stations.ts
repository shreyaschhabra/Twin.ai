/**
 * MOCK DATA — Development only.
 *
 * 45 manufacturing stations for Twin AI development and demonstration.
 * DO NOT use in production. Replace via getStations() service function.
 *
 * Sensor maturity distribution (required):
 *   RICH    → 29 stations
 *   PARTIAL → 10 stations
 *   POOR    →  6 stations
 *   Total   → 45 stations
 *
 * Station type and operation are always separate fields.
 * Stations of the same type may perform different operations.
 */

import type { Station } from "@/types/station";

// ─── MOCK STATIONS ────────────────────────────────────────────────────────────
// prettier-ignore
export const mockStations: Station[] = [
  // ── WELDING / BODY JOINING ─────────────────────────────────── S01–S06 ──
  {
    id: "S01", name: "Body Side Inner Weld", type: "Welding / Body Joining",
    operation: "Body side inner panel spot welding",
    state: "PROCESSING", baselineCycleTime: 62, currentCycleTime: 63,
    currentVehicleId: "V2043", upstreamBufferId: "B00", downstreamBufferId: "B01",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S02", name: "Floor Pan Weld", type: "Welding / Body Joining",
    operation: "Floor pan to sill seam weld",
    state: "PROCESSING", baselineCycleTime: 58, currentCycleTime: 58,
    currentVehicleId: "V2044", upstreamBufferId: "B01", downstreamBufferId: "B02",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S03", name: "Roof Panel Weld", type: "Welding / Body Joining",
    operation: "Roof panel laser weld to body sides",
    state: "PROCESSING", baselineCycleTime: 70, currentCycleTime: 72,
    currentVehicleId: "V2045", upstreamBufferId: "B02", downstreamBufferId: "B03",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S04", name: "A-Pillar Weld", type: "Welding / Body Joining",
    operation: "A-pillar reinforcement weld",
    state: "PROCESSING", baselineCycleTime: 55, currentCycleTime: 56,
    currentVehicleId: "V2046", upstreamBufferId: "B03", downstreamBufferId: "B04",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S05", name: "Rear Quarter Weld", type: "Welding / Body Joining",
    operation: "Rear quarter panel MIG weld",
    state: "IDLE", baselineCycleTime: 65, currentCycleTime: 65,
    upstreamBufferId: "B04", downstreamBufferId: "B05",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S06", name: "Door Aperture Weld", type: "Welding / Body Joining",
    operation: "Door aperture stiffener projection weld",
    state: "PROCESSING", baselineCycleTime: 60, currentCycleTime: 61,
    currentVehicleId: "V2047", upstreamBufferId: "B05", downstreamBufferId: "B06",
    sensorMaturity: "PARTIAL", sensorTrustState: "INFERRED", confidence: "MEDIUM",
  },

  // ── ADHESIVE / SEALING ────────────────────────────────────── S07–S10 ──
  {
    id: "S07", name: "Structural Adhesive Apply", type: "Adhesive / Sealing",
    operation: "Structural adhesive bead application on roof rail",
    state: "PROCESSING", baselineCycleTime: 48, currentCycleTime: 49,
    currentVehicleId: "V2048", upstreamBufferId: "B06", downstreamBufferId: "B07",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S08", name: "Hem Flange Seal", type: "Adhesive / Sealing",
    operation: "Hem flange mastic sealing on door panels",
    state: "PROCESSING", baselineCycleTime: 52, currentCycleTime: 54,
    currentVehicleId: "V2049", upstreamBufferId: "B07", downstreamBufferId: "B08",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "MEDIUM",
  },
  {
    id: "S09", name: "Underbody Sealer", type: "Adhesive / Sealing",
    operation: "Underbody anti-corrosion sealer application",
    state: "PROCESSING", baselineCycleTime: 75, currentCycleTime: 75,
    currentVehicleId: "V2050", upstreamBufferId: "B08", downstreamBufferId: "B09",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S10", name: "Windshield Urethane Apply", type: "Adhesive / Sealing",
    operation: "Windshield urethane bead application",
    state: "IDLE", baselineCycleTime: 44, currentCycleTime: 44,
    upstreamBufferId: "B09", downstreamBufferId: "B10",
    sensorMaturity: "POOR", sensorTrustState: "UNKNOWN", confidence: "LOW",
  },

  // ── ROBOTIC HANDLING / ASSEMBLY ───────────────────────────── S11–S15 ──
  {
    id: "S11", name: "Door Hinge Robot", type: "Robotic Handling / Assembly",
    operation: "Automated door hinge fastening",
    state: "PROCESSING", baselineCycleTime: 50, currentCycleTime: 51,
    currentVehicleId: "V2051", upstreamBufferId: "B10", downstreamBufferId: "B11",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S12", name: "Instrument Panel Robot", type: "Robotic Handling / Assembly",
    operation: "Instrument panel robotic installation",
    state: "PROCESSING", baselineCycleTime: 90, currentCycleTime: 104,
    currentVehicleId: "V2052", upstreamBufferId: "B11", downstreamBufferId: "B12",
    sensorMaturity: "RICH", sensorTrustState: "INFERRED", confidence: "MEDIUM",
  },
  {
    id: "S13", name: "Seat Install Robot", type: "Robotic Handling / Assembly",
    operation: "Front and rear seat robotic drop-in",
    state: "BLOCKED", baselineCycleTime: 68, currentCycleTime: 68,
    currentVehicleId: "V2053", upstreamBufferId: "B12", downstreamBufferId: "B13",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S14", name: "Engine Dress Robot", type: "Robotic Handling / Assembly",
    operation: "Engine ancillary component robotic assembly",
    state: "PROCESSING", baselineCycleTime: 110, currentCycleTime: 112,
    currentVehicleId: "V2054", upstreamBufferId: "B13", downstreamBufferId: "B14",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S15", name: "Body Transfer Robot", type: "Robotic Handling / Assembly",
    operation: "Body-in-white transfer between assembly zones",
    state: "PROCESSING", baselineCycleTime: 30, currentCycleTime: 30,
    currentVehicleId: "V2055", upstreamBufferId: "B14", downstreamBufferId: "B15",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },

  // ── DIMENSIONAL INSPECTION ────────────────────────────────── S16–S18 ──
  {
    id: "S16", name: "CMM Body Geometry", type: "Dimensional Inspection",
    operation: "Coordinate measuring machine body geometry check",
    state: "PROCESSING", baselineCycleTime: 95, currentCycleTime: 96,
    currentVehicleId: "V2043", upstreamBufferId: "B15", downstreamBufferId: "B16",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S17", name: "Door Gap / Flush Check", type: "Dimensional Inspection",
    operation: "Automated door gap and flush measurement",
    state: "PROCESSING", baselineCycleTime: 80, currentCycleTime: 83,
    currentVehicleId: "V2044", upstreamBufferId: "B16", downstreamBufferId: "B17",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    // BOTTLENECK SCENARIO STATION
    id: "S18", name: "Underbody Dimensional", type: "Dimensional Inspection",
    operation: "Underbody fixture dimensional verification",
    state: "PROCESSING", baselineCycleTime: 85, currentCycleTime: 99,
    currentVehicleId: "V2045", upstreamBufferId: "B17", downstreamBufferId: "B18",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },

  // ── PAINT / COATING ───────────────────────────────────────── S19–S23 ──
  {
    id: "S19", name: "E-Coat Dip", type: "Paint / Coating",
    operation: "Electrocoat anti-corrosion dip",
    state: "PROCESSING", baselineCycleTime: 120, currentCycleTime: 120,
    currentVehicleId: "V2046", upstreamBufferId: "B18", downstreamBufferId: "B19",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S20", name: "Primer Spray", type: "Paint / Coating",
    operation: "Primer coat spray application",
    state: "PROCESSING", baselineCycleTime: 90, currentCycleTime: 92,
    currentVehicleId: "V2047", upstreamBufferId: "B19", downstreamBufferId: "B20",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S21", name: "Base Coat Spray", type: "Paint / Coating",
    operation: "Base coat electrostatic spray application",
    state: "PROCESSING", baselineCycleTime: 95, currentCycleTime: 96,
    currentVehicleId: "V2048", upstreamBufferId: "B20", downstreamBufferId: "B21",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "MEDIUM",
  },
  {
    id: "S22", name: "Clear Coat Spray", type: "Paint / Coating",
    operation: "Clear coat final layer application",
    state: "PROCESSING", baselineCycleTime: 85, currentCycleTime: 86,
    currentVehicleId: "V2049", upstreamBufferId: "B21", downstreamBufferId: "B22",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S23", name: "Paint Inspection Booth", type: "Paint / Coating",
    operation: "Post-paint visual and gloss inspection",
    state: "PROCESSING", baselineCycleTime: 70, currentCycleTime: 72,
    currentVehicleId: "V2050", upstreamBufferId: "B22", downstreamBufferId: "B23",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "MEDIUM",
  },

  // ── CURING / ENVIRONMENTAL PROCESS ───────────────────────── S24–S27 ──
  {
    id: "S24", name: "E-Coat Oven", type: "Curing / Environmental Process",
    operation: "Electrocoat bake oven cycle",
    state: "PROCESSING", baselineCycleTime: 180, currentCycleTime: 180,
    currentVehicleId: "V2051", upstreamBufferId: "B23", downstreamBufferId: "B24",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S25", name: "Primer Oven", type: "Curing / Environmental Process",
    operation: "Primer coat oven cure",
    state: "PROCESSING", baselineCycleTime: 150, currentCycleTime: 150,
    currentVehicleId: "V2052", upstreamBufferId: "B24", downstreamBufferId: "B25",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S26", name: "Top Coat Oven", type: "Curing / Environmental Process",
    operation: "Base and clear coat combined bake",
    state: "PROCESSING", baselineCycleTime: 160, currentCycleTime: 161,
    currentVehicleId: "V2053", upstreamBufferId: "B25", downstreamBufferId: "B26",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S27", name: "Adhesive Cure", type: "Curing / Environmental Process",
    operation: "Structural adhesive ambient cure hold",
    state: "PROCESSING", baselineCycleTime: 200, currentCycleTime: 200,
    currentVehicleId: "V2054", upstreamBufferId: "B26", downstreamBufferId: "B27",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "MEDIUM",
  },

  // ── MANUAL ASSEMBLY ───────────────────────────────────────── S28–S32 ──
  {
    id: "S28", name: "Trim Line A", type: "Manual Assembly",
    operation: "Interior trim panel manual installation",
    state: "PROCESSING", baselineCycleTime: 105, currentCycleTime: 112,
    currentVehicleId: "V2055", upstreamBufferId: "B27", downstreamBufferId: "B28",
    sensorMaturity: "POOR", sensorTrustState: "LIVE", confidence: "MEDIUM",
  },
  {
    id: "S29", name: "Trim Line B", type: "Manual Assembly",
    operation: "Headliner, sun visor and grab handle installation",
    state: "PROCESSING", baselineCycleTime: 98, currentCycleTime: 101,
    currentVehicleId: "V2043", upstreamBufferId: "B28", downstreamBufferId: "B29",
    sensorMaturity: "POOR", sensorTrustState: "UNKNOWN", confidence: "LOW",
  },
  {
    id: "S30", name: "Electrical Harness Install", type: "Manual Assembly",
    operation: "Main wiring harness routing and connector seating",
    state: "PROCESSING", baselineCycleTime: 115, currentCycleTime: 118,
    currentVehicleId: "V2044", upstreamBufferId: "B29", downstreamBufferId: "B30",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "MEDIUM",
  },
  {
    id: "S31", name: "Glass Install Manual", type: "Manual Assembly",
    operation: "Rear and quarter glass manual installation",
    state: "PROCESSING", baselineCycleTime: 88, currentCycleTime: 90,
    currentVehicleId: "V2045", upstreamBufferId: "B30", downstreamBufferId: "B31",
    sensorMaturity: "POOR", sensorTrustState: "UNKNOWN", confidence: "LOW",
  },
  {
    id: "S32", name: "Pedal / Control Install", type: "Manual Assembly",
    operation: "Pedal box, steering column and HVAC control assembly",
    state: "IDLE", baselineCycleTime: 92, currentCycleTime: 92,
    upstreamBufferId: "B31", downstreamBufferId: "B32",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "MEDIUM",
  },

  // ── TORQUE / FASTENING ────────────────────────────────────── S33–S36 ──
  {
    id: "S33", name: "Subframe Torque", type: "Torque / Fastening",
    operation: "Front subframe to body torque-to-yield fastening",
    state: "PROCESSING", baselineCycleTime: 72, currentCycleTime: 73,
    currentVehicleId: "V2046", upstreamBufferId: "B32", downstreamBufferId: "B33",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S34", name: "Suspension Torque", type: "Torque / Fastening",
    operation: "Front strut top mount and lower arm torque",
    state: "PROCESSING", baselineCycleTime: 80, currentCycleTime: 81,
    currentVehicleId: "V2047", upstreamBufferId: "B33", downstreamBufferId: "B34",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S35", name: "Wheel Bolt Torque", type: "Torque / Fastening",
    operation: "Wheel bolt tightening (4-gun simultaneous)",
    state: "PROCESSING", baselineCycleTime: 45, currentCycleTime: 46,
    currentVehicleId: "V2048", upstreamBufferId: "B34", downstreamBufferId: "B35",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S36", name: "Engine Mount Torque", type: "Torque / Fastening",
    operation: "Engine and transmission mount angle torque",
    state: "PROCESSING", baselineCycleTime: 78, currentCycleTime: 79,
    currentVehicleId: "V2049", upstreamBufferId: "B35", downstreamBufferId: "B36",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },

  // ── FLUID FILL / FUNCTIONAL PROCESS ─────────────────────── S37–S40 ──
  {
    id: "S37", name: "Engine Oil Fill", type: "Fluid Fill / Functional Process",
    operation: "Engine oil fill to specification",
    state: "PROCESSING", baselineCycleTime: 40, currentCycleTime: 40,
    currentVehicleId: "V2050", upstreamBufferId: "B36", downstreamBufferId: "B37",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S38", name: "Coolant Fill / Bleed", type: "Fluid Fill / Functional Process",
    operation: "Coolant fill and vacuum bleed cycle",
    state: "PROCESSING", baselineCycleTime: 55, currentCycleTime: 56,
    currentVehicleId: "V2051", upstreamBufferId: "B37", downstreamBufferId: "B38",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S39", name: "Brake Fluid Fill", type: "Fluid Fill / Functional Process",
    operation: "Brake fluid fill and ABS bleed",
    state: "PROCESSING", baselineCycleTime: 48, currentCycleTime: 49,
    currentVehicleId: "V2052", upstreamBufferId: "B38", downstreamBufferId: "B39",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S40", name: "Refrigerant Charge", type: "Fluid Fill / Functional Process",
    operation: "A/C refrigerant charge and leak test",
    state: "IDLE", baselineCycleTime: 62, currentCycleTime: 62,
    upstreamBufferId: "B39", downstreamBufferId: "B40",
    sensorMaturity: "POOR", sensorTrustState: "UNKNOWN", confidence: "LOW",
  },

  // ── INSPECTION / END-OF-LINE TESTING ─────────────────────── S41–S45 ──
  {
    id: "S41", name: "Headlamp Aim", type: "Inspection / End-of-Line Testing",
    operation: "Headlamp aim and beam pattern verification",
    state: "PROCESSING", baselineCycleTime: 38, currentCycleTime: 38,
    currentVehicleId: "V2053", upstreamBufferId: "B40", downstreamBufferId: "B41",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S42", name: "Rolling Road Test", type: "Inspection / End-of-Line Testing",
    operation: "Chassis dynamometer drive cycle and calibration",
    state: "PROCESSING", baselineCycleTime: 180, currentCycleTime: 182,
    currentVehicleId: "V2054", upstreamBufferId: "B41", downstreamBufferId: "B42",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S43", name: "Water Test", type: "Inspection / End-of-Line Testing",
    operation: "Water ingress flood test",
    state: "PROCESSING", baselineCycleTime: 90, currentCycleTime: 91,
    currentVehicleId: "V2055", upstreamBufferId: "B42", downstreamBufferId: "B43",
    sensorMaturity: "PARTIAL", sensorTrustState: "LIVE", confidence: "HIGH",
  },
  {
    id: "S44", name: "Final Visual Inspection", type: "Inspection / End-of-Line Testing",
    operation: "Full-vehicle visual quality final sign-off",
    state: "PROCESSING", baselineCycleTime: 75, currentCycleTime: 77,
    currentVehicleId: "V2043", upstreamBufferId: "B43", downstreamBufferId: "B44",
    sensorMaturity: "POOR", sensorTrustState: "INFERRED", confidence: "LOW",
  },
  {
    id: "S45", name: "Software Flash / OBD", type: "Inspection / End-of-Line Testing",
    operation: "ECU software flash and OBD-II diagnostic readout",
    state: "PROCESSING", baselineCycleTime: 65, currentCycleTime: 65,
    currentVehicleId: "V2044", upstreamBufferId: "B44",
    sensorMaturity: "RICH", sensorTrustState: "LIVE", confidence: "HIGH",
  },
];

// ─── LOOKUP HELPERS ───────────────────────────────────────────────────────────

/** O(1) station lookup by id. */
export const stationById = new Map<string, Station>(
  mockStations.map((s) => [s.id, s]),
);
