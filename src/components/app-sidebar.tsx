"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
  LayoutDashboard,
  Network,
  Car,
  Bell,
  Activity,
  ShieldCheck,
  BarChart3,
  ClipboardCheck,
  BriefcaseBusiness,
  Calculator,
  Settings,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { canAccessRoute } from "@/lib/auth/rbac";
import type { ClerkOrgRole } from "@/lib/auth/rbac";

interface SidebarItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

interface SidebarSection {
  title: string;
  items: SidebarItem[];
}

const SIDEBAR_SECTIONS: SidebarSection[] = [
  {
    title: "Operations",
    items: [
      { name: "Overview", href: "/app", icon: LayoutDashboard },
      { name: "Live Twin", href: "/app/live-twin", icon: Network },
      { name: "Vehicles", href: "/app/vehicles", icon: Car },
      { name: "Alerts", href: "/app/alerts", icon: Bell },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { name: "Flow Intelligence", href: "/app/flow", icon: Activity },
      { name: "Quality Intelligence", href: "/app/quality", icon: ShieldCheck },
    ],
  },
  {
    title: "Insights",
    items: [
      { name: "Analytics", href: "/app/analytics", icon: BarChart3 },
      { name: "Validation", href: "/app/validation", icon: ClipboardCheck },
    ],
  },
  {
    title: "Business",
    items: [
      { name: "Leadership", href: "/app/leadership", icon: BriefcaseBusiness },
      { name: "ROI", href: "/app/roi", icon: Calculator },
    ],
  },
  {
    title: "System",
    items: [
      { name: "Settings", href: "/app/settings", icon: Settings },
    ],
  },
];

interface AppSidebarProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  className?: string;
}

export function AppSidebar({
  isCollapsed,
  onToggleCollapse,
  className,
}: AppSidebarProps) {
  const pathname = usePathname();
  const { orgRole } = useAuth();
  const role = orgRole as ClerkOrgRole | undefined;

  // Filter sections and items based on the user's role in the active organization
  const filteredSections = SIDEBAR_SECTIONS.map((section) => {
    const filteredItems = section.items.filter((item) =>
      role ? canAccessRoute(role, item.href) : false
    );
    return {
      ...section,
      items: filteredItems,
    };
  }).filter((section) => section.items.length > 0);

  return (
    <aside
      className={cn(
        "flex flex-col border-r bg-sidebar text-sidebar-foreground transition-all duration-300 ease-in-out select-none",
        isCollapsed ? "w-16" : "w-64",
        className
      )}
    >
      {/* Brand Header */}
      <div className="flex h-14 items-center justify-between border-b px-4">
        <Link
          href="/app"
          className={cn(
            "flex items-center gap-2 font-semibold tracking-tight transition-opacity",
            isCollapsed ? "opacity-0 w-0 overflow-hidden" : "opacity-100"
          )}
        >
          <span className="text-lg">Twin AI</span>
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-widest self-end pb-[2px]">
            Operations
          </span>
        </Link>
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleCollapse}
          className="h-8 w-8 text-muted-foreground hover:text-foreground self-center mx-auto"
          aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </Button>
      </div>

      {/* Navigation list */}
      <nav className="flex-1 overflow-y-auto py-4 space-y-6 scrollbar-thin">
        {filteredSections.map((section) => (
          <div key={section.title} className="px-3">
            {/* Section label */}
            <h3
              className={cn(
                "mb-2 px-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider transition-opacity duration-200",
                isCollapsed ? "opacity-0 h-0 overflow-hidden mb-0" : "opacity-100"
              )}
            >
              {section.title}
            </h3>

            {/* Section items */}
            <ul className="space-y-1">
              {section.items.map((item) => {
                // Nested route active state highlighting logic:
                // "/app" must match exactly; other routes match exactly or as descendants (e.g. /app/live-twin/stations/S18 triggers Live Twin active state)
                const isActive =
                  item.href === "/app"
                    ? pathname === item.href
                    : pathname === item.href || pathname.startsWith(item.href + "/");
                const Icon = item.icon;

                return (
                  <li key={item.name}>
                    <Link
                      href={item.href}
                      title={isCollapsed ? item.name : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                        isActive
                          ? "bg-sidebar-primary text-sidebar-primary-foreground"
                          : "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground text-muted-foreground",
                        isCollapsed ? "justify-center" : "justify-start"
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      {!isCollapsed && (
                        <span className="truncate">{item.name}</span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
