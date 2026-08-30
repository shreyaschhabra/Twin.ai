import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse select-none">
      {/* Header Skeleton */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b pb-4">
        <div className="space-y-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-6 w-24" />
        </div>
      </div>

      {/* Summary KPI skeletons */}
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-4 border p-4 rounded bg-card">
        {Array.from({ length: 8 }).map((_, idx) => (
          <div key={idx} className="flex flex-col items-center gap-2 p-2 border rounded">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-5 w-8" />
          </div>
        ))}
      </div>

      {/* Main Canvas skeleton split */}
      <div className="grid gap-6 lg:grid-cols-4">
        {/* Left zones stack (cols-3) */}
        <div className="lg:col-span-3 space-y-6">
          <div className="flex items-center gap-2 border-b pb-4">
            <Skeleton className="h-7 w-48" />
          </div>

          {/* Skeletons for 3 mock zones */}
          {Array.from({ length: 3 }).map((_, zoneIdx) => (
            <div key={zoneIdx} className="p-4 border rounded bg-card space-y-4">
              <div className="flex items-center justify-between border-b pb-2">
                <Skeleton className="h-4 w-36" />
              </div>
              <div className="flex items-center gap-4 py-2">
                {Array.from({ length: 4 }).map((_, nodeIdx) => (
                  <div key={nodeIdx} className="flex items-center gap-3 shrink-0">
                    <Skeleton className="h-20 w-32 rounded" />
                    {nodeIdx < 3 && <Skeleton className="h-4 w-6" />}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Right side diagnostics (col-1) */}
        <div className="space-y-6">
          <div className="p-4 border rounded bg-card h-80 space-y-4">
            <Skeleton className="h-5 w-32 border-b pb-2" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
          <div className="p-4 border rounded bg-card h-40 space-y-4">
            <Skeleton className="h-5 w-24 border-b pb-2" />
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
