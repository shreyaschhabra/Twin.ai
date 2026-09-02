"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { X, LayoutDashboard, Network, Car, Bell, Activity, ShieldCheck, BarChart3, ClipboardCheck, BriefcaseBusiness, Calculator, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
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

interface MobileNavProps {
  isOpen: boolean;
  onClose: () => void;
}

export function MobileNav({ isOpen, onClose }: MobileNavProps) {
  const pathname = usePathname();
  const { orgRole } = useAuth();
  const role = orgRole as ClerkOrgRole | undefined;

  // Prevent background scrolling when mobile menu is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "unset";
    }
    return () => {
      document.body.style.overflow = "unset";
    };
  }, [isOpen]);

  // Automatically close mobile menu on route change
  useEffect(() => {
    onClose();
  }, [pathname, onClose]);

  if (!isOpen) return null;

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
    <div className="fixed inset-0 z-50 flex md:hidden select-none" role="dialog" aria-modal="true">
      {/* Backdrop overlay */}
      <div
        className="fixed inset-0 bg-background/80 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer content panel */}
      <div className="relative flex w-full max-w-xs flex-col bg-sidebar text-sidebar-foreground border-r p-4 shadow-xl animate-in slide-in-from-left duration-200">
        <div className="flex items-center justify-between border-b pb-4 mb-4">
          <div className="flex items-center gap-2 font-semibold">
            <span className="text-lg">Twin AI</span>
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-widest pt-[2px]">
              Operations
            </span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            aria-label="Close navigation menu"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Navigation links */}
        <nav className="flex-1 overflow-y-auto space-y-6">
          {filteredSections.map((section) => (
            <div key={section.title}>
              <h3 className="mb-2 px-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                {section.title}
              </h3>
              <ul className="space-y-1">
                {section.items.map((item) => {
                  // Nested route active state highlighting logic:
                  // "/app" must match exactly; other routes match exactly or as descendants
                  const isActive =
                    item.href === "/app"
                      ? pathname === item.href
                      : pathname === item.href || pathname.startsWith(item.href + "/");
                  const Icon = item.icon;

                  return (
                    <li key={item.name}>
                      <Link
                        href={item.href}
                        className={cn(
                          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                          isActive
                            ? "bg-sidebar-primary text-sidebar-primary-foreground"
                            : "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground text-muted-foreground"
                        )}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        <span>{item.name}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      </div>
    </div>
  );
}
