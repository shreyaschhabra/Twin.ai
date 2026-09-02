import Link from "next/link";
import { FeaturePlaceholder } from "@/components/app-shell/feature-placeholder";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <FeaturePlaceholder
        title="Settings"
        description="Application preferences, user profile settings, and tenant organization controls."
      />

      <div className="grid gap-6 md:grid-cols-3">
        {/* Profile Card */}
        <Card className="flex flex-col justify-between border bg-card text-card-foreground">
          <CardHeader>
            <CardTitle className="text-base font-semibold">User Profile</CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Manage your personal credentials and alert preferences.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <span className="text-xs text-muted-foreground font-mono">
              [ Managed by Clerk User Profile ]
            </span>
          </CardContent>
        </Card>

        {/* Organization Card */}
        <Card className="flex flex-col justify-between border bg-card text-card-foreground">
          <CardHeader>
            <CardTitle className="text-base font-semibold">Organization / Company</CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Manage members, invite teammates, and modify company settings.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0 flex flex-col gap-3">
            <Link
              href="/app/settings/organization"
              className="inline-flex h-8 items-center justify-center rounded-md border bg-background px-3 text-xs font-medium text-foreground hover:bg-accent transition-colors self-start"
            >
              Manage Organization
            </Link>
          </CardContent>
        </Card>

        {/* Application Card */}
        <Card className="flex flex-col justify-between border bg-card text-card-foreground">
          <CardHeader>
            <CardTitle className="text-base font-semibold">Application Parameters</CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Configure baseline cycle times, custom alert thresholds, and system settings.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <span className="text-xs text-muted-foreground font-mono">
              [ Factory Parameters - Read Only ]
            </span>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
