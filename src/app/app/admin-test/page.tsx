/**
 * TEMPORARY — Phase 4 role authorization verification page.
 *
 * Purpose: Confirm that org:admin role enforcement works server-side.
 * This route is NOT part of the final Twin AI product.
 * Remove or repurpose in a later phase.
 *
 * Access policy:
 *   org:admin  → page renders
 *   org:member → redirected to /app
 *   unauthenticated → redirected to /sign-in
 */

import { requireOrganizationAdmin } from "@/lib/auth";

export default async function AdminTestPage() {
  // This throws a redirect if the user is not an org:admin.
  // The page content below only renders for verified admins.
  const { userId, orgId, orgRole } = await requireOrganizationAdmin();

  return (
    <main className="min-h-screen p-6 md:p-8">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-lg border p-6">
          <h1 className="text-xl font-semibold tracking-tight">
            Organization Admin Access Verified
          </h1>

          <p className="mt-2 text-sm text-muted-foreground">
            This page is only accessible to users with the{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
              org:admin
            </code>{" "}
            role.
          </p>

          <div className="mt-6 space-y-2 rounded-md border bg-muted/30 p-4 font-mono text-xs">
            <div>
              <span className="text-muted-foreground">userId: </span>
              {userId}
            </div>
            <div>
              <span className="text-muted-foreground">orgId: </span>
              {orgId}
            </div>
            <div>
              <span className="text-muted-foreground">orgRole: </span>
              {orgRole}
            </div>
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            ⚠ Temporary verification route — not part of the final product.
          </p>
        </div>
      </div>
    </main>
  );
}
