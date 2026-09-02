"use client";

import { usePathname } from "next/navigation";
import { UserButton, OrganizationSwitcher } from "@clerk/nextjs";
import { Menu } from "lucide-react";
import { cn } from "@/lib/utils";
import { appConfig } from "@/config/app";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface AppHeaderProps {
  onOpenMobileMenu: () => void;
  className?: string;
}

const ROUTE_LABELS: Record<string, string> = {
  "/app": "Overview",
  "/app/live-twin": "Live Twin",
  "/app/vehicles": "Vehicles",
  "/app/alerts": "Alerts",
  "/app/flow": "Flow Intelligence",
  "/app/quality": "Quality Intelligence",
  "/app/analytics": "Analytics",
  "/app/validation": "Validation",
  "/app/leadership": "Leadership",
  "/app/roi": "ROI",
  "/app/settings": "Settings",
  "/app/settings/organization": "Organization Settings",
};

export function AppHeader({ onOpenMobileMenu, className }: AppHeaderProps) {
  const pathname = usePathname();

  // Find the exact or parent label
  let breadcrumbLabel = "Twin AI";
  if (ROUTE_LABELS[pathname]) {
    breadcrumbLabel = ROUTE_LABELS[pathname];
  } else {
    // Fallback search (e.g. for dynamic nested routes)
    const matchingKey = Object.keys(ROUTE_LABELS)
      .sort((a, b) => b.length - a.length)
      .find((key) => pathname.startsWith(key));
    if (matchingKey) {
      breadcrumbLabel = ROUTE_LABELS[matchingKey];
    }
  }

  return (
    <header className={cn("flex h-14 items-center justify-between border-b bg-background px-4 select-none", className)}>
      {/* Left: Hamburger (mobile) + Breadcrumb */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenMobileMenu}
          className="md:hidden h-8 w-8 text-muted-foreground hover:text-foreground"
          aria-label="Open navigation menu"
        >
          <Menu className="h-4 w-4" />
        </Button>

        {/* Path Breadcrumb display */}
        <div className="flex items-center gap-2 text-sm font-medium">
          <span className="text-muted-foreground">Twin AI</span>
          <span className="text-muted-foreground/60 select-none">/</span>
          <span className="text-foreground tracking-tight">{breadcrumbLabel}</span>
        </div>
      </div>

      {/* Right: Controls & Profile */}
      <div className="flex items-center gap-4">
        {/* Mock/Demo indicator */}
        {appConfig.useMockData && (
          <Badge
            variant="outline"
            className="hidden sm:inline-flex bg-amber-50/20 text-amber-700 dark:text-amber-400 border-amber-500/20 dark:border-amber-400/20 font-mono text-[10px] tracking-wider uppercase px-2 py-0.5"
          >
            Demo Data Mode
          </Badge>
        )}

        {/* Desktop Divider */}
        <div className="hidden md:block h-4 w-[1px] bg-border" />

        {/* Clerk Switchers */}
        <div className="flex items-center gap-3">
          <OrganizationSwitcher
            hidePersonal
            afterSelectOrganizationUrl="/app"
            afterCreateOrganizationUrl="/app"
            appearance={{
              elements: {
                rootBox: "h-8 flex items-center justify-center max-w-[180px] sm:max-w-none",
                organizationSwitcherTrigger:
                  "h-8 px-2 py-1.5 border rounded-md hover:bg-accent text-sm text-foreground transition-colors",
              },
            }}
          />
          <UserButton
            appearance={{
              elements: {
                avatarBox: "h-8 w-8 border",
              },
            }}
          />
        </div>
      </div>
    </header>
  );
}
