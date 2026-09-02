/**
 * Buffer (inter-station WIP store) domain type.
 *
 * Buffers hold work-in-progress vehicles between stations.
 * Their occupancy ratio is a leading indicator for bottleneck prediction.
 */
export type BufferStatus = "NORMAL" | "FILLING" | "CRITICAL" | "EMPTY";

export type Buffer = {
  id: string;

  /** Station immediately upstream (feeding into this buffer). */
  upstreamStationId: string;

  /** Station immediately downstream (consuming from this buffer). */
  downstreamStationId: string;

  /** Maximum number of vehicles this buffer can hold. */
  capacity: number;

  /** Current number of vehicles in the buffer. */
  currentWip: number;

  /**
   * currentWip / capacity, pre-computed for display.
   * Range: 0.0 – 1.0.
   */
  occupancyRatio: number;

  /** WIP count at the previous observation interval. */
  previousWip?: number;

  /**
   * Rate of change in WIP between observations.
   * Positive = filling, negative = draining.
   */
  growthRate?: number;

  status: BufferStatus;
};
