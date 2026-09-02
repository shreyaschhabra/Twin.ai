import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { OrganizationList } from "@clerk/nextjs";

/**
 * Organization selection / creation page.
 *
 * Access rules:
 *   - Unauthenticated → /sign-in
 *   - Authenticated + already has active org → /app (skip this step)
 *   - Authenticated + no org → render OrganizationList
 */
export default async function OrganizationPage() {
  const { userId, orgId } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  // User is authenticated and already has an active organization — nothing
  // to do here; send them straight into the app.
  if (orgId) {
    redirect("/app");
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="flex flex-col items-center gap-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Twin AI</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Select or create your company workspace to continue.
          </p>
        </div>

        <OrganizationList
          hidePersonal
          afterCreateOrganizationUrl="/app"
          afterSelectOrganizationUrl="/app"
        />
      </div>
    </main>
  );
}
