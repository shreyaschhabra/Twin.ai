/**
 * Quality Risk Progression Chart
 *
 * Stepped SVG line chart showing how a vehicle's quality risk accumulated
 * across the stations it has visited.
 */

import type { QualityRiskPoint } from "@/types/quality";
import { cn } from "@/lib/utils";

interface RiskProgressionChartProps {
  riskHistory: QualityRiskPoint[];
  exposureCohortStationId?: string;
}

export function RiskProgressionChart({
  riskHistory,
  exposureCohortStationId,
}: RiskProgressionChartProps) {
  if (!riskHistory || riskHistory.length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic py-4">
        No risk history points recorded for this assembly.
      </p>
    );
  }

  const W = 500;
  const H = 140;
  const PAD_L = 40;
  const PAD_R = 16;
  const PAD_T = 12;
  const PAD_B = 28;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const n = riskHistory.length;
  const maxRisk = 1.0;

  // Map points to SVG coords
  const coords = riskHistory.map((p, i) => {
    const x = PAD_L + (i / Math.max(n - 1, 1)) * chartW;
    const y = PAD_T + (1 - p.risk / maxRisk) * chartH;
    return { x, y, point: p };
  });

  // Build stepped polyline path
  let pathD = `M ${coords[0].x} ${coords[0].y}`;
  for (let i = 1; i < coords.length; i++) {
    // Step: horizontal then vertical
    pathD += ` H ${coords[i].x} V ${coords[i].y}`;
  }

  function dotColor(risk: number) {
    if (risk >= 0.5) return "#b91c1c"; // red-700
    if (risk >= 0.2) return "#b45309"; // amber-700
    return "#047857"; // emerald-700
  }

  const lastPoint = coords[coords.length - 1]?.point;
  const lastRisk = lastPoint?.risk ?? 0;

  return (
    <div className="w-full">
      <div className="overflow-x-auto select-none">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          className="min-w-[350px]"
          aria-label="Quality risk progression chart"
        >
          {/* Y-Axis Grid Lines */}
          {[0, 0.25, 0.5, 0.75, 1.0].map((val) => {
            const y = PAD_T + (1 - val) * chartH;
            return (
              <g key={val}>
                <line
                  x1={PAD_L}
                  y1={y}
                  x2={W - PAD_R}
                  y2={y}
                  stroke="#e2e8f0"
                  strokeWidth={1}
                  strokeDasharray={val === 0.5 ? "3 3" : "1 4"}
                />
                <text
                  x={PAD_L - 6}
                  y={y + 3}
                  textAnchor="end"
                  fontSize={8}
                  fill="#94a3b8"
                  className="font-mono"
                >
                  {Math.round(val * 100)}%
                </text>
              </g>
            );
          })}

          {/* Stepped line path */}
          <path
            d={pathD}
            fill="none"
            stroke={lastRisk >= 0.5 ? "#ef4444" : lastRisk >= 0.2 ? "#f59e0b" : "#10b981"}
            strokeWidth={2}
            strokeLinejoin="round"
          />

          {/* Station markers */}
          {coords.map(({ x, y, point }, i) => {
            const isExposed = point.stationId === exposureCohortStationId;
            return (
              <g key={i}>
                <circle
                  cx={x}
                  cy={y}
                  r={isExposed ? 5 : 4}
                  fill={dotColor(point.risk)}
                  stroke={isExposed ? "#d97706" : "white"}
                  strokeWidth={isExposed ? 2.5 : 1.5}
                />
                <text
                  x={x}
                  y={H - 6}
                  textAnchor="middle"
                  fontSize={8}
                  fill="#64748b"
                  className="font-mono"
                >
                  {point.stationId}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-700" />
          <span>Low Risk (&lt;20%)</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-amber-700" />
          <span>Watch (20% – 50%)</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-red-700" />
          <span>High Risk (≥50%)</span>
        </div>
        {exposureCohortStationId && (
          <div className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-white border-2 border-amber-600" />
            <span className="font-semibold text-amber-700">Anomaly Station ({exposureCohortStationId})</span>
          </div>
        )}
      </div>
    </div>
  );
}
