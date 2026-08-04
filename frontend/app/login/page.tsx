"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useAuthStore } from "@/stores/auth";
import { useRedirectWhenAuthenticated } from "@/hooks/use-redirect-when-authenticated";
import { mapAuthError, validateEmail, validatePassword } from "@/lib/auth-forms";
import { isDemoAccessPublished } from "@/lib/demo";
import { DemoCredentials } from "@/components/demo-credentials";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

export default function LoginPage() {
  const router = useRouter();
  const login = useAuthStore((s) => s.login);
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
      await login(email, password);
      router.push("/");
    } catch (err) {
      setError(mapAuthError(err));
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

  return (
    <main className="flex min-h-full flex-1 items-center justify-center px-6 py-12">
      <div className="w-full max-w-[26rem]">
        <p className="font-mono text-meta uppercase text-ink-2">Nexus</p>
        <h1 className="mt-3 text-display text-balance">
          Answers grounded in your own documents.
        </h1>
        <p className="mt-3 text-sm text-ink-2">
          Every answer cites the passages it came from — and says so when nothing
          in your corpus supports one.
        </p>

        {/* The way in, before the wall. Renders nothing unless this build
            publishes credentials, so local dev shows the form alone. */}
        <div className="mt-8 empty:hidden">
          <DemoCredentials />
        </div>

        <Card className="mt-4">
          <CardContent className="flex flex-col gap-5">
            <h2 className="text-section">Sign in</h2>
            <form
              onSubmit={onSubmit}
              noValidate
              className="flex flex-col gap-4"
            >
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
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>
              <Button
                type="submit"
                size="lg"
                className="mt-1 w-full"
                disabled={submitting}
              >
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Hidden on the exact condition that publishes the demo panel: with a
            shared account and REGISTRATION_ENABLED=false, "Create one" is a
            dead end. Same imported guard the panel uses — never re-derived. */}
        {!isDemoAccessPublished() && (
          <p className="mt-5 text-sm text-ink-2">
            Don&apos;t have an account?{" "}
            <Link
              href="/register"
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              Create one
            </Link>
          </p>
        )}
      </div>
    </main>
  );
}
