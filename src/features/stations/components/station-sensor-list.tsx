import { Cpu } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { SensorTrustBadge } from "@/features/trust/components/sensor-trust-badge";
import type { StationSensor } from "@/types/station";
import type { SensorMaturity } from "@/types/common";
import { cn } from "@/lib/utils";

interface StationSensorListProps {
  sensors: StationSensor[];
  maturity: SensorMaturity;
}

export function StationSensorList({ sensors, maturity }: StationSensorListProps) {
  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="pb-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <Cpu className="h-4 w-4 text-slate-500 shrink-0" />
              Telemetry &amp; Sensor Feeds
            </CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Direct cell sensors and computed proxy variables.
            </CardDescription>
          </div>
          {/* Sensor maturity badge */}
          <div className="flex items-center gap-1.5 font-mono text-[9px] border px-2 py-0.5 rounded bg-muted/20 self-start sm:self-center">
            <span className="text-muted-foreground">INSTRUMENTATION:</span>
            <span className={cn(
              "font-bold uppercase",
              maturity === "RICH" && "text-emerald-500",
              maturity === "PARTIAL" && "text-blue-500",
              maturity === "POOR" && "text-amber-500"
            )}>
              {maturity}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y border-t select-none">
          {sensors.map((sensor) => {
            const isUnknown = sensor.trustState === "UNKNOWN";
            const isInferred = sensor.trustState === "INFERRED";

            return (
              <li
                key={sensor.id}
                className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 p-4 hover:bg-muted/10 transition-colors"
              >
                {/* Channel details */}
                <div className="space-y-0.5 min-w-0">
                  <p className="text-sm font-semibold text-foreground truncate">
                    {sensor.name}
                  </p>
                  <p className="text-[10px] text-muted-foreground font-mono">
                    ID: {sensor.id}
                  </p>
                  {isInferred && (
                    <p className="text-[9px] text-blue-600/80 dark:text-blue-400/80 font-sans italic mt-1 leading-normal">
                      Estimated from validated station process context (indirect proxy)
                    </p>
                  )}
                  {isUnknown && (
                    <p className="text-[9px] text-amber-600/80 dark:text-amber-400/80 font-sans italic mt-1 leading-normal">
                      Telemetry warning: Signal offline. Lower direct measurement coverage.
                    </p>
                  )}
                </div>

                {/* Values & Trust Badge */}
                <div className="flex items-center gap-3 shrink-0 self-start sm:self-center">
                  <div className="text-right font-mono">
                    <span className="text-sm font-bold text-foreground">
                      {isUnknown || sensor.value === undefined ? "Unavailable" : sensor.value}
                    </span>
                    {!isUnknown && sensor.unit && (
                      <span className="text-xs text-muted-foreground ml-1">
                        {sensor.unit}
                      </span>
                    )}
                  </div>
                  <SensorTrustBadge trust={sensor.trustState} />
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
