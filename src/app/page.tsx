import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-6">
      <div className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight">Twin AI</h1>
        <p className="mt-3 text-lg text-muted-foreground">
          Predictive digital twin intelligence for industrial operations.
        </p>
      </div>

      <div className="flex gap-4">
        <Link
          href="/sign-in"
          className="inline-flex h-10 items-center justify-center rounded-md bg-foreground px-6 text-sm font-medium text-background transition-colors hover:opacity-90"
        >
          Sign In
        </Link>
        <Link
          href="/sign-up"
          className="inline-flex h-10 items-center justify-center rounded-md border px-6 text-sm font-medium transition-colors hover:bg-accent"
        >
          Create Account
        </Link>
      </div>
    </main>
  );
}
