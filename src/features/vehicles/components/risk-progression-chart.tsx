/**
 * Risk Progression Chart
 *
 * Renders a stepped SVG line chart showing how a vehicle's cumulative quality
 * risk score changes after each station passage.
 *
 * Renders completed stations only — no future telemetry is projected.
 */

import type { VehicleGenealogyEvent } from "@/types/vehicle";

interface RiskProgressionChartProps {
  genealogy: VehicleGenealogyEvent[];
}

export function RiskProgressionChart({ genealogy }: RiskProgressionChartProps) {
  // Only include completed or in-progress events with risk data
  const points = genealogy.filter(
    (e) => e.processStatus === "COMPLETE" || e.processStatus === "IN_PROGRESS",
  );

  if (points.length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">
        No risk progression data available.
      </p>
    );
  }

  const W = 480;
  const H = 120;
  const PAD_L = 40;
  const PAD_R = 16;
  const PAD_T = 12;
  const PAD_B = 28;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const n = points.length;
  const maxRisk = 1.0;

  // Map each point to SVG coords (stepped: horizontal then vertical)
  const coords = points.map((e, i) => {
    const x = PAD_L + (i / Math.max(n - 1, 1)) * chartW;
    const y = PAD_T + (1 - e.qualityRiskAfterStation / maxRisk) * chartH;
    return { x, y, event: e };
  });

  // Build stepped polyline path
  let pathD = `M ${coords[0].x} ${coords[0].y}`;
  for (let i = 1; i < coords.length; i++) {
    // Step: go right to new x at old y, then drop to new y
    pathD += ` H ${coords[i].x} V ${coords[i].y}`;
  }

  // Risk color thresholds
  function dotColor(risk: number) {
    if (risk >= 0.5) return "#dc2626"; // red
    if (risk >= 0.2) return "#d97706"; // amber
    return "#059669"; // emerald
  }

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        aria-label="Risk progression chart"
        className="min-w-[320px]"
      >
        {/* Y-axis reference lines */}
        {[0, 0.25, 0.5, 0.75, 1.0].map((pct) => {
          const y = PAD_T + (1 - pct) * chartH;
          return (
            <g key={pct}>
              <line
                x1={PAD_L}
                y1={y}
                x2={W - PAD_R}
                y2={y}
                stroke="#e5e7eb"
                strokeWidth={1}
                strokeDasharray={pct === 0.5 ? "4 3" : "2 4"}
              />
              <text
                x={PAD_L - 4}
                y={y + 4}
                textAnchor="end"
                fontSize={9}
                fill="#9ca3af"
              >
                {(pct * 100).toFixed(0)}%
              </text>
            </g>
          );
        })}

        {/* High-risk threshold band */}
        <rect
          x={PAD_L}
          y={PAD_T}
          width={chartW}
          height={(1 - 0.5) * chartH}
          fill="#fef2f2"
          opacity={0.6}
        />

        {/* Stepped risk line */}
        <path
          d={pathD}
          fill="none"
          stroke={
            (coords[coords.length - 1]?.event.qualityRiskAfterStation ?? 0) >= 0.5
              ? "#dc2626"
              : (coords[coords.length - 1]?.event.qualityRiskAfterStation ?? 0) >= 0.2
              ? "#d97706"
              : "#059669"
          }
          strokeWidth={2}
          strokeLinejoin="round"
        />

        {/* Station dots */}
        {coords.map(({ x, y, event }, i) => (
          <g key={i}>
            <circle
              cx={x}
              cy={y}
              r={event.anomalyExposure ? 5 : 4}
              fill={dotColor(event.qualityRiskAfterStation)}
              stroke={event.anomalyExposure ? "#f59e0b" : "white"}
              strokeWidth={event.anomalyExposure ? 2 : 1.5}
            />
          </g>
        ))}

        {/* Station ID labels along x-axis */}
        {coords.map(({ x, event }, i) => (
          <text
            key={i}
            x={x}
            y={H - 4}
            textAnchor="middle"
            fontSize={8}
            fill="#6b7280"
          >
            {event.stationId}
          </text>
        ))}
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-600" />
          <span>Normal (&lt;20%)</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-amber-600" />
          <span>Watch (20–50%)</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-red-600" />
          <span>High Risk (≥50%)</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-white border-2 border-amber-500" />
          <span>Anomaly exposure</span>
        </div>
      </div>
    </div>
  );
}
