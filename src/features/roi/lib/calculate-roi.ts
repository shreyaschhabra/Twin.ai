/**
 * ROI Calculation Utility
 *
 * Deterministic formulas for computing downtime benefits, quality savings,
 * implementation costs, net benefits, ROI percentages, and payback periods.
 */

import type { RoiInputs, RoiOutputs } from "@/types/roi";

/**
 * Computes estimated ROI outputs based on configurable plant inputs.
 */
export function calculateRoi(inputs: RoiInputs): RoiOutputs {
  // Input validations & sanitization
  const vehiclesPerYear = Math.max(0, inputs.vehiclesPerYear);
  const defectRate = Math.min(1, Math.max(0, inputs.defectRate));
  const averageReworkCost = Math.max(0, inputs.averageReworkCost);

  const bottleneckEventsPerMonth = Math.max(0, inputs.bottleneckEventsPerMonth);
  const averageDowntimeMinutesPerEvent = Math.max(0, inputs.averageDowntimeMinutesPerEvent);
  const downtimeCostPerMinute = Math.max(0, inputs.downtimeCostPerMinute);

  const preventableReworkPct = Math.min(1, Math.max(0, inputs.preventableReworkPct));
  const avoidableDowntimePct = Math.min(1, Math.max(0, inputs.avoidableDowntimePct));

  const softwareIntegrationCost = Math.max(0, inputs.softwareIntegrationCost);
  const sensorRetrofitCost = Math.max(0, inputs.sensorRetrofitCost);
  const annualOperatingCost = Math.max(0, inputs.annualOperatingCost);

  // 1. Downtime Benefit
  const eventsPerYear = bottleneckEventsPerMonth * 12;
  const annualDowntimeMinutes = eventsPerYear * averageDowntimeMinutesPerEvent;
  const addressableDowntimeMinutes = annualDowntimeMinutes * avoidableDowntimePct;
  const annualDowntimeBenefit = Math.round(addressableDowntimeMinutes * downtimeCostPerMinute);

  // 2. Quality/Rework Benefit
  const defectsPerYear = vehiclesPerYear * defectRate;
  const preventableReworkCount = defectsPerYear * preventableReworkPct;
  const annualQualityBenefit = Math.round(preventableReworkCount * averageReworkCost);

  // 3. Gross Benefit
  const annualGrossBenefit = annualDowntimeBenefit + annualQualityBenefit;

  // 4. Initial Investment
  const initialInvestment = softwareIntegrationCost + sensorRetrofitCost;

  // 5. Net Benefits
  const firstYearNetBenefit = annualGrossBenefit - initialInvestment - annualOperatingCost;
  const steadyStateAnnualNetBenefit = annualGrossBenefit - annualOperatingCost;

  // 6. ROI percentage
  let roiPct: number | null = null;
  if (initialInvestment > 0) {
    roiPct = Math.round(((annualGrossBenefit - annualOperatingCost - initialInvestment) / initialInvestment) * 1000) / 10;
  }

  // 7. Payback period
  let paybackMonths: number | null = null;
  const monthlyNetBenefit = steadyStateAnnualNetBenefit / 12;
  if (monthlyNetBenefit > 0 && initialInvestment > 0) {
    paybackMonths = Math.round((initialInvestment / monthlyNetBenefit) * 10) / 10;
  }

  return {
    annualDowntimeBenefit,
    annualQualityBenefit,
    annualGrossBenefit,
    initialInvestment,
    firstYearNetBenefit,
    steadyStateAnnualNetBenefit,
    roiPct,
    paybackMonths,
  };
}
