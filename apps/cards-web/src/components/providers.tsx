"use client";

import { type ReactNode } from "react";
import { AuthProvider, type AuthSnapshot } from "@/hooks/useAuth";
import { SignInMethodsProvider } from "@/hooks/useSignInMethods";
import { LINKEDIN_ONLY, type SignInMethods } from "@/lib/auth/providers";

export function Providers({
  initialAuth,
  signInMethods = LINKEDIN_ONLY,
  children,
}: {
  initialAuth?: AuthSnapshot;
  signInMethods?: SignInMethods;
  children: ReactNode;
}) {
  return (
    <AuthProvider initial={initialAuth}>
      <SignInMethodsProvider value={signInMethods}>
        {children}
      </SignInMethodsProvider>
    </AuthProvider>
  );
}
