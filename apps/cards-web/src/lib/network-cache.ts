"use client";

import { useSyncExternalStore } from "react";
import type { AgentSources } from "./agent-stream";
import type {
  CardGroupMember,
  CardInbox,
  CardMessage,
  CardMessagePage,
} from "./cards-network";

export type NetworkThreadKind = "dm" | "group";

export interface CachedThread {
  messages: CardMessage[];
  hasMore: boolean;
  latestSeq: number;
  peerReadSeq: number;
  threadId: string | null;
  updatedAt: number;
}

export interface NetworkCacheState {
  userId: string | null;
  inbox: CardInbox | null;
  inboxAt: number;
  threads: Record<string, CachedThread>;
  members: Record<string, CardGroupMember[]>;
  version: number;
}

const EMPTY_STATE: NetworkCacheState = {
  userId: null,
  inbox: null,
  inboxAt: 0,
  threads: {},
  members: {},
  version: 0,
};

const THREAD_LIMIT = 30;
const MESSAGE_LIMIT = 80;
const STORAGE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const DB_NAME = "zynd-cards-network";
const STORE = "cache";
const DB_VERSION = 1;

let state: NetworkCacheState = EMPTY_STATE;
let currentUserId: string | null = null;
let hydratePromise: Promise<void> | null = null;
let persistTimer: number | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): NetworkCacheState {
  return state;
}

function getServerSnapshot(): NetworkCacheState {
  return EMPTY_STATE;
}

