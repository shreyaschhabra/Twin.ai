import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { AppShellClient } from "@/components/app-shell-client";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { userId, orgId } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  if (!orgId) {
    redirect("/organization");
  }

  return <AppShellClient>{children}</AppShellClient>;
}
