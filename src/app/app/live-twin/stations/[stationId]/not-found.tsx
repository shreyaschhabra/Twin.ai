import Link from "next/link";
import { ArrowLeft, AlertCircle } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[50vh] text-center p-6 space-y-4 select-none">
      <AlertCircle className="h-10 w-10 text-rose-500" />
      <div className="space-y-2">
        <h2 className="text-xl font-bold tracking-tight text-foreground">
          Station not found
        </h2>
        <p className="text-sm text-muted-foreground max-w-sm">
          The requested station does not exist in the current line configuration.
        </p>
      </div>
      <Link
        href="/app/live-twin"
        className="inline-flex h-9 items-center gap-1.5 rounded-md border bg-background px-4 text-xs font-semibold text-foreground hover:bg-accent transition-colors mt-2"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Live Twin
      </Link>
    </div>
  );
}
