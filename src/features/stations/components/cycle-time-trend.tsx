import { TrendingUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import type { StationProcessTrend } from "@/types/station";

interface CycleTimeTrendProps {
  trend: StationProcessTrend | null;
  baseline: number;
}

export function CycleTimeTrend({ trend, baseline }: CycleTimeTrendProps) {
  if (!trend || !trend.cycleTimeHistory || trend.cycleTimeHistory.length === 0) {
    return (
      <Card className="border bg-card text-card-foreground shadow-sm">
        <CardContent className="p-8 text-center text-xs text-muted-foreground font-mono">
          No cycle-time history data available.
        </CardContent>
      </Card>
    );
  }

  const { cycleTimeHistory } = trend;

  // SVG dimensions
  const width = 500;
  const height = 150;
  const paddingLeft = 40;
  const paddingRight = 40;
  const paddingTop = 20;
  const paddingBottom = 20;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  // Find min/max for Y scaling
  const allYValues = [...cycleTimeHistory, baseline];
  const maxVal = Math.max(...allYValues) + 2;
  const minVal = Math.max(0, Math.min(...allYValues) - 2);
  const valRange = maxVal - minVal || 1;

  // Map values to coordinates
  const points = cycleTimeHistory.map((val, idx) => {
    const x = paddingLeft + (idx / (cycleTimeHistory.length - 1)) * chartWidth;
    const y = height - paddingBottom - ((val - minVal) / valRange) * chartHeight;
    return { x, y, val };
  });

  // Map baseline to Y
  const baselineY = height - paddingBottom - ((baseline - minVal) / valRange) * chartHeight;

  // Create SVG path string
  const pathData = points
    .map((p, idx) => `${idx === 0 ? "M" : "L"} ${p.x} ${p.y}`)
    .join(" ");

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-slate-500 shrink-0" />
          Cycle-Time Trend — Recent Cycles
        </CardTitle>
        <CardDescription className="text-xs text-muted-foreground">
          Observed cycle-time durations in seconds against baseline targets.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-2 select-none">
        <div className="relative w-full h-[150px]">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            width="100%"
            height="100%"
            className="overflow-visible"
            aria-hidden="true"
          >
            {/* Dashed Baseline Reference line */}
            <line
              x1={paddingLeft}
              y1={baselineY}
              x2={width - paddingRight}
              y2={baselineY}
              className="stroke-slate-400 dark:stroke-slate-600 stroke-[1.5]"
              strokeDasharray="4 4"
            />
            {/* Baseline text indicator */}
            <text
              x={width - paddingRight + 5}
              y={baselineY + 4}
              className="text-[9px] font-mono fill-muted-foreground text-left"
            >
              {baseline}s (Target)
            </text>

            {/* Sparkline Path */}
            <path
              d={pathData}
              fill="none"
              className="stroke-sky-500 dark:stroke-sky-400 stroke-2"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Nodes and Labels */}
            {points.map((p, idx) => (
              <g key={idx}>
                {/* Node dot */}
                <circle
                  cx={p.x}
                  cy={p.y}
                  r="4"
                  className="fill-sky-500 stroke-background stroke-2 dark:fill-sky-400"
                />
                {/* Value label */}
                <text
                  x={p.x}
                  y={p.y - 8}
                  className="text-[9px] font-mono font-bold fill-foreground text-center"
                  textAnchor="middle"
                >
                  {p.val}s
                </text>
                {/* Cycles axis label */}
                <text
                  x={p.x}
                  y={height - 2}
                  className="text-[8px] font-mono fill-muted-foreground text-center"
                  textAnchor="middle"
                >
                  -{cycleTimeHistory.length - 1 - idx}
                </text>
              </g>
            ))}
          </svg>
        </div>
      </CardContent>
    </Card>
  );
}
