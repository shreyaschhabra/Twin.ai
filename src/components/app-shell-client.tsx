"use client";

import { useState } from "react";
import { AppSidebar } from "@/components/app-sidebar";
import { AppHeader } from "@/components/app-header";
import { MobileNav } from "@/components/mobile-nav";

interface AppShellClientProps {
  children: React.ReactNode;
}

export function AppShellClient({ children }: AppShellClientProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      {/* Permanent sidebar on desktop */}
      <AppSidebar
        isCollapsed={isCollapsed}
        onToggleCollapse={() => setIsCollapsed(!isCollapsed)}
        className="hidden md:flex shrink-0"
      />

      {/* Mobile navigation drawer */}
      <MobileNav
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main app region */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <AppHeader
          onOpenMobileMenu={() => setIsMobileMenuOpen(true)}
          className="shrink-0"
        />

        {/* Content canvas container */}
        <main className="flex-1 overflow-y-auto bg-muted/10 p-4 md:p-6 lg:p-8">
          <div className="mx-auto w-full max-w-[1600px] space-y-6">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