export function useNetworkCache(): NetworkCacheState {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export function threadKey(kind: NetworkThreadKind, id: string): string {
  return `${kind}:${id}`;
}

export function mergeMessages(current: CardMessage[], incoming: CardMessage[]): CardMessage[] {
  const byKey = new Map<string, CardMessage>();
  for (const message of current) byKey.set(message.client_id ?? message.id, message);
  for (const message of incoming) byKey.set(message.client_id ?? message.id, message);
  return [...byKey.values()].sort((a, b) => {
    if (a.seq != null && b.seq != null) return a.seq - b.seq;
    if (a.seq != null) return -1;
    if (b.seq != null) return 1;
    return a.created_at.localeCompare(b.created_at);
  });
}

export function getCachedInbox(): CardInbox | null {
  return state.inbox;
}

export function getCachedThread(kind: NetworkThreadKind, id: string): CachedThread | undefined {
  return state.threads[threadKey(kind, id)];
}

export function getCachedMembers(groupId: string): CardGroupMember[] | undefined {
  return state.members[groupId];
}

function nextState(patch: Partial<NetworkCacheState>) {
  state = { ...state, ...patch, version: state.version + 1 };
  emit();
  schedulePersist();
}

export function cacheInbox(inbox: CardInbox) {
  nextState({ inbox, inboxAt: Date.now() });
}

export function cacheMembers(groupId: string, members: CardGroupMember[]) {
  nextState({ members: { ...state.members, [groupId]: members } });
}

export function invalidateCachedMembers(groupId: string) {
  if (!(groupId in state.members)) return;
  const next = { ...state.members };
  delete next[groupId];
  nextState({ members: next });
}

export function cacheThreadPage(
  kind: NetworkThreadKind,
  id: string,
  page: CardMessagePage,
  mode: "initial" | "older" | "newer" = "initial",
) {
  const key = threadKey(kind, id);
  const previous = state.threads[key];
  // Server rows win over the cached copy; this matters for flags such as
  // `remembered` that another member may have set since the cache was written.
  const messages = mergeMessages(previous?.messages ?? [], page.messages);
  const thread: CachedThread = {
    messages,
    hasMore: mode === "newer" ? previous?.hasMore ?? false : page.has_more,
    latestSeq: Math.max(previous?.latestSeq ?? 0, page.latest_seq ?? 0),
    peerReadSeq: page.peer_last_read_seq ?? previous?.peerReadSeq ?? 0,
    threadId: page.thread_id ?? previous?.threadId ?? null,
    updatedAt: Date.now(),
  };
  nextState({ threads: { ...state.threads, [key]: thread } });
}

export function cacheThreadMessage(kind: NetworkThreadKind, id: string, message: CardMessage) {
  const key = threadKey(kind, id);
  const previous = state.threads[key];
  const thread: CachedThread = {
    messages: mergeMessages(previous?.messages ?? [], [message]),
    hasMore: previous?.hasMore ?? false,
    latestSeq: Math.max(previous?.latestSeq ?? 0, message.seq ?? 0),
    peerReadSeq: previous?.peerReadSeq ?? 0,
    threadId: message.thread_id ?? previous?.threadId ?? null,
    updatedAt: Date.now(),
  };
  nextState({ threads: { ...state.threads, [key]: thread } });
}

export function cacheThreadPeerRead(kind: NetworkThreadKind, id: string, seq: number) {
  const key = threadKey(kind, id);
  const previous = state.threads[key];
  if (!previous) return;
  nextState({
    threads: {
      ...state.threads,
      [key]: { ...previous, peerReadSeq: Math.max(previous.peerReadSeq, seq), updatedAt: Date.now() },
    },
  });
}

export function markCachedMessageRemembered(
  kind: NetworkThreadKind,
  id: string,
  messageId: string,
  memoryId: string,
) {
  const key = threadKey(kind, id);
  const previous = state.threads[key];
  if (!previous) return;
  nextState({
    threads: {
      ...state.threads,
      [key]: {
        ...previous,
        messages: previous.messages.map((message) => message.id === messageId
          ? { ...message, remembered: true, memory_id: memoryId }
          : message),
        updatedAt: Date.now(),
      },
    },
  });
}

export function removeCachedMessage(kind: NetworkThreadKind, id: string, clientId: string) {
  const key = threadKey(kind, id);
  const previous = state.threads[key];
  if (!previous) return;
  nextState({
    threads: {
      ...state.threads,
      [key]: {
        ...previous,
        messages: previous.messages.filter((message) => message.client_id !== clientId),
        updatedAt: Date.now(),
      },
    },
  });
}

// ── Where an assistant reply came from (dev only) ───────────────────────────
//
// Sent by cards-api with `agent_stream` when it runs with
// FEATURE_AGENT_DEBUG_SOURCES, keyed by job id, which the finished reply
// carries as its `client_id`. Deliberately outside `state`: it is session
// memory, so it survives switching conversations but is never written to
// IndexedDB and is gone on reload.

const SOURCES_LIMIT = 100;
const NO_SOURCES: Record<string, AgentSources> = {};
let agentSources = NO_SOURCES;
const sourceListeners = new Set<() => void>();

function emitSources() {
  for (const listener of sourceListeners) listener();
}

function subscribeSources(listener: () => void): () => void {
  sourceListeners.add(listener);
  return () => sourceListeners.delete(listener);
}

export function rememberAgentSources(jobId: string, sources: AgentSources) {
  const kept = Object.entries(agentSources).filter(([id]) => id !== jobId).slice(-(SOURCES_LIMIT - 1));
  agentSources = Object.fromEntries([...kept, [jobId, sources]]);
  emitSources();
}

export function useAgentSources(): Record<string, AgentSources> {
  return useSyncExternalStore(subscribeSources, () => agentSources, () => NO_SOURCES);
}

export function clearNetworkCache() {
  state = EMPTY_STATE;
  currentUserId = null;
  agentSources = NO_SOURCES;
  emitSources();
  hydratePromise = null;
  if (persistTimer != null && typeof window !== "undefined") window.clearTimeout(persistTimer);
  persistTimer = null;
  emit();
  if (typeof indexedDB !== "undefined") {
    try {
      const request = indexedDB.deleteDatabase(DB_NAME);
      request.onerror = () => undefined;
    } catch {
      // Private mode or a blocked browser store: the in-memory cache still resets.
    }
  }
}

/**
 * Load the signed-in user's persisted cache once. The in-memory cache is always
 * authoritative while the tab is open; IndexedDB only seeds a fresh mount.
 */
export function hydrateNetworkCache(userId: string): Promise<void> {
  if (!userId) return Promise.resolve();
  if (currentUserId === userId && state.userId === userId) return hydratePromise ?? Promise.resolve();
  currentUserId = userId;
  state = { ...EMPTY_STATE, userId };
  hydratePromise = null;
  emit();

  hydratePromise = loadPersisted(userId)
    .then((saved) => {
      if (!saved || currentUserId !== userId) return;
      const threads = { ...state.threads };
      for (const [key, savedThread] of Object.entries(saved.threads)) {
        const current = threads[key];
        if (!current || savedThread.updatedAt > current.updatedAt) threads[key] = savedThread;
      }
      state = {
        ...state,
        inbox: state.inboxAt > saved.savedAt ? state.inbox : saved.inbox ?? state.inbox,
        inboxAt: Math.max(state.inboxAt, saved.savedAt),
        threads,
        members: { ...saved.members, ...state.members },
        version: state.version + 1,
      };
      emit();
    })
    .catch(() => undefined)
    .finally(() => {
      hydratePromise = null;
    });

  return hydratePromise;
}

function schedulePersist() {
  const userId = currentUserId;
  if (!userId || typeof window === "undefined") return;
  if (persistTimer != null) window.clearTimeout(persistTimer);
  persistTimer = window.setTimeout(() => {
    persistTimer = null;
    void persist(userId);
  }, 450);
}

async function persist(userId: string) {
  if (typeof indexedDB === "undefined" || state.userId !== userId) return;
  const threads = Object.entries(state.threads)
    .sort(([, a], [, b]) => b.updatedAt - a.updatedAt)
    .slice(0, THREAD_LIMIT)
    .map(([key, thread]) => {
      const clean = thread.messages.filter((message) => !message.pending && !message.failed);
      return [
        key,
        {
          ...thread,
          messages: clean.slice(-MESSAGE_LIMIT),
          // The persisted copy is truncated; keep "load older" available.
          hasMore: clean.length > MESSAGE_LIMIT ? true : thread.hasMore,
        },
      ];
    });
  const payload = {
    savedAt: Date.now(),
    inbox: state.inbox,
    threads: Object.fromEntries(threads),
    members: state.members,
  };
  try {
    const db = await openDb();
    if (!db) return;
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(payload, userId);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
    db.close();
  } catch {
    // Storage is best effort. A full or private store must not break chat.
  }
}

async function loadPersisted(userId: string): Promise<{
  savedAt: number;
  inbox: CardInbox | null;
  threads: Record<string, CachedThread>;
  members: Record<string, CardGroupMember[]>;
} | null> {
  try {
    const db = await openDb();
    if (!db) return null;
    const value = await new Promise<unknown>((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const request = tx.objectStore(STORE).get(userId);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    db.close();
    if (!value || typeof value !== "object") return null;
    const saved = value as {
      savedAt?: unknown;
      inbox?: CardInbox | null;
      threads?: Record<string, CachedThread>;
      members?: Record<string, CardGroupMember[]>;
    };
    const savedAt = typeof saved.savedAt === "number" ? saved.savedAt : 0;
    if (!savedAt || Date.now() - savedAt > STORAGE_TTL_MS) return null;
    return {
      savedAt,
      inbox: saved.inbox ?? null,
      threads: saved.threads && typeof saved.threads === "object" ? saved.threads : {},
      members: saved.members && typeof saved.members === "object" ? saved.members : {},
    };
  } catch {
    return null;
  }
}

function openDb(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === "undefined") return Promise.resolve(null);
  return new Promise((resolve) => {
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}
