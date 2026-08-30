import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";

interface FeaturePlaceholderProps {
  title: string;
  description: string;
  statusText?: string;
  statusVariant?: "default" | "secondary" | "outline" | "destructive";
  children?: ReactNode;
}

/**
 * FeaturePlaceholder component.
 * Renders a highly professional, information-dense industrial dashboard placeholder.
 * Avoids consumer "coming soon" aesthetic.
 */
export function FeaturePlaceholder({
  title,
  description,
  statusText = "Pipeline Invariant Active",
  statusVariant = "outline",
  children,
}: FeaturePlaceholderProps) {
  return (
    <div className="flex flex-col gap-6 rounded-md border bg-card p-6 text-card-foreground shadow-sm">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between md:gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">{description}</p>
        </div>
        <div className="self-start md:self-center">
          <Badge variant={statusVariant} className="font-mono text-xs uppercase tracking-wider">
            {statusText}
          </Badge>
        </div>
      </div>

      <div className="border-t pt-4">
        <div className="rounded border border-dashed bg-muted/20 p-8 text-center text-sm text-muted-foreground font-mono">
          [ {title} telemetry visualization zone — data bindings ready ]
        </div>
      </div>

      {children && <div className="mt-2">{children}</div>}
    </div>
  );
}
