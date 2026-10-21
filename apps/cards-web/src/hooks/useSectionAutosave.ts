"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ownerRequest } from "@/lib/owner-home";

export type SectionValues = Record<string, Record<string, unknown>>;

/** Serialize saves and compare each section with its last acknowledged value.
 * New edits made during a request stay queued. Failures keep the draft local;
 * navigation is blocked until saving succeeds or the user reloads deliberately.
 *
 * With `auto` false nothing is saved until `flush()` is called (the editor's Save
 * button), so a slip of the mouse can be discarded instead of being persisted.
 * Leaving the page then asks first instead of saving on the way out.
 */
export function useSectionAutosave(
  handle: string,
  token: string,
  values: SectionValues,
  enabled: boolean,
  auto = true,
) {
  const router = useRouter();
  const initial = JSON.stringify(values);
  const baseline = useRef<SectionValues>(JSON.parse(initial));
  const expected = useRef<SectionValues>(JSON.parse(initial));
  const latest = useRef<SectionValues>(values);
  const running = useRef<Promise<boolean> | null>(null);
  const [status, setStatus] = useState("Saved");
  const [sectionStates, setSectionStates] = useState<Record<string, string>>(
    {},
  );
  const [error, setError] = useState("");
  // What the server last acknowledged, as state so the page can show "unsaved" and revert to it.
  const [saved, setSaved] = useState<SectionValues>(() => JSON.parse(initial));
  const [recovery, setRecovery] = useState<SectionValues | null>(null);
  const storageKey = useMemo(() => {
    try {
      const payload = JSON.parse(
        atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
      ) as { sub?: string };
      return payload.sub ? `zynd:s10:draft:${payload.sub}:${handle}` : null;
    } catch {
      return null;
    }
  }, [token, handle]);
  const mounted = useRef(true);
  const dirty = useCallback(
    () => JSON.stringify(baseline.current) !== JSON.stringify(latest.current),
    [],
  );

  const saveRef = useRef<() => Promise<boolean>>(async () => true);
  useEffect(() => {
    if (!enabled || !storageKey) return;
    // Load browser-only recovery after hydration, without changing the server
    // render or synchronously cascading a second render from this effect.
    let previousDraft: SectionValues | null = null;
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (raw && raw !== initial)
        previousDraft = JSON.parse(raw) as SectionValues;
    } catch {
      /* Private browsing may disable storage. */
    }
    // Capture before backing up this visit's first edit. Defer only publishing
    // the recovery prompt, so it cannot mistake a new edit for a previous visit.
    const timer = setTimeout(() => {
      if (previousDraft) setRecovery(previousDraft);
    }, 0);
    return () => clearTimeout(timer);
    // Inspect recovery once on mount; later edits are backed up separately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, storageKey]);

  useEffect(() => {
    latest.current = JSON.parse(initial);
    if (enabled && storageKey && dirty()) {
      try {
        sessionStorage.setItem(storageKey, initial);
      } catch {
        /* Unload warning remains available. */
      }
    }
    saveRef.current = () => {
      if (running.current) return running.current;
      const work = async () => {
        if (!dirty()) return true;
        if (mounted.current) {
          setStatus("Saving…");
          setError("");
        }
        try {
          while (dirty()) {
            const snapshot: SectionValues = JSON.parse(
              JSON.stringify(latest.current),
            );
            for (const [section, patch] of Object.entries(snapshot)) {
              if (
                JSON.stringify(baseline.current[section]) ===
                JSON.stringify(patch)
              )
                continue;
              if (mounted.current)
                setSectionStates((current) => ({
                  ...current,
                  [section]: "Saving…",
                }));
              const saved = await ownerRequest<Record<string, unknown>>(
                `by-handle/${encodeURIComponent(handle)}/sections/${section}`,
                token,
                "PATCH",
                { patch, expected: expected.current[section] },
              );
              // Compare against the normalized values returned by the API, but
              // don't replace newer local input with an older response.
              const acknowledged = Object.fromEntries(
                Object.keys(patch).map((key) => [key, saved[key]]),
              );
              baseline.current[section] = patch;
              expected.current[section] = acknowledged;
              if (mounted.current) {
                setSaved(JSON.parse(JSON.stringify(baseline.current)));
                setSectionStates((current) => ({
                  ...current,
                  [section]: "Saved",
                }));
              }
            }
          }
          if (storageKey) {
            try {
              sessionStorage.removeItem(storageKey);
            } catch {
              /* Storage is optional. */
            }
          }
          if (mounted.current) {
            setStatus("Saved");
            setRecovery(null);
          }
          return true;
        } catch (failure) {
          if (mounted.current) {
            setStatus("Not saved");
            setError(
              failure instanceof Error
                ? failure.message
                : "Could not save. Try again.",
            );
          }
          return false;
        }
      };
      running.current = work().finally(() => {
        running.current = null;
      });
      return running.current;
    };
  }, [initial, handle, token, dirty, enabled, storageKey]);

  useEffect(() => {
    if (!enabled || !auto || !dirty()) return;
    const timer = setTimeout(() => void saveRef.current(), 750);
    return () => clearTimeout(timer);
  }, [initial, enabled, auto, dirty]);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty() || running.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    const click = (event: MouseEvent) => {
      const anchor = (event.target as Element | null)?.closest("a");
      if (
        !anchor ||
        event.defaultPrevented ||
        event.button !== 0 ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        anchor.target === "_blank" ||
        (!dirty() && !running.current)
      )
        return;
      const target = new URL(anchor.href);
      if (
        target.origin !== location.origin ||
        (target.pathname === location.pathname &&
          target.search === location.search)
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      const go = () => router.push(target.pathname + target.search + target.hash);
      if (!auto) {
        if (window.confirm("You have unsaved changes. Leave without saving?")) go();
        return;
      }
      void saveRef.current().then((ok) => {
        if (ok) go();
      });
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", click, true);
    return () => {
      mounted.current = false;
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", click, true);
    };
  }, [enabled, auto, router, dirty]);

  const clearBackup = () => {
    if (storageKey) {
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        /* Optional storage. */
      }
    }
    setRecovery(null);
  };

  return {
    status,
    sectionStates,
    error,
    recovery,
    /** True while the page holds edits the server hasn't acknowledged. */
    unsaved: JSON.stringify(saved) !== initial,
    /** The values the server last acknowledged. */
    saved,
    discardRecovery: clearBackup,
    /** After the page drops its edits: forget the local backup and any save error. */
    reset: () => {
      clearBackup();
      setStatus("Saved");
      setError("");
    },
    flush: () => saveRef.current(),
  };
}
