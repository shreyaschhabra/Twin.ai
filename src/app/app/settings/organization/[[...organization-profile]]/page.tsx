import { OrganizationProfile } from "@clerk/nextjs";

export default function OrganizationSettingsPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <OrganizationProfile routing="path" path="/app/settings/organization" />
    </main>
  );
}
