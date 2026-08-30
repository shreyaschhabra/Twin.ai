import type {
  ConfidenceLevel,
  SensorMaturity,
  SensorTrustState,
} from "./common";

/**
 * Operational runtime state of a manufacturing station.
 *
 * IDLE       — station is between jobs, waiting for a vehicle.
 * PROCESSING — station is actively working on a vehicle.
 * BLOCKED    — station has finished but cannot release; downstream is full.
 * STARVED    — station is waiting; upstream cannot supply a vehicle.
 * DOWN       — station is offline due to fault, maintenance, or changeover.
 */
export type StationState =
  | "IDLE"
  | "PROCESSING"
  | "BLOCKED"
  | "STARVED"
  | "DOWN";

/**
 * Station process family / type label.
 * Used for grouping and display; does not constrain per-station operations.
 */
export type StationType =
  | "Welding / Body Joining"
  | "Adhesive / Sealing"
  | "Robotic Handling / Assembly"
  | "Dimensional Inspection"
  | "Paint / Coating"
  | "Curing / Environmental Process"
  | "Manual Assembly"
  | "Torque / Fastening"
  | "Fluid Fill / Functional Process"
  | "Inspection / End-of-Line Testing";

/**
 * Core frontend contract for a manufacturing station.
 *
 * id                — unique station identifier, e.g. "S18".
 * name              — human-readable label.
 * type              — process family grouping.
 * operation         — specific operation performed at this station.
 *
 * state             — current runtime operational state.
 * baselineCycleTime — nominal cycle time in seconds.
 * currentCycleTime  — observed cycle time in seconds (may differ from baseline).
 *
 * currentVehicleId  — vehicle currently at this station, if any.
 * upstreamBufferId  — buffer feeding this station, if any.
 * downstreamBufferId— buffer this station feeds into, if any.
 *
 * sensorMaturity    — quality of this station's sensor instrumentation.
 * sensorTrustState  — current live trust state of sensor data.
 *
 * confidence        — prediction confidence level for this station's metrics.
 */
export type Station = {
  id: string;
  name: string;
  type: StationType;
  operation: string;

  state: StationState;
  baselineCycleTime: number;
  currentCycleTime: number;

  currentVehicleId?: string;
  upstreamBufferId?: string;
  downstreamBufferId?: string;

  sensorMaturity: SensorMaturity;
  sensorTrustState: SensorTrustState;

  confidence: ConfidenceLevel;
};

export type StationSensor = {
  id: string;
  name: string;
  value?: number;
  unit?: string;
  trustState: SensorTrustState;
  status?: "NORMAL" | "DEVIATING" | "UNAVAILABLE";
};

export type StationMaintenance = {
  hoursSinceMaintenance: number;
  toolAgePercent: number;
  recentMinorStopsCount: number;
  needsAttention: boolean;
};

export type StationProcessTrend = {
  cycleTimeHistory: number[];
};

