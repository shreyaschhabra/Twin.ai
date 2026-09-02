/**
 * Precision-Recall Curve Chart Component
 *
 * Renders an SVG line chart plotting Precision on Y-axis (0-100%)
 * against Recall on X-axis (0-100%). Includes grid lines and axis labels.
 */

import type { PRCurvePoint } from "@/types/validation";

interface PrecisionRecallChartProps {
  points: PRCurvePoint[];
}

export function PrecisionRecallChart({ points }: PrecisionRecallChartProps) {
  if (!points || points.length === 0) {
    return (
      <div className="h-48 flex items-center justify-center text-xs text-muted-foreground italic border rounded-lg bg-slate-50/50">
        No PR curve points available.
      </div>
    );
  }

  const W = 500;
  const H = 220;
  const PAD_L = 40;
  const PAD_R = 20;
  const PAD_T = 20;
  const PAD_B = 32;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  // Map 0.0-1.0 points to SVG coordinates
  // X is Recall (0 to 1), Y is Precision (0 to 1)
  const svgPoints = points
    .map((p) => {
      const x = PAD_L + p.recall * chartW;
      const y = PAD_T + (1 - p.precision) * chartH;
      return { x, y, ...p };
    })
    .sort((a, b) => a.recall - b.recall);

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
          aria-label="Precision-Recall Curve"
        >
          {/* Y-axis grids (Precision) */}
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

          {/* X-axis labels (Recall) */}
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

          {/* PR Curve Line */}
          <path
            d={pathD}
            fill="none"
            stroke="#2563eb" // Blue-600
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Points dots */}
          {svgPoints.map((p, i) => (
            <g key={i} className="group/dot">
              <circle
                cx={p.x}
                cy={p.y}
                r={3.5}
                fill="#2563eb"
                stroke="white"
                strokeWidth={1.5}
              />
              <title>
                Threshold: {p.threshold.toFixed(2)} | Prec: {Math.round(p.precision * 100)}% | Recall: {Math.round(p.recall * 100)}%
              </title>
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
            Recall (Sensitivity)
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
            Precision (PPV)
          </text>
        </svg>
      </div>
    </div>
  );
}
