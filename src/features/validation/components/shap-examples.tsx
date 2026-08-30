/**
 * SHAP Explainability Examples Component
 *
 * Renders frontend placeholders for future teammate-provided SHAP feature attribution.
 * Displays example contribution horizontal bars with "Demo explanation structure" disclaimer labels.
 */

import { HelpCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface SHAPExamplesProps {}

export function SHAPExamples({}: SHAPExamplesProps) {
  const flowFactors = [
    { name: "Buffer Growth Rate", value: 0.22 },
    { name: "Cycle-Time Velocity Slope", value: 0.18 },
    { name: "Arrival/Departure Sequence Gap", value: 0.14 },
    { name: "Vehicle Config Product Mix", value: 0.06 },
  ];

  const qualityFactors = [
    { name: "Max Anomaly Exposure Time", value: 0.31 },
    { name: "Process Telemetry Deviation", value: 0.24 },
    { name: "Tool/Station Maintenance Age", value: 0.18 },
    { name: "Cohort Batch Risk Indicator", value: 0.09 },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        {/* Flow ML Explainability */}
        <div className="border rounded-lg p-4 space-y-4">
          <div className="flex items-center justify-between border-b pb-2 flex-wrap gap-2">
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">
                FLOW INTELLIGENCE EXPLAINABILITY
              </h4>
              <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                Target: S18 Bottleneck Alert
              </p>
            </div>
            <Badge variant="outline" className="text-[9px] uppercase font-mono bg-slate-50">
              Demo Structure
            </Badge>
          </div>

          <div className="space-y-3">
            {flowFactors.map((factor, idx) => (
              <div key={idx} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground font-medium">{factor.name}</span>
                  <span className="font-mono font-bold text-blue-600">+{factor.value.toFixed(2)}</span>
                </div>
                <div className="w-full bg-muted h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-blue-600 h-full rounded-full"
                    style={{ width: `${(factor.value / 0.4) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Quality ML Explainability */}
        <div className="border rounded-lg p-4 space-y-4">
          <div className="flex items-center justify-between border-b pb-2 flex-wrap gap-2">
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">
                QUALITY INTELLIGENCE EXPLAINABILITY
              </h4>
              <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                Target: V2048 Defect Risk Flag
              </p>
            </div>
            <Badge variant="outline" className="text-[9px] uppercase font-mono bg-slate-50">
              Demo Structure
            </Badge>
          </div>

          <div className="space-y-3">
            {qualityFactors.map((factor, idx) => (
              <div key={idx} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground font-medium">{factor.name}</span>
                  <span className="font-mono font-bold text-amber-600">+{factor.value.toFixed(2)}</span>
                </div>
                <div className="w-full bg-muted h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-amber-600 h-full rounded-full"
                    style={{ width: `${(factor.value / 0.4) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="text-[10px] text-muted-foreground bg-slate-50/50 p-2.5 rounded border border-dashed flex items-start gap-2">
        <HelpCircle className="h-4 w-4 shrink-0 text-slate-400 mt-0.5" />
        <span>
          <strong>Explainability Protocol:</strong> Feature attribution values are precomputed offline via SHAP (SHapley Additive exPlanations). Teammates will integrate live kernel outputs during Phase 16; current factor attributions represent mock templates.
        </span>
      </div>
    </div>
  );
}
