/**
 * MOCK DATA — Development only.
 * Default ROI calculator inputs and estimated outputs for demo.
 * Real calculations will be performed by the backend or the UI calculator engine.
 */

import type { RoiCalculation } from "@/types/roi";

export const mockRoiDefaults: RoiCalculation = {
  inputs: {
    vehiclesPerYear: 120000,
    defectRate: 0.04,
    averageReworkCost: 18000,
    bottleneckEventsPerMonth: 18,
    averageDowntimeMinutesPerEvent: 7,
    downtimeCostPerMinute: 25000,
    preventableReworkPct: 0.15,
    avoidableDowntimePct: 0.20,
    softwareIntegrationCost: 3000000,
    sensorRetrofitCost: 1200000,
    annualOperatingCost: 800000,
  },
  outputs: {
    annualDowntimeBenefit: 7560000,
    annualQualityBenefit: 12960000,
    annualGrossBenefit: 20520000,
    initialInvestment: 4200000,
    firstYearNetBenefit: 15520000,
    steadyStateAnnualNetBenefit: 19720000,
    roiPct: 369.5,
    paybackMonths: 2.6,
  },
};
