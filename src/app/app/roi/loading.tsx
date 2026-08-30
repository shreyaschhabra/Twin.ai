/**
 * ROI Calculator Loading Page
 *
 * Skeletons representing page layout for Phase 17 Interactive ROI Calculator dashboard.
 */

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardHeader, CardContent } from "@/components/ui/card";

export default function RoiLoading() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="border-b pb-4 space-y-2">
        <Skeleton className="h-6 w-36" />
        <Skeleton className="h-4 w-96" />
      </div>

      {/* Preset Buttons */}
      <div className="flex gap-4 bg-slate-50 border rounded-lg p-3">
        <Skeleton className="h-4 w-28" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-20" />
        ))}
      </div>

      {/* Layout workspace */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Inputs skeleton */}
        <Card className="border shadow-none">
          <CardHeader className="pb-3 border-b">
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent className="pt-6 space-y-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>

        {/* Outcomes skeleton */}
        <Card className="border shadow-none bg-slate-50/50">
          <CardHeader className="pb-3 border-b">
            <Skeleton className="h-5 w-48" />
          </CardHeader>
          <CardContent className="pt-6 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
