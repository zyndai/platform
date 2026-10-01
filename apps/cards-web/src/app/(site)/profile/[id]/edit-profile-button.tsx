"use client";
import { useAuth } from "@/hooks/useAuth";

const EDIT_ICON = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
  </svg>
);

// Cards on /profile/[id] never have handles — they redirect to /p/[handle] if
// they do. The create page's edit mode only works by handle, so we always link
// to /create with no ?edit param. Authenticated users land on the "you already
// have a card" screen; unauthenticated users see the create form.
export function EditProfileButton() {
  const { ready, authenticated } = useAuth();

  // Hide while auth resolves — avoids "Update profile" → "Edit profile" flash.
  if (!ready) return null;

  return (
    <a href="/create" className="pf-edit-btn">
      {EDIT_ICON}
      {authenticated ? "Edit profile" : "Update profile"}
    </a>
  );
}
