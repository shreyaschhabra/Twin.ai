/**
 * Throughput Trend Chart Component
 *
 * Renders an SVG bar/line chart representing completed vehicles per shift.
 * Uses clean axes, text labels, and grid lines. Fully responsive.
 */

import type { ShiftAnalytics } from "@/types/analytics";

interface ThroughputTrendChartProps {
  shifts: ShiftAnalytics[];
}

export function ThroughputTrendChart({ shifts }: ThroughputTrendChartProps) {
  if (shifts.length === 0) {
    return (
      <div className="h-48 flex items-center justify-center text-xs text-muted-foreground italic border rounded-lg bg-slate-50/50">
        No throughput trend data available.
      </div>
    );
  }

  const W = 500;
  const H = 160;
  const PAD_L = 36;
  const PAD_R = 16;
  const PAD_T = 12;
  const PAD_B = 28;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const values = shifts.map((s) => s.throughput);
  const minVal = Math.min(...values, 400); // Pad baseline
  const maxVal = Math.max(...values, 460);
  const range = maxVal - minVal;

  const n = shifts.length;

  const points = shifts.map((s, i) => {
    const x = PAD_L + (i / Math.max(n - 1, 1)) * chartW;
    const y = PAD_T + (1 - (s.throughput - minVal) / (range || 1)) * chartH;
    return { x, y, shiftId: s.shiftId, val: s.throughput };
  });

  // Build line path
  let pathD = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    pathD += ` L ${points[i].x} ${points[i].y}`;
  }

  // Y-axis grid labels
  const gridSteps = [minVal, minVal + range / 2, maxVal];

  return (
    <div className="w-full">
      <div className="overflow-x-auto select-none">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          className="min-w-[320px]"
          aria-label="Throughput Trend Chart"
        >
          {/* Y-axis Grid Lines */}
          {gridSteps.map((val, idx) => {
            const y = PAD_T + (1 - (val - minVal) / (range || 1)) * chartH;
            return (
              <g key={idx}>
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
                  {Math.round(val)}
                </text>
              </g>
            );
          })}

          {/* Trend line */}
          <path
            d={pathD}
            fill="none"
            stroke="#2563eb" // Blue-600
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Point dots */}
          {points.map((p, i) => (
            <g key={i} className="group/dot">
              <circle
                cx={p.x}
                cy={p.y}
                r={3}
                fill="#2563eb"
                stroke="white"
                strokeWidth={1}
              />
              <circle
                cx={p.x}
                cy={p.y}
                r={6}
                fill="#2563eb"
                fillOpacity={0}
                className="hover:fill-opacity-20 cursor-pointer transition-all"
              />
            </g>
          ))}

          {/* X-axis labels (render subset to avoid clutter) */}
          {points.map((p, i) => {
            const shouldRenderLabel = n <= 10 || i === 0 || i === n - 1 || i === Math.floor(n / 2);
            if (!shouldRenderLabel) return null;

            return (
              <text
                key={i}
                x={p.x}
                y={H - 8}
                textAnchor="middle"
                fontSize={8}
                fill="#64748b"
                className="font-mono"
              >
                {p.shiftId.replace("Shift ", "S")}
              </text>
            );
          })}
        </svg>
      </div>

      <div className="flex items-center justify-between mt-2 text-[10px] text-muted-foreground font-mono px-1">
        <span>Earlier shifts</span>
        <span>Latest shift (Shift 100)</span>
      </div>
    </div>
  );
}
