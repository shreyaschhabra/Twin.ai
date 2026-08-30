/**
 * Leadership Loading Page
 *
 * Skeletons representing page layout for Phase 16 Leadership dashboard.
 */

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardHeader, CardContent } from "@/components/ui/card";

export default function LeadershipLoading() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="border-b pb-4 space-y-2">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-96" />
      </div>

      {/* KPI Cards */}
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

      {/* Value Areas */}
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i} className="border shadow-none">
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-3 w-36 mt-2" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Details Grid */}
      <div className="grid gap-6 md:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i} className="border shadow-none">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-40" />
            </CardHeader>
            <CardContent className="pt-6">
              <Skeleton className="h-32 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
