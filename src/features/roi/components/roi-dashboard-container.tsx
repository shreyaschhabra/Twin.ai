/**
 * ROI Dashboard Container Component
 *
 * Coordinates client-side interactive state for the ROI Calculator:
 * - Scenario Presets (Conservative, Base, Optimistic, Custom)
 * - Input Groups: Production, Quality, Flow, Costs, Effectiveness
 * - Recalculates benefits, investments, first-year nets, payback periods, and ROI %
 * - India/USD Currency selector toggle
 * - Visual bar breakdowns and sensitivity modeling grids
 * - Cautious disclaimer advisories and formula disclosures
 */

"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  TrendingUp,
  Activity,
  ArrowLeft,
  HelpCircle,
  AlertTriangle,
  RotateCcw,
  Sparkles,
  DollarSign,
  Maximize2,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { calculateRoi } from "../lib/calculate-roi";
import { formatCurrency, formatNumber } from "../lib/roi-formatters";
import type { RoiCalculation, RoiInputs } from "@/types/roi";

interface RoiDashboardContainerProps {
  defaultCalculation: RoiCalculation;
}

const PRESETS = {
  conservative: {
    vehiclesPerYear: 120000,
    defectRate: 0.04,
    averageReworkCost: 18000,
    bottleneckEventsPerMonth: 12,
    averageDowntimeMinutesPerEvent: 5,
    downtimeCostPerMinute: 20000,
    preventableReworkPct: 0.08,
    avoidableDowntimePct: 0.10,
    softwareIntegrationCost: 3500000,
    sensorRetrofitCost: 1500000,
    annualOperatingCost: 1000000,
  },
  base: {
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
  optimistic: {
    vehiclesPerYear: 120000,
    defectRate: 0.04,
    averageReworkCost: 18000,
    bottleneckEventsPerMonth: 24,
    averageDowntimeMinutesPerEvent: 10,
    downtimeCostPerMinute: 30000,
    preventableReworkPct: 0.25,
    avoidableDowntimePct: 0.35,
    softwareIntegrationCost: 2500000,
    sensorRetrofitCost: 1000000,
    annualOperatingCost: 600000,
  },
};

export function RoiDashboardContainer({ defaultCalculation }: RoiDashboardContainerProps) {
  const [inputs, setInputs] = useState<RoiInputs>(defaultCalculation.inputs);
  const [currency, setCurrency] = useState<"INR" | "USD">("INR");
  const [preset, setPreset] = useState<string>("base"); // conservative, base, optimistic, custom
  const [showFormula, setShowFormula] = useState(false);

  // Recalculate outputs dynamically whenever inputs change
  const outputs = useMemo(() => {
    return calculateRoi(inputs);
  }, [inputs]);

  // Handle preset application
  const handleApplyPreset = (key: "conservative" | "base" | "optimistic") => {
    setPreset(key);
    // Convert preset to matched currency values if USD is toggled
    const baseInputs = PRESETS[key];
    if (currency === "USD") {
      setInputs({
        ...baseInputs,
        averageReworkCost: Math.round(baseInputs.averageReworkCost / 80),
        downtimeCostPerMinute: Math.round(baseInputs.downtimeCostPerMinute / 80),
        softwareIntegrationCost: Math.round(baseInputs.softwareIntegrationCost / 80),
        sensorRetrofitCost: Math.round(baseInputs.sensorRetrofitCost / 80),
        annualOperatingCost: Math.round(baseInputs.annualOperatingCost / 80),
      });
    } else {
      setInputs(baseInputs);
    }
  };

  // Convert current input values when currency toggles
  const handleCurrencyToggle = (target: "INR" | "USD") => {
    if (target === currency) return;
    setCurrency(target);

    const conversionFactor = target === "USD" ? 1 / 80 : 80;
    setInputs((prev) => ({
      ...prev,
      averageReworkCost: Math.round(prev.averageReworkCost * conversionFactor),
      downtimeCostPerMinute: Math.round(prev.downtimeCostPerMinute * conversionFactor),
      softwareIntegrationCost: Math.round(prev.softwareIntegrationCost * conversionFactor),
      sensorRetrofitCost: Math.round(prev.sensorRetrofitCost * conversionFactor),
      annualOperatingCost: Math.round(prev.annualOperatingCost * conversionFactor),
    }));
  };

  // Handle single input change
  const handleInputChange = (field: keyof RoiInputs, val: number) => {
    setPreset("custom");
    setInputs((prev) => ({
      ...prev,
      [field]: val,
    }));
  };

  // Reset to default
  const handleReset = () => {
    setCurrency("INR");
    setPreset("base");
    setInputs(defaultCalculation.inputs);
  };

  // Sensitivity matrix calculation (avoidable downtime vs preventable rework)
  const sensitivityData = useMemo(() => {
    const downtimeAvoidanceLevels = [0.10, 0.20, 0.30];
    const qualityPreventableLevels = [0.10, 0.15, 0.20];

    return downtimeAvoidanceLevels.map((dt) => {
      return qualityPreventableLevels.map((q) => {
        const testInputs = {
          ...inputs,
          avoidableDowntimePct: dt,
          preventableReworkPct: q,
        };
        const testOutputs = calculateRoi(testInputs);
        return {
          downtimePct: dt,
          reworkPct: q,
          roiPct: testOutputs.roiPct,
          annualGrossBenefit: testOutputs.annualGrossBenefit,
        };
      });
    });
  }, [inputs]);

  return (
    <div className="space-y-6">
      {/* ── HEADER CROSS LINKS & CURRENCY TOGGLE ── */}
      <div className="flex items-center justify-between gap-3 flex-wrap border-b pb-3">
        <Link
          href="/app/leadership"
          className="text-xs font-semibold text-blue-600 hover:underline flex items-center gap-1"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Leadership Overview
        </Link>

        <div className="flex items-center gap-4">
          {/* Currency Toggle */}
          <div className="flex rounded border overflow-hidden text-xs font-mono">
            <button
              onClick={() => handleCurrencyToggle("INR")}
              className={`px-3 py-1 font-bold ${
                currency === "INR" ? "bg-slate-200 text-foreground" : "bg-white text-muted-foreground hover:bg-slate-50"
              }`}
            >
              INR (₹)
            </button>
            <button
              onClick={() => handleCurrencyToggle("USD")}
              className={`px-3 py-1 font-bold ${
                currency === "USD" ? "bg-slate-200 text-foreground" : "bg-white text-muted-foreground hover:bg-slate-50"
              }`}
            >
              USD ($)
            </button>
          </div>

          <button
            onClick={handleReset}
            className="text-xs font-semibold text-muted-foreground hover:text-foreground flex items-center gap-1.5"
            title="Reset default values"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </button>
        </div>
      </div>

      {/* ── SCENARIO PRESETS ── */}
      <div className="flex items-center gap-2 flex-wrap bg-slate-50 border rounded-lg p-3">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider pr-2">
          Scenario Presets
        </span>
        <button
          onClick={() => handleApplyPreset("conservative")}
          className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
            preset === "conservative"
              ? "bg-slate-800 text-white"
              : "bg-white border text-foreground hover:bg-slate-50"
          }`}
        >
          Conservative
        </button>
        <button
          onClick={() => handleApplyPreset("base")}
          className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
            preset === "base"
              ? "bg-slate-800 text-white"
              : "bg-white border text-foreground hover:bg-slate-50"
          }`}
        >
          Base Scenario
        </button>
        <button
          onClick={() => handleApplyPreset("optimistic")}
          className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
            preset === "optimistic"
              ? "bg-slate-800 text-white"
              : "bg-white border text-foreground hover:bg-slate-50"
          }`}
        >
          Optimistic
        </button>
        {preset === "custom" && (
          <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 text-[10px] uppercase font-bold py-0.5 px-2">
            Custom Scenario
          </Badge>
        )}
      </div>

      {/* ── CORE CALCULATOR WORKSPACE ── */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* INPUT ASSUMPTIONS FORM */}
        <div className="space-y-6">
          <Card className="border shadow-none">
            <CardHeader className="pb-3 border-b bg-muted/20">
              <CardTitle className="text-sm font-semibold">Configurable Plant Inputs</CardTitle>
              <CardDescription className="text-xs">
                Adjust sliders or type values directly to model your factory configuration.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              {/* GROUP 1: PRODUCTION */}
              <div className="space-y-3">
                <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider border-b pb-1">
                  1. Production Volume
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <label htmlFor="vehiclesPerYear" className="text-xs font-medium text-foreground">
                      Vehicles per Year
                    </label>
                    <Input
                      id="vehiclesPerYear"
                      type="number"
                      value={inputs.vehiclesPerYear}
                      onChange={(e) => handleInputChange("vehiclesPerYear", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs"
                      min={0}
                    />
                  </div>
                </div>
              </div>

              {/* GROUP 2: QUALITY */}
              <div className="space-y-3 pt-2">
                <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider border-b pb-1">
                  2. Quality & Rework
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <label htmlFor="defectRate" className="text-xs font-medium text-foreground">
                      Defect Rate ({Math.round(inputs.defectRate * 100)}%)
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        id="defectRate"
                        type="range"
                        min="0"
                        max="0.2"
                        step="0.005"
                        value={inputs.defectRate}
                        onChange={(e) => handleInputChange("defectRate", parseFloat(e.target.value))}
                        className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer"
                      />
                      <span className="text-xs font-mono font-medium min-w-[32px] text-right">
                        {(inputs.defectRate * 100).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="averageReworkCost" className="text-xs font-medium text-foreground">
                      Avg Rework Cost / Case
                    </label>
                    <Input
                      id="averageReworkCost"
                      type="number"
                      value={inputs.averageReworkCost}
                      onChange={(e) => handleInputChange("averageReworkCost", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs font-mono"
                      min={0}
                    />
                  </div>
                </div>
              </div>

              {/* GROUP 3: FLOW / DOWNTIME */}
              <div className="space-y-3 pt-2">
                <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider border-b pb-1">
                  3. Flow & Downtime
                </h4>
                <div className="grid grid-cols-3 gap-2">
                  <div className="space-y-1">
                    <label htmlFor="eventsPerMonth" className="text-[11px] font-medium text-foreground">
                      Events / Month
                    </label>
                    <Input
                      id="eventsPerMonth"
                      type="number"
                      value={inputs.bottleneckEventsPerMonth}
                      onChange={(e) => handleInputChange("bottleneckEventsPerMonth", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs font-mono"
                      min={0}
                    />
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="downtimePerEvent" className="text-[11px] font-medium text-foreground">
                      Avg Mins / Event
                    </label>
                    <Input
                      id="downtimePerEvent"
                      type="number"
                      value={inputs.averageDowntimeMinutesPerEvent}
                      onChange={(e) => handleInputChange("averageDowntimeMinutesPerEvent", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs font-mono"
                      min={0}
                    />
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="costPerMin" className="text-[11px] font-medium text-foreground">
                      Cost / Minute
                    </label>
                    <Input
                      id="costPerMin"
                      type="number"
                      value={inputs.downtimeCostPerMinute}
                      onChange={(e) => handleInputChange("downtimeCostPerMinute", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs font-mono"
                      min={0}
                    />
                  </div>
                </div>
              </div>

              {/* GROUP 4: EFFECTIVENESS ASSUMPTIONS */}
              <div className="space-y-3 pt-2">
                <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider border-b pb-1">
                  4. Twin AI Effectiveness Assumptions
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <label htmlFor="avoidableDowntimePct" className="text-xs font-medium text-foreground">
                      Avoidable Downtime ({Math.round(inputs.avoidableDowntimePct * 100)}%)
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        id="avoidableDowntimePct"
                        type="range"
                        min="0"
                        max="0.8"
                        step="0.05"
                        value={inputs.avoidableDowntimePct}
                        onChange={(e) => handleInputChange("avoidableDowntimePct", parseFloat(e.target.value))}
                        className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer"
                      />
                      <span className="text-xs font-mono font-medium min-w-[32px] text-right">
                        {(inputs.avoidableDowntimePct * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="preventableReworkPct" className="text-xs font-medium text-foreground">
                      Preventable Rework ({Math.round(inputs.preventableReworkPct * 100)}%)
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        id="preventableReworkPct"
                        type="range"
                        min="0"
                        max="0.8"
                        step="0.05"
                        value={inputs.preventableReworkPct}
                        onChange={(e) => handleInputChange("preventableReworkPct", parseFloat(e.target.value))}
                        className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer"
                      />
                      <span className="text-xs font-mono font-medium min-w-[32px] text-right">
                        {(inputs.preventableReworkPct * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* GROUP 5: COSTS */}
              <div className="space-y-3 pt-2">
                <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider border-b pb-1">
                  5. Implementation Investment
                </h4>
                <div className="grid grid-cols-3 gap-2">
                  <div className="space-y-1">
                    <label htmlFor="softwareIntegrationCost" className="text-[11px] font-medium text-foreground">
                      Software Setup
                    </label>
                    <Input
                      id="softwareIntegrationCost"
                      type="number"
                      value={inputs.softwareIntegrationCost}
                      onChange={(e) => handleInputChange("softwareIntegrationCost", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs font-mono"
                      min={0}
                    />
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="sensorRetrofitCost" className="text-[11px] font-medium text-foreground">
                      Sensor Retrofit
                    </label>
                    <Input
                      id="sensorRetrofitCost"
                      type="number"
                      value={inputs.sensorRetrofitCost}
                      onChange={(e) => handleInputChange("sensorRetrofitCost", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs font-mono"
                      min={0}
                    />
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="annualOperatingCost" className="text-[11px] font-medium text-foreground">
                      Annual OpCost
                    </label>
                    <Input
                      id="annualOperatingCost"
                      type="number"
                      value={inputs.annualOperatingCost}
                      onChange={(e) => handleInputChange("annualOperatingCost", parseInt(e.target.value, 10) || 0)}
                      className="h-8 text-xs font-mono"
                      min={0}
                    />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ESTIMATED BUSINESS CASE OUTPUTS */}
        <div className="space-y-6">
          <Card className="border shadow-none bg-slate-50/50">
            <CardHeader className="pb-3 border-b bg-white">
              <CardTitle className="text-sm font-semibold">Estimated Business Case Outcomes</CardTitle>
              <CardDescription className="text-xs">
                Derived values based on your scenario settings. Results are illustrative estimates.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-6">
              {/* Output cards grid */}
              <div className="grid grid-cols-2 gap-3">
                {/* Gross Benefit */}
                <div className="bg-white border rounded p-3 text-left">
                  <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-wider block">
                    Annual Gross Benefit
                  </span>
                  <span className="text-lg font-bold font-mono text-foreground block mt-1">
                    {formatCurrency(outputs.annualGrossBenefit, currency, true)}
                  </span>
                  <span className="text-[8px] text-muted-foreground font-medium block mt-0.5 uppercase">
                    downtime + quality benefits
                  </span>
                </div>

                {/* Net Benefit */}
                <div className="bg-white border rounded p-3 text-left">
                  <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-wider block">
                    First-Year Net Benefit
                  </span>
                  <span className={`text-lg font-bold font-mono block mt-1 ${outputs.firstYearNetBenefit >= 0 ? "text-emerald-800" : "text-red-700"}`}>
                    {formatCurrency(outputs.firstYearNetBenefit, currency, true)}
                  </span>
                  <span className="text-[8px] text-muted-foreground font-medium block mt-0.5 uppercase">
                    investment & opcost subtracted
                  </span>
                </div>

                {/* ROI % */}
                <div className="bg-white border rounded p-3 text-left">
                  <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-wider block">
                    Illustrative ROI
                  </span>
                  <span className={`text-lg font-bold font-mono block mt-1 ${outputs.roiPct !== null && outputs.roiPct >= 0 ? "text-emerald-800" : "text-red-700"}`}>
                    {outputs.roiPct !== null ? `${outputs.roiPct}%` : "N/A"}
                  </span>
                  <span className="text-[8px] text-muted-foreground font-medium block mt-0.5 uppercase">
                    initial investment return
                  </span>
                </div>

                {/* Payback Months */}
                <div className="bg-white border rounded p-3 text-left">
                  <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-wider block">
                    Estimated Payback
                  </span>
                  <span className="text-sm font-bold block mt-1.5 text-foreground leading-tight">
                    {outputs.paybackMonths !== null ? `${outputs.paybackMonths} months` : "No positive payback"}
                  </span>
                  <span className="text-[8px] text-muted-foreground font-medium block mt-0.5 uppercase">
                    breakeven duration
                  </span>
                </div>
              </div>

              {/* Value breakdown stacked bar */}
              <div className="space-y-2 border-t pt-3 bg-white p-3 rounded border">
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider block">
                  Estimated value contribution
                </span>
                <div className="h-5 w-full bg-slate-100 rounded overflow-hidden flex border">
                  {outputs.annualGrossBenefit > 0 ? (
                    <>
                      <div
                        className="bg-blue-600 h-full flex items-center justify-center text-[9px] text-white font-mono font-bold"
                        style={{ width: `${(outputs.annualDowntimeBenefit / outputs.annualGrossBenefit) * 100}%` }}
                        title={`Downtime benefit: ${formatCurrency(outputs.annualDowntimeBenefit, currency)}`}
                      >
                        {outputs.annualDowntimeBenefit > 0 && "Downtime"}
                      </div>
                      <div
                        className="bg-red-600 h-full flex items-center justify-center text-[9px] text-white font-mono font-bold"
                        style={{ width: `${(outputs.annualQualityBenefit / outputs.annualGrossBenefit) * 100}%` }}
                        title={`Quality benefit: ${formatCurrency(outputs.annualQualityBenefit, currency)}`}
                      >
                        {outputs.annualQualityBenefit > 0 && "Quality"}
                      </div>
                    </>
                  ) : (
                    <div className="w-full text-center text-[10px] text-muted-foreground flex items-center justify-center">
                      No calculated gross benefits
                    </div>
                  )}
                </div>
                <div className="flex justify-between text-[9px] font-mono text-muted-foreground">
                  <div>Downtime: {formatCurrency(outputs.annualDowntimeBenefit, currency, true)}</div>
                  <div>Quality: {formatCurrency(outputs.annualQualityBenefit, currency, true)}</div>
                </div>
              </div>

              {/* Cost breakdown stacked bar */}
              <div className="space-y-2 border-t pt-3 bg-white p-3 rounded border">
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider block">
                  Implementation Costs Breakdown
                </span>
                <div className="grid grid-cols-3 gap-2 text-xs font-mono">
                  <div className="p-1 border rounded text-center">
                    <span className="block text-[8px] font-sans text-muted-foreground uppercase">Software Setup</span>
                    <span className="font-bold">{formatCurrency(inputs.softwareIntegrationCost, currency, true)}</span>
                  </div>
                  <div className="p-1 border rounded text-center">
                    <span className="block text-[8px] font-sans text-muted-foreground uppercase">Retrofits</span>
                    <span className="font-bold">{formatCurrency(inputs.sensorRetrofitCost, currency, true)}</span>
                  </div>
                  <div className="p-1 border rounded text-center text-amber-800">
                    <span className="block text-[8px] font-sans text-muted-foreground uppercase">Annual OpCost</span>
                    <span className="font-bold">{formatCurrency(inputs.annualOperatingCost, currency, true)}</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ── SECTION 5: Sensitivity Analysis ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">Scenario Sensitivity Modeling</CardTitle>
          <CardDescription className="text-xs">
            Matrix showing resulting illustrative ROI % across varying avoidable downtime and preventable quality rework rates.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="rounded border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40">
                  <TableHead className="text-xs font-semibold">Downtime Avoidance \ Quality Rework</TableHead>
                  <TableHead className="text-xs font-semibold text-center">10% Preventable Rework</TableHead>
                  <TableHead className="text-xs font-semibold text-center">15% Preventable Rework</TableHead>
                  <TableHead className="text-xs font-semibold text-center">20% Preventable Rework</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sensitivityData.map((row, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="text-xs font-mono font-bold">
                      {Math.round(row[0].downtimePct * 100)}% Avoidable Downtime
                    </TableCell>
                    {row.map((cell, cIdx) => (
                      <TableCell key={cIdx} className="text-xs text-center font-mono">
                        <div className="space-y-0.5">
                          <span className="font-bold text-foreground">
                            {cell.roiPct !== null ? `${cell.roiPct}%` : "N/A"}
                          </span>
                          <span className="block text-[9px] text-muted-foreground">
                            {formatCurrency(cell.annualGrossBenefit, currency, true)} benefit
                          </span>
                        </div>
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="text-[10px] text-muted-foreground italic text-center mt-2">
            Note: Sensitivity model ROI % updates relative to software, retrofit, and operating costs.
          </p>
        </CardContent>
      </Card>

      {/* ── SECTION 6: Current Assumptions Summary ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-2 bg-muted/20">
          <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Current Scenario Summary
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-3 text-xs text-muted-foreground leading-relaxed">
          Modeling a plant segment outputting <strong>{formatNumber(inputs.vehiclesPerYear)} vehicles/year</strong> with an initial defect rate of <strong>{(inputs.defectRate * 100).toFixed(1)}%</strong> (averaging <strong>{formatCurrency(inputs.averageReworkCost, currency)}</strong> rework cost per vehicle). The line experiences <strong>{inputs.bottleneckEventsPerMonth} bottlenecks/month</strong> (averaging <strong>{inputs.averageDowntimeMinutesPerEvent} minutes</strong> each at <strong>{formatCurrency(inputs.downtimeCostPerMinute, currency)}/minute</strong>). We assume <strong>{Math.round(inputs.avoidableDowntimePct * 100)}% avoidable downtime</strong> and <strong>{Math.round(inputs.preventableReworkPct * 100)}% preventable defects</strong> with an initial integration investment of <strong>{formatCurrency(inputs.softwareIntegrationCost + inputs.sensorRetrofitCost, currency)}</strong>.
        </CardContent>
      </Card>

      {/* ── SECTION 7: Formula Explanation ── */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b flex flex-row items-center justify-between pointer-events-auto">
          <div>
            <CardTitle className="text-sm font-semibold">How this estimate is calculated</CardTitle>
            <CardDescription className="text-xs">
              Transparent, deterministic formulas for leadership trust.
            </CardDescription>
          </div>
          <button
            onClick={() => setShowFormula(!showFormula)}
            className="text-xs font-semibold text-blue-600 hover:underline"
          >
            {showFormula ? "Hide Formula" : "Expand Formula"}
          </button>
        </CardHeader>
        {showFormula && (
          <CardContent className="pt-4 space-y-4 text-xs text-muted-foreground leading-relaxed">
            <div>
              <h5 className="font-bold text-foreground mb-1 uppercase tracking-wide text-[10px]">
                Downtime Benefit Formula
              </h5>
              <div className="bg-slate-50 p-2.5 rounded font-mono text-[10px] text-foreground">
                Annual Bottlenecks = Events / Month × 12
                <br />
                Annual Downtime Mins = Annual Bottlenecks × Average Downtime Mins
                <br />
                Addressable Downtime Mins = Annual Downtime Mins × Avoidable Downtime %
                <br />
                Downtime Benefit = Addressable Downtime Mins × Downtime Cost / Minute
              </div>
            </div>

            <div>
              <h5 className="font-bold text-foreground mb-1 uppercase tracking-wide text-[10px]">
                Quality/Rework Benefit Formula
              </h5>
              <div className="bg-slate-50 p-2.5 rounded font-mono text-[10px] text-foreground">
                Annual Defects = Vehicles / Year × Defect Rate
                <br />
                Prevented Defects = Annual Defects × Preventable Rework %
                <br />
                Quality Benefit = Prevented Defects × Average Rework Cost
              </div>
            </div>

            <div>
              <h5 className="font-bold text-foreground mb-1 uppercase tracking-wide text-[10px]">
                Financial ROI & Payback Formulas
              </h5>
              <div className="bg-slate-50 p-2.5 rounded font-mono text-[10px] text-foreground">
                Initial Investment = Software Integration + Sensor Retrofit
                <br />
                Steady-State Net Benefit = Gross Benefit - Annual Operating Cost
                <br />
                First-Year Net Benefit = Gross Benefit - Initial Investment - Annual Operating Cost
                <br />
                ROI % = (Gross Benefit - Annual Operating Cost - Initial Investment) / Initial Investment × 100
                <br />
                Payback Period = Initial Investment / (Steady-State Net Benefit / 12)
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ── SECTION 8: Disclaimer ── */}
      <Card className="border shadow-none bg-slate-50/20">
        <CardContent className="pt-4 flex items-start gap-2 text-xs text-muted-foreground leading-relaxed">
          <AlertTriangle className="h-4.5 w-4.5 shrink-0 text-slate-500 mt-0.5" />
          <span>
            <strong>Scenario Disclaimer:</strong> These values are illustrative scenario estimates. Actual savings depend on plant economics, model effectiveness, operational adoption, operator response loops, and deployment line conditions. Twin AI does not directly write plc commands or autonomously stop line operations.
          </span>
        </CardContent>
      </Card>
    </div>
  );
}
