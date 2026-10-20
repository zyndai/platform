"use client";

import { useEffect, useRef, useState } from "react";
import type { RealtimeChannel } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";

export type NetworkRealtimeStatus = "connecting" | "connected" | "disconnected";

export interface NetworkRealtimeEvent {
  event: string;
  payload: Record<string, unknown>;
}

/**
 * Subscribe to a private Cards Realtime topic. The topic is authorized by the
 * `cards.network_can_subscribe` RLS policy; the browser never reads the cards
 * tables directly.
 */
export function useNetworkRealtime({
  token,
  topic,
  events,
  onEvent,
  onReconnect,
  enabled = true,
}: {
  token: string;
  topic: string | null;
  events: readonly string[];
  onEvent: (event: NetworkRealtimeEvent) => void;
  onReconnect?: () => void;
  enabled?: boolean;
}): NetworkRealtimeStatus {
  const eventRef = useRef(onEvent);
  const reconnectRef = useRef(onReconnect);
  const [status, setStatus] = useState<NetworkRealtimeStatus>("connecting");
  const eventKey = events.join("|");

  useEffect(() => {
    eventRef.current = onEvent;
    reconnectRef.current = onReconnect;
  });

  useEffect(() => {
    if (!enabled || !topic || process.env.NEXT_PUBLIC_DISABLE_REALTIME === "true") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStatus("disconnected");
      return;
    }
    const supabase = createClient();
    let cancelled = false;
    let channel: RealtimeChannel | null = null;
    let hasSubscribed = false;

    async function connect() {
      setStatus("connecting");
      try {
        await supabase.realtime.setAuth(token);
      } catch {
        // A failed auth refresh should not prevent a later reconnect attempt.
      }
      if (cancelled) return;
      channel = supabase.channel(topic!, { config: { private: true } });
      for (const event of eventKey.split("|").filter(Boolean)) {
        channel.on("broadcast", { event }, (message) => {
          eventRef.current({
            event: message.event,
            payload: (message.payload ?? {}) as Record<string, unknown>,
          });
        });
      }
      channel.subscribe((state) => {
        if (cancelled) return;
        if (state === "SUBSCRIBED") {
          setStatus("connected");
          if (hasSubscribed) reconnectRef.current?.();
          hasSubscribed = true;
        } else if (state === "CHANNEL_ERROR" || state === "TIMED_OUT" || state === "CLOSED") {
          setStatus("disconnected");
        } else {
          setStatus("connecting");
        }
      });
    }

    void connect();
    return () => {
      cancelled = true;
      if (channel) void supabase.removeChannel(channel);
    };
  }, [token, topic, eventKey, enabled]);

  return status;
}
