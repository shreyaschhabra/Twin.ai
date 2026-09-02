/**
 * Probability Calibration Curve Chart Component
 *
 * Plots Observed Outcome Frequency (Y-axis, 0-100%) against Predicted Risk
 * Probability (X-axis, 0-100%). Includes a perfect calibration diagonal reference line.
 */

import type { CalibrationPoint } from "@/types/validation";

interface CalibrationChartProps {
  points?: CalibrationPoint[];
}

export function CalibrationChart({ points }: CalibrationChartProps) {
  // Pre-calculated representative demo calibration curve
  const displayPoints = !points || points.length === 0 ? [
    { meanPredicted: 0.1, fractionPositives: 0.08 },
    { meanPredicted: 0.3, fractionPositives: 0.26 },
    { meanPredicted: 0.5, fractionPositives: 0.44 },
    { meanPredicted: 0.7, fractionPositives: 0.68 },
    { meanPredicted: 0.9, fractionPositives: 0.85 },
  ] : points;

  const W = 500;
  const H = 220;
  const PAD_L = 40;
  const PAD_R = 20;
  const PAD_T = 20;
  const PAD_B = 32;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const svgPoints = displayPoints
    .map((p) => {
      const x = PAD_L + p.meanPredicted * chartW;
      const y = PAD_T + (1 - p.fractionPositives) * chartH;
      return { x, y, ...p };
    })
    .sort((a, b) => a.meanPredicted - b.meanPredicted);

  let pathD = `M ${svgPoints[0].x} ${svgPoints[0].y}`;
  for (let i = 1; i < svgPoints.length; i++) {
    pathD += ` L ${svgPoints[i].x} ${svgPoints[i].y}`;
  }

  const gridSteps = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="w-full">
      <div className="overflow-x-auto select-none">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          className="min-w-[320px]"
          aria-label="Probability Calibration Curve"
        >
          {/* Y-axis grids (Observed) */}
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

          {/* X-axis labels (Predicted) */}
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
                  {Math.round(val * 100)}%
                </text>
              </g>
            );
          })}

          {/* Perfect calibration reference line (Y=X) */}
          <line
            x1={PAD_L}
            y1={PAD_T + chartH}
            x2={PAD_L + chartW}
            y2={PAD_T}
            stroke="#94a3b8"
            strokeWidth={1.5}
            strokeDasharray="4 4"
          />

          {/* Model calibration line */}
          <path
            d={pathD}
            fill="none"
            stroke="#d97706" // Amber-600
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Bins points */}
          {svgPoints.map((p, i) => (
            <g key={i}>
              <circle
                cx={p.x}
                cy={p.y}
                r={3}
                fill="#d97706"
                stroke="white"
                strokeWidth={1}
              />
            </g>
          ))}

          {/* Chart Labels */}
          <text
            x={PAD_L + chartW / 2}
            y={H - 2}
            textAnchor="middle"
            fontSize={9}
            fill="#64748b"
            className="font-semibold uppercase tracking-wider"
          >
            Predicted Probability
          </text>
          <text
            transform={`rotate(-90 ${12} ${PAD_T + chartH / 2})`}
            x={12}
            y={PAD_T + chartH / 2}
            textAnchor="middle"
            fontSize={9}
            fill="#64748b"
            className="font-semibold uppercase tracking-wider"
          >
            Observed Frequency
          </text>
        </svg>
      </div>

      <div className="flex items-center justify-center gap-4 mt-2 text-[10px] text-muted-foreground font-mono">
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-0.5 border-t-2 border-dashed border-[#94a3b8]" />
          <span>Perfect Calibration</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-0.5 bg-[#d97706]" />
          <span>Current Model</span>
        </div>
      </div>
    </div>
  );
}
