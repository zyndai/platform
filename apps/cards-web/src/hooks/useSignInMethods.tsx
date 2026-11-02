"use client";

import { createContext, useContext, type ReactNode } from "react";
import { LINKEDIN_ONLY, type SignInMethods } from "@/lib/auth/providers";

const SignInMethodsContext = createContext<SignInMethods>(LINKEDIN_ONLY);

/** Seeded by the root layouts from lib/auth/sign-in-methods.ts, so server and client agree. */
export function SignInMethodsProvider({ value, children }: { value: SignInMethods; children: ReactNode }) {
  return <SignInMethodsContext.Provider value={value}>{children}</SignInMethodsContext.Provider>;
}

export function useSignInMethods(): SignInMethods {
  return useContext(SignInMethodsContext);
}
