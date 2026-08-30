import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse select-none">
      {/* Header Skeleton */}
      <div className="flex flex-col gap-3 border-b pb-4">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-4 w-72" />
      </div>

      {/* Operational summaries row */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        {Array.from({ length: 6 }).map((_, idx) => (
          <div key={idx} className="p-4 border rounded">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-5 w-20 mt-2" />
          </div>
        ))}
      </div>

      {/* Main Canvas split grids */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          {/* Flow card skeleton */}
          <div className="p-4 border rounded h-60 space-y-4">
            <Skeleton className="h-5 w-40 border-b pb-2" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>

          {/* Buffers skeleton */}
          <div className="p-4 border rounded h-72 space-y-4">
            <Skeleton className="h-5 w-36 border-b pb-2" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        </div>

        <div className="space-y-6">
          {/* Telemetry skeleton */}
          <div className="p-4 border rounded h-[360px] space-y-4">
            <Skeleton className="h-5 w-48 border-b pb-2" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
