/**
 * Quality Intelligence Loading Page
 *
 * Skeletons representing page layout for Phase 12 Quality Intelligence dashboard.
 */

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardHeader, CardContent } from "@/components/ui/card";

export default function QualityLoading() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="border-b pb-4 space-y-2">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-96" />
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="border shadow-none">
            <CardHeader className="pb-1 pt-4 px-4">
              <Skeleton className="h-3.5 w-24" />
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <Skeleton className="h-8 w-16 mt-1" />
              <Skeleton className="h-3 w-28 mt-1" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Highest Priority Warning Card */}
      <Card className="border border-muted shadow-none">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-64" />
          <Skeleton className="h-4 w-96 mt-1" />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-8 w-24" />
              </div>
            ))}
          </div>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>

      {/* Dashboard container skeleton (Table + Detail Side-by-Side) */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Table skeleton */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex gap-3">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-8 w-32" />
          </div>
          <Card className="border shadow-none">
            <CardContent className="p-0">
              <div className="space-y-2 p-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Selected vehicle details panel skeleton */}
        <div className="lg:col-span-1">
          <Card className="border shadow-none h-full">
            <CardContent className="space-y-4 pt-6">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-20 w-full" />
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Exposure cohorts skeleton */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-6 md:grid-cols-3">
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
            <div className="md:col-span-2">
              <Skeleton className="h-36 w-full" />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
