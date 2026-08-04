"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useAuthStore } from "@/stores/auth";
import { useRedirectWhenAuthenticated } from "@/hooks/use-redirect-when-authenticated";
import {
  mapRegisterError,
  validateEmail,
  validatePassword,
} from "@/lib/auth-forms";
import { isDemoAccessPublished } from "@/lib/demo";
import { DemoCredentials } from "@/components/demo-credentials";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-full flex-1 items-center justify-center px-6 py-12">
      <div className="w-full max-w-[26rem]">
        <p className="font-mono text-meta uppercase text-ink-2">Nexus</p>
        {children}
      </div>
    </main>
  );
}

export default function RegisterPage() {
  const router = useRouter();
  const register = useAuthStore((s) => s.register);
  // Already-authenticated visitors are sent to / (loading-gated); see the hook.
  const redirecting = useRedirectWhenAuthenticated();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    // Client-side gate first, so a bad input never spends a rate-limited attempt.
    const validationError = validateEmail(email) ?? validatePassword(password);
    if (validationError) {
      setError(validationError);
      return;
    }

    setSubmitting(true);
    try {
      // register() creates the account then logs in; success lands authenticated.
      await register(email, password);
      router.push("/");
    } catch (err) {
      setError(mapRegisterError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (redirecting) {
    return (
      <div className="flex min-h-full flex-1 items-center justify-center p-4 text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  // When this build publishes demo credentials, registration is closed and this
  // form would 403 on every submit. Rendering it anyway — subordinate to a panel
  // saying "use these instead" — is a confusing hierarchy and a small trap, so
  // the page becomes the redirect it should be. Nobody arrives here by clicking
  // (/login hides the link on this same guard); this is the direct-URL path.
  if (isDemoAccessPublished()) {
    return (
      <PageShell>
        <h1 className="mt-3 text-title text-balance">
          Registration is closed on this demo
        </h1>
        <p className="mt-3 text-sm text-ink-2">
          This deployment runs on a single shared account. Use the credentials
          below — its document corpus is already loaded.
        </p>
        <div className="mt-8">
          <DemoCredentials />
        </div>
        <Link
          href="/login"
          className="mt-5 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          Go to sign in →
        </Link>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <h1 className="mt-3 text-display text-balance">
        Build a corpus worth asking.
      </h1>
      <p className="mt-3 text-sm text-ink-2">
        Upload your documents, then ask questions that get answered from them.
      </p>

      <Card className="mt-8">
        <CardContent className="flex flex-col gap-5">
          <h2 className="text-section">Create account</h2>
          <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
                required
              />
              <p className="text-meta text-ink-2">8–72 characters.</p>
            </div>
            <Button
              type="submit"
              size="lg"
              className="mt-1 w-full"
              disabled={submitting}
            >
              {submitting ? "Creating account…" : "Create account"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <p className="mt-5 text-sm text-ink-2">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          Sign in
        </Link>
      </p>
    </PageShell>
  );
}
