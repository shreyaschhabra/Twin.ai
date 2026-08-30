/**
 * MOCK DATA — Development only.
 * 44 inter-station buffers connecting S01→S45.
 * Buffer IDs: B01–B44 (B00 is the upstream supply — virtual, not tracked).
 */

import type { Buffer } from "@/types/buffer";

export const mockBuffers: Buffer[] = [
  { id: "B01", upstreamStationId: "S01", downstreamStationId: "S02", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B02", upstreamStationId: "S02", downstreamStationId: "S03", capacity: 4, currentWip: 1, occupancyRatio: 0.25, previousWip: 1, growthRate: 0, status: "NORMAL" },
  { id: "B03", upstreamStationId: "S03", downstreamStationId: "S04", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B04", upstreamStationId: "S04", downstreamStationId: "S05", capacity: 3, currentWip: 1, occupancyRatio: 0.33, previousWip: 1, growthRate: 0, status: "NORMAL" },
  { id: "B05", upstreamStationId: "S05", downstreamStationId: "S06", capacity: 4, currentWip: 0, occupancyRatio: 0.00, previousWip: 0, growthRate: 0, status: "EMPTY" },
  { id: "B06", upstreamStationId: "S06", downstreamStationId: "S07", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B07", upstreamStationId: "S07", downstreamStationId: "S08", capacity: 5, currentWip: 3, occupancyRatio: 0.60, previousWip: 2, growthRate: 1, status: "NORMAL" },
  { id: "B08", upstreamStationId: "S08", downstreamStationId: "S09", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B09", upstreamStationId: "S09", downstreamStationId: "S10", capacity: 4, currentWip: 1, occupancyRatio: 0.25, previousWip: 1, growthRate: 0, status: "NORMAL" },
  { id: "B10", upstreamStationId: "S10", downstreamStationId: "S11", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B11", upstreamStationId: "S11", downstreamStationId: "S12", capacity: 5, currentWip: 3, occupancyRatio: 0.60, previousWip: 2, growthRate: 1, status: "NORMAL" },
  // B12 — upstream of S13 which is BLOCKED. Buffer is filling.
  { id: "B12", upstreamStationId: "S12", downstreamStationId: "S13", capacity: 5, currentWip: 4, occupancyRatio: 0.80, previousWip: 3, growthRate: 1, status: "FILLING" },
  { id: "B13", upstreamStationId: "S13", downstreamStationId: "S14", capacity: 6, currentWip: 2, occupancyRatio: 0.33, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B14", upstreamStationId: "S14", downstreamStationId: "S15", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B15", upstreamStationId: "S15", downstreamStationId: "S16", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B16", upstreamStationId: "S16", downstreamStationId: "S17", capacity: 5, currentWip: 3, occupancyRatio: 0.60, previousWip: 3, growthRate: 0, status: "NORMAL" },
  // B17 — upstream of S18 (BOTTLENECK SCENARIO). Buffer filling critically.
  { id: "B17", upstreamStationId: "S17", downstreamStationId: "S18", capacity: 7, currentWip: 6, occupancyRatio: 0.86, previousWip: 5, growthRate: 1, status: "FILLING" },
  { id: "B18", upstreamStationId: "S18", downstreamStationId: "S19", capacity: 6, currentWip: 1, occupancyRatio: 0.17, previousWip: 2, growthRate: -1, status: "NORMAL" },
  { id: "B19", upstreamStationId: "S19", downstreamStationId: "S20", capacity: 8, currentWip: 3, occupancyRatio: 0.38, previousWip: 3, growthRate: 0, status: "NORMAL" },
  { id: "B20", upstreamStationId: "S20", downstreamStationId: "S21", capacity: 8, currentWip: 4, occupancyRatio: 0.50, previousWip: 4, growthRate: 0, status: "NORMAL" },
  { id: "B21", upstreamStationId: "S21", downstreamStationId: "S22", capacity: 8, currentWip: 3, occupancyRatio: 0.38, previousWip: 3, growthRate: 0, status: "NORMAL" },
  { id: "B22", upstreamStationId: "S22", downstreamStationId: "S23", capacity: 6, currentWip: 2, occupancyRatio: 0.33, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B23", upstreamStationId: "S23", downstreamStationId: "S24", capacity: 6, currentWip: 3, occupancyRatio: 0.50, previousWip: 3, growthRate: 0, status: "NORMAL" },
  { id: "B24", upstreamStationId: "S24", downstreamStationId: "S25", capacity: 6, currentWip: 4, occupancyRatio: 0.67, previousWip: 4, growthRate: 0, status: "NORMAL" },
  { id: "B25", upstreamStationId: "S25", downstreamStationId: "S26", capacity: 6, currentWip: 3, occupancyRatio: 0.50, previousWip: 3, growthRate: 0, status: "NORMAL" },
  { id: "B26", upstreamStationId: "S26", downstreamStationId: "S27", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B27", upstreamStationId: "S27", downstreamStationId: "S28", capacity: 5, currentWip: 3, occupancyRatio: 0.60, previousWip: 3, growthRate: 0, status: "NORMAL" },
  { id: "B28", upstreamStationId: "S28", downstreamStationId: "S29", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B29", upstreamStationId: "S29", downstreamStationId: "S30", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B30", upstreamStationId: "S30", downstreamStationId: "S31", capacity: 5, currentWip: 3, occupancyRatio: 0.60, previousWip: 3, growthRate: 0, status: "NORMAL" },
  { id: "B31", upstreamStationId: "S31", downstreamStationId: "S32", capacity: 5, currentWip: 1, occupancyRatio: 0.20, previousWip: 1, growthRate: 0, status: "NORMAL" },
  { id: "B32", upstreamStationId: "S32", downstreamStationId: "S33", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B33", upstreamStationId: "S33", downstreamStationId: "S34", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B34", upstreamStationId: "S34", downstreamStationId: "S35", capacity: 4, currentWip: 1, occupancyRatio: 0.25, previousWip: 1, growthRate: 0, status: "NORMAL" },
  { id: "B35", upstreamStationId: "S35", downstreamStationId: "S36", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B36", upstreamStationId: "S36", downstreamStationId: "S37", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B37", upstreamStationId: "S37", downstreamStationId: "S38", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B38", upstreamStationId: "S38", downstreamStationId: "S39", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B39", upstreamStationId: "S39", downstreamStationId: "S40", capacity: 4, currentWip: 1, occupancyRatio: 0.25, previousWip: 1, growthRate: 0, status: "NORMAL" },
  { id: "B40", upstreamStationId: "S40", downstreamStationId: "S41", capacity: 5, currentWip: 2, occupancyRatio: 0.40, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B41", upstreamStationId: "S41", downstreamStationId: "S42", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B42", upstreamStationId: "S42", downstreamStationId: "S43", capacity: 4, currentWip: 1, occupancyRatio: 0.25, previousWip: 1, growthRate: 0, status: "NORMAL" },
  { id: "B43", upstreamStationId: "S43", downstreamStationId: "S44", capacity: 4, currentWip: 2, occupancyRatio: 0.50, previousWip: 2, growthRate: 0, status: "NORMAL" },
  { id: "B44", upstreamStationId: "S44", downstreamStationId: "S45", capacity: 4, currentWip: 1, occupancyRatio: 0.25, previousWip: 1, growthRate: 0, status: "NORMAL" },
];

export const bufferById = new Map<string, Buffer>(
  mockBuffers.map((b) => [b.id, b]),
);
