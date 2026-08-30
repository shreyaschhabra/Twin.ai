/**
 * Server-side authorization utilities for Twin AI.
 *
 * All functions use Clerk's `auth()` which runs exclusively on the server.
 * Never call these helpers from client components.
 *
 * Roles in use:
 *   org:admin  — company administrator
 *   org:member — standard company user
 *
 * Future resources (factories, stations, alerts, vehicles, simulations)
 * will each carry an organization_id that must be compared against the
 * orgId returned here.  See docs/architecture.md for the tenancy invariant.
 */

import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

// ─── Types ────────────────────────────────────────────────────────────────────

export type OrganizationContext = {
  userId: string;
  orgId: string;
  orgRole: string;
};

// ─── requireUser ──────────────────────────────────────────────────────────────

/**
 * Asserts the request comes from an authenticated Clerk user.
 * Redirects to /sign-in if not.
 *
 * @returns The authenticated userId.
 */
export async function requireUser(): Promise<string> {
  const { userId } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  return userId;
}

// ─── requireOrganization ──────────────────────────────────────────────────────

/**
 * Asserts the request comes from an authenticated user who has an active
 * Clerk Organization selected.  Redirects appropriately if either condition
 * is not met.
 *
 * The returned `orgId` is the authoritative tenant identifier that all future
 * Twin AI resources (factories, alerts, simulations, etc.) will store.
 *
 * @returns Trusted `{ userId, orgId, orgRole }` from Clerk — never from the client.
 */
export async function requireOrganization(): Promise<OrganizationContext> {
  const { userId, orgId, orgRole } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  if (!orgId) {
    redirect("/organization");
  }

  return {
    userId,
    orgId,
    orgRole: orgRole ?? "org:member",
  };
}

// ─── requireOrganizationAdmin ─────────────────────────────────────────────────

/**
 * Asserts the request comes from an authenticated user who:
 *   1. Has an active organization.
 *   2. Holds the `org:admin` role within that organization.
 *
 * Non-admin org members receive a 403-equivalent redirect to /app.
 * Unauthenticated users are redirected to /sign-in.
 *
 * @returns Trusted `{ userId, orgId, orgRole }` — all from Clerk session claims.
 */
export async function requireOrganizationAdmin(): Promise<OrganizationContext> {
  const { userId, orgId, orgRole, has } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  if (!orgId) {
    redirect("/organization");
  }

  // Use Clerk's has() to check the role from session claims.
  // This is safer than a raw string comparison because Clerk validates the claim.
  const isAdmin = has({ role: "org:admin" });

  if (!isAdmin) {
    redirect("/app");
  }

  return {
    userId,
    orgId,
    orgRole: orgRole ?? "org:member",
  };
}
