/**
 * Alert Threshold Trade-off Chart Component
 *
 * Plots Precision and Recall curves across different classification thresholds
 * to visualize optimal trade-offs. Highlights the currently selected validation threshold.
 */

import type { ThresholdTradeoff } from "@/types/validation";

interface ThresholdTradeoffChartProps {
  tradeoffs?: ThresholdTradeoff[];
  selectedThreshold?: number;
}

export function ThresholdTradeoffChart({ tradeoffs, selectedThreshold = 0.65 }: ThresholdTradeoffChartProps) {
  // Pre-calculated representative tradeoffs
  const displayTradeoffs = !tradeoffs || tradeoffs.length === 0 ? [
    { threshold: 0.35, precision: 0.62, recall: 0.94, alertsPerShift: 5.1 },
    { threshold: 0.45, precision: 0.73, recall: 0.89, alertsPerShift: 3.8 },
    { threshold: 0.55, precision: 0.81, recall: 0.84, alertsPerShift: 2.9 },
    { threshold: 0.65, precision: 0.86, recall: 0.82, alertsPerShift: 2.2 },
    { threshold: 0.75, precision: 0.91, recall: 0.71, alertsPerShift: 1.6 },
    { threshold: 0.85, precision: 0.95, recall: 0.55, alertsPerShift: 1.1 },
  ] : tradeoffs;

  const W = 500;
  const H = 220;
  const PAD_L = 40;
  const PAD_R = 20;
  const PAD_T = 20;
  const PAD_B = 32;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  // Map points to SVG coordinates
  const precisionPoints = displayTradeoffs.map((t) => {
    const x = PAD_L + t.threshold * chartW;
    const y = PAD_T + (1 - t.precision) * chartH;
    return { x, y };
  });

  const recallPoints = displayTradeoffs.map((t) => {
    const x = PAD_L + t.threshold * chartW;
    const y = PAD_T + (1 - t.recall) * chartH;
    return { x, y };
  });

  let precPath = `M ${precisionPoints[0].x} ${precisionPoints[0].y}`;
  let recallPath = `M ${recallPoints[0].x} ${recallPoints[0].y}`;

  for (let i = 1; i < displayTradeoffs.length; i++) {
    precPath += ` L ${precisionPoints[i].x} ${precisionPoints[i].y}`;
    recallPath += ` L ${recallPoints[i].x} ${recallPoints[i].y}`;
  }

  const gridSteps = [0, 0.25, 0.5, 0.75, 1];

  // Selected threshold X coordinate
  const thresholdX = PAD_L + selectedThreshold * chartW;

  return (
    <div className="w-full">
      <div className="overflow-x-auto select-none">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          className="min-w-[320px]"
          aria-label="Alert Threshold Trade-off Chart"
        >
          {/* Y-axis Grid Lines */}
          {gridSteps.map((val) => {
            const y = PAD_T + (1 - val) * chartH;
            return (
              <g key={`y-${val}`}>
                <line
                  x1={PAD_L}
                  y1={y}
                  x2={W - PAD_R}
                  y2={y}
                  stroke="#e2e8f0"
                  strokeWidth={1}
                  strokeDasharray="2 4"
                />
                <text
                  x={PAD_L - 6}
                  y={y + 3}
                  textAnchor="end"
                  fontSize={8}
                  fill="#94a3b8"
                  className="font-mono font-medium"
                >
                  {Math.round(val * 100)}%
                </text>
              </g>
            );
          })}

          {/* X-axis Grid Lines (Thresholds) */}
          {gridSteps.map((val) => {
            const x = PAD_L + val * chartW;
            return (
              <g key={`x-${val}`}>
                <line
                  x1={x}
                  y1={PAD_T}
                  x2={x}
                  y2={H - PAD_B}
                  stroke="#e2e8f0"
                  strokeWidth={1}
                  strokeDasharray="2 4"
                />
                <text
                  x={x}
                  y={H - 12}
                  textAnchor="middle"
                  fontSize={8}
                  fill="#94a3b8"
                  className="font-mono font-medium"
                >
                  {val.toFixed(2)}
                </text>
              </g>
            );
          })}

          {/* Selected Threshold Marker Indicator */}
          <line
            x1={thresholdX}
            y1={PAD_T}
            x2={thresholdX}
            y2={H - PAD_B}
            stroke="#2563eb"
            strokeWidth={1.5}
            strokeDasharray="3 3"
          />
          <text
            x={thresholdX}
            y={PAD_T - 4}
            textAnchor="middle"
            fontSize={7}
            fill="#2563eb"
            className="font-mono font-bold uppercase"
          >
            Threshold: {selectedThreshold}
          </text>

          {/* Precision curve (Blue) */}
          <path
            d={precPath}
            fill="none"
            stroke="#2563eb" // Blue-600
            strokeWidth={2}
            strokeLinecap="round"
          />

          {/* Recall curve (Amber) */}
          <path
            d={recallPath}
            fill="none"
            stroke="#d97706" // Amber-600
            strokeWidth={2}
            strokeLinecap="round"
          />

          {/* Chart Labels */}
          <text
            x={PAD_L + chartW / 2}
            y={H - 2}
            textAnchor="middle"
            fontSize={9}
            fill="#64748b"
            className="font-semibold uppercase tracking-wider"
          >
            Alert Decision Threshold
          </text>
        </svg>
      </div>

      <div className="flex items-center justify-center gap-4 mt-2 text-[10px] text-muted-foreground font-mono">
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-0.5 bg-[#2563eb]" />
          <span>Precision (PPV)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-0.5 bg-[#d97706]" />
          <span>Recall (Sensitivity)</span>
        </div>
      </div>
    </div>
  );
}
