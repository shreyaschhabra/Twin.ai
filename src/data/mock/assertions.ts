/**
 * DEVELOPMENT DATA QUALITY ASSERTIONS
 *
 * Validates the mock dataset invariants at module load time (development only).
 * These assertions will throw if the mock data violates its own contracts.
 *
 * Run at build time via the service layer or a dedicated test.
 * Not included in production bundles when useMockData is false.
 */

import { mockStations } from "./stations";
import type { ConfidenceLevel, SensorMaturity, SensorTrustState } from "@/types/common";

const VALID_CONFIDENCE: ConfidenceLevel[] = ["HIGH", "MEDIUM", "LOW"];
const VALID_TRUST: SensorTrustState[] = ["LIVE", "INFERRED", "UNKNOWN"];
const VALID_MATURITY: SensorMaturity[] = ["RICH", "PARTIAL", "POOR"];

export function assertMockDataIntegrity(): void {
  // ── 1. Exactly 45 stations ─────────────────────────────────────────────
  if (mockStations.length !== 45) {
    throw new Error(
      `[Mock Data] Expected 45 stations, got ${mockStations.length}.`,
    );
  }

  // ── 2. Unique station IDs S01–S45 ──────────────────────────────────────
  const ids = mockStations.map((s) => s.id);
  const uniqueIds = new Set(ids);
  if (uniqueIds.size !== 45) {
    const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
    throw new Error(`[Mock Data] Duplicate station IDs found: ${dupes.join(", ")}`);
  }

  for (let i = 1; i <= 45; i++) {
    const expected = `S${String(i).padStart(2, "0")}`;
    if (!uniqueIds.has(expected)) {
      throw new Error(`[Mock Data] Missing station ID: ${expected}`);
    }
  }

  // ── 3. Sensor maturity distribution: 29 RICH, 10 PARTIAL, 6 POOR ──────
  const maturityCount: Record<SensorMaturity, number> = { RICH: 0, PARTIAL: 0, POOR: 0 };
  for (const s of mockStations) {
    maturityCount[s.sensorMaturity]++;
  }

  if (maturityCount.RICH !== 29) {
    throw new Error(
      `[Mock Data] Expected 29 RICH stations, got ${maturityCount.RICH}.`,
    );
  }
  if (maturityCount.PARTIAL !== 10) {
    throw new Error(
      `[Mock Data] Expected 10 PARTIAL stations, got ${maturityCount.PARTIAL}.`,
    );
  }
  if (maturityCount.POOR !== 6) {
    throw new Error(
      `[Mock Data] Expected 6 POOR stations, got ${maturityCount.POOR}.`,
    );
  }

  // ── 4. All confidence values are valid ─────────────────────────────────
  for (const s of mockStations) {
    if (!VALID_CONFIDENCE.includes(s.confidence)) {
      throw new Error(
        `[Mock Data] Station ${s.id} has invalid confidence: "${s.confidence}".`,
      );
    }
  }

  // ── 5. All sensor trust values are valid ───────────────────────────────
  for (const s of mockStations) {
    if (!VALID_TRUST.includes(s.sensorTrustState)) {
      throw new Error(
        `[Mock Data] Station ${s.id} has invalid sensorTrustState: "${s.sensorTrustState}".`,
      );
    }
  }

  // ── 6. All sensor maturity values are valid ────────────────────────────
  for (const s of mockStations) {
    if (!VALID_MATURITY.includes(s.sensorMaturity)) {
      throw new Error(
        `[Mock Data] Station ${s.id} has invalid sensorMaturity: "${s.sensorMaturity}".`,
      );
    }
  }
}

/**
 * Returns a summary of the mock data integrity check results.
 * Useful for logging in development startup.
 */
export function getMockDataSummary(): {
  stationCount: number;
  maturityDistribution: Record<SensorMaturity, number>;
  allAssertionsPassed: boolean;
  error?: string;
} {
  const maturityDistribution: Record<SensorMaturity, number> = {
    RICH: 0, PARTIAL: 0, POOR: 0,
  };
  for (const s of mockStations) {
    maturityDistribution[s.sensorMaturity]++;
  }

  try {
    assertMockDataIntegrity();
    return {
      stationCount: mockStations.length,
      maturityDistribution,
      allAssertionsPassed: true,
    };
  } catch (e) {
    return {
      stationCount: mockStations.length,
      maturityDistribution,
      allAssertionsPassed: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}
