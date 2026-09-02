import Link from "next/link";
import { Bell } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Alert } from "@/types/alert";
import { cn } from "@/lib/utils";

interface ActiveAlertsListProps {
  alerts: Alert[];
}

export function ActiveAlertsList({ alerts }: ActiveAlertsListProps) {
  // Sort by timestamp descending
  const recentAlerts = [...alerts]
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, 4);

  return (
    <Card className="border bg-card text-card-foreground shadow-sm">
      <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4">
        <div>
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <Bell className="h-4 w-4 text-rose-500 shrink-0" />
            Active Alerts Feed
          </CardTitle>
          <CardDescription className="text-xs text-muted-foreground">
            Top unacknowledged and warning/critical indicators on the floor.
          </CardDescription>
        </div>
        <Link
          href="/app/alerts"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-3 text-xs font-medium text-foreground hover:bg-accent transition-colors self-start sm:self-center"
        >
          View All Alerts
        </Link>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y border-t select-none">
          {recentAlerts.length === 0 ? (
            <li className="p-6 text-center text-xs text-muted-foreground font-mono">
              No active operational alerts.
            </li>
          ) : (
            recentAlerts.map((alert) => {
              const severityStyles = {
                CRITICAL: "bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20",
                WARNING: "bg-orange-500/10 text-orange-700 dark:text-orange-400 border-orange-500/20",
                WATCH: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20",
                INFO: "bg-slate-500/10 text-slate-700 dark:text-slate-400 border-slate-500/20",
              };

              const alertAgeMin = Math.round(
                (new Date("2026-08-30T10:55:00Z").getTime() - new Date(alert.timestamp).getTime()) / 60000
              );

              return (
                <li
                  key={alert.id}
                  className="flex items-start gap-4 p-4 hover:bg-muted/10 transition-colors"
                >
                  {/* Severity badge */}
                  <Badge
                    variant="outline"
                    className={cn(
                      "font-mono text-[9px] tracking-wider uppercase px-2 py-0.5 mt-0.5 shrink-0",
                      severityStyles[alert.severity]
                    )}
                  >
                    {alert.severity}
                  </Badge>

                  {/* Body info */}
                  <div className="flex-1 space-y-1 min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate">
                      {alert.title}
                    </p>
                    <p className="text-xs text-muted-foreground line-clamp-1">
                      {alert.description}
                    </p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground font-mono pt-1">
                      <span className="bg-muted px-1.5 py-0.5 rounded font-sans uppercase">
                        {alert.kind}
                      </span>
                      {alert.stationId && <span>STATION: {alert.stationId}</span>}
                      {alert.vehicleId && <span>VEHICLE: {alert.vehicleId}</span>}
                    </div>
                  </div>

                  {/* Age timestamp */}
                  <span className="text-[10px] text-muted-foreground font-mono whitespace-nowrap self-start mt-1">
                    {alertAgeMin <= 0 ? "Just now" : `${alertAgeMin}m ago`}
                  </span>
                </li>
              );
            })
          )}
        </ul>
      </CardContent>
    </Card>
  );
}
