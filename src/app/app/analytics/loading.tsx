/**
 * Plant Analytics Loading Page
 *
 * Skeletons representing page layout for Phase 14 Plant Manager Analytics dashboard.
 */

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardHeader, CardContent } from "@/components/ui/card";

export default function AnalyticsLoading() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="border-b pb-4 space-y-2">
        <Skeleton className="h-6 w-36" />
        <Skeleton className="h-4 w-96" />
      </div>

      {/* Time Range Selector */}
      <div className="flex items-center gap-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-36" />
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="border shadow-none">
            <CardHeader className="pb-1 pt-4 px-4">
              <Skeleton className="h-3 w-16" />
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <Skeleton className="h-6 w-12 mt-1" />
              <Skeleton className="h-3 w-20 mt-1" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Trends Row */}
      <div className="grid gap-6 md:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i} className="border shadow-none">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-32" />
            </CardHeader>
            <CardContent className="pt-6">
              <Skeleton className="h-40 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Hotspots Row */}
      <div className="grid gap-6 md:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i} className="border shadow-none">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-48" />
            </CardHeader>
            <CardContent className="pt-6">
              <Skeleton className="h-32 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Shift Table Skeleton */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b">
          <Skeleton className="h-5 w-36" />
        </CardHeader>
        <CardContent className="pt-6">
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
