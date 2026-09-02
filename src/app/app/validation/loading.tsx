/**
 * Model Validation Loading Page
 *
 * Skeletons representing page layout for Phase 15 Model Validation dashboard.
 */

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardHeader, CardContent } from "@/components/ui/card";

export default function ValidationLoading() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="border-b pb-4 space-y-2">
        <Skeleton className="h-6 w-36" />
        <Skeleton className="h-4 w-96" />
      </div>

      {/* Tabs Selector */}
      <div className="flex gap-4 border-b pb-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-5 w-24" />
        ))}
      </div>

      {/* Status Bar */}
      <Skeleton className="h-16 w-full rounded-lg" />

      {/* Grid Cards Row */}
      <div className="grid gap-6 md:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i} className="border shadow-none">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-40" />
            </CardHeader>
            <CardContent className="pt-6 space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Details Row */}
      <Card className="border shadow-none">
        <CardHeader className="pb-3 border-b">
          <Skeleton className="h-5 w-32" />
        </CardHeader>
        <CardContent className="pt-6 space-y-4">
          <Skeleton className="h-40 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
