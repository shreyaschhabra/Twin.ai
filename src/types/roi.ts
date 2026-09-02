/**
 * ROI calculator input/output contracts.
 *
 * Inputs are collected from the customer/operator.
 * Outputs are computed by the ROI engine.
 */

/** Customer-provided inputs for ROI estimation. */
export type RoiInputs = {
  vehiclesPerYear: number;
  defectRate: number; // e.g. 0.04 for 4%
  averageReworkCost: number;

  bottleneckEventsPerMonth: number;
  averageDowntimeMinutesPerEvent: number;
  downtimeCostPerMinute: number;

  preventableReworkPct: number; // e.g. 0.15 for 15%
  avoidableDowntimePct: number; // e.g. 0.20 for 20%

  softwareIntegrationCost: number;
  sensorRetrofitCost: number;
  annualOperatingCost: number;
};

/** Estimated ROI outputs based on inputs. */
export type RoiOutputs = {
  annualDowntimeBenefit: number;
  annualQualityBenefit: number;
  annualGrossBenefit: number;
  initialInvestment: number;
  firstYearNetBenefit: number;
  steadyStateAnnualNetBenefit: number;
  roiPct: number | null;
  paybackMonths: number | null;
};

/** Combined ROI calculator state. */
export type RoiCalculation = {
  inputs: RoiInputs;
  outputs: RoiOutputs;
};
