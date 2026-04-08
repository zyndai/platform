"use client";

import { useEffect, useState, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSupabase } from "@/lib/supabase";

interface Thread {
  id: string;
  initiator_id: string;
  receiver_id: string;
  initiator_name: string;
  receiver_name: string;
  status: "pending" | "accepted" | "blocked";
  created_at: string;
}

interface Message {
  id: string;
  thread_id: string;
  sender_id: string;
  content: string;
  created_at: string;
}

export default function MessagesPanel() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThread, setActiveThread] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sessionUser, setSessionUser] = useState<any>(null);
  const [sessionDid, setSessionDid] = useState<string | null>(null);
  const [sessionName, setSessionName] = useState<string>("Zynd Agent");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getSupabase()
      .auth.getSession()
      .then(({ data }) => setSessionUser(data.session?.user));
  }, []);

  useEffect(() => {
    if (!sessionUser) return;

    let isMounted = true;

    const initializeNetwork = async () => {
      let activeDid = sessionDid;
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/persona/${sessionUser.id}/status`
        );
        if (res.ok) {
          const data = await res.json();
          if (data.deployed && data.did) {
            activeDid = data.did;
            if (isMounted) {
              setSessionDid(data.did);
              if (data.name) setSessionName(data.name);
            }
            await getSupabase()
              .from("persona_dids")
              .upsert({ user_id: sessionUser.id, did: data.did });
          }
        }
      } catch (e) {
        console.error("Failed DID sync:", e);
      }

      const sb = getSupabase();
      let queryStr = `initiator_id.eq.${sessionUser.id},receiver_id.eq.${sessionUser.id}`;
      if (activeDid) {
        queryStr = `${queryStr},initiator_id.eq.${activeDid},receiver_id.eq.${activeDid}`;
      }

      const { data } = await sb
        .from("dm_threads")
        .select("*")
        .or(queryStr)
        .order("updated_at", { ascending: false });

      if (data && isMounted) {
        setThreads(data);
      }
    };

    initializeNetwork();

    const channel = getSupabase()
      .channel("system_pings")
      .on("broadcast", { event: "new_thread" }, (payload) => {
        if (
          payload.payload?.receiver_id === sessionUser.id ||
          payload.payload?.receiver_id === sessionDid ||
          payload.payload?.initiator_id === sessionUser.id
        ) {
          initializeNetwork();
        }
      })
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "dm_threads" },
        () => {
          initializeNetwork();
        }
      )
      .subscribe();

    const pollId = setInterval(() => {
      if (isMounted) initializeNetwork();
    }, 10000);

    return () => {
      isMounted = false;
      clearInterval(pollId);
      getSupabase().removeChannel(channel);
    };
  }, [sessionUser]);

  useEffect(() => {
    if (!activeThread) return;
    const sb = getSupabase();

    sb.from("dm_messages")
      .select("*")
      .eq("thread_id", activeThread.id)
      .order("created_at", { ascending: true })
      .then(({ data }) => {
        if (data) setMessages(data);
        setTimeout(
          () => scrollRef.current?.scrollIntoView({ behavior: "smooth" }),
          100
        );
      });

    const channel = sb
      .channel(`thread-${activeThread.id}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "dm_messages",
          filter: `thread_id=eq.${activeThread.id}`,
        },
        (payload) => {
          setMessages((prev) => [...prev, payload.new as Message]);
          setTimeout(
            () => scrollRef.current?.scrollIntoView({ behavior: "smooth" }),
            100
          );
        }
      )
      .subscribe();

    return () => {
      sb.removeChannel(channel);
    };
  }, [activeThread]);

  const handleSend = async () => {
    if (!draft.trim() || !activeThread || !sessionUser) return;
    const content = draft;
    setDraft("");

    await getSupabase().from("dm_messages").insert({
      thread_id: activeThread.id,
      sender_id: sessionDid || sessionUser.id,
      content: content,
    });
  };

  const updateThreadStatus = async (status: string) => {
    if (!activeThread) return;
    await getSupabase()
      .from("dm_threads")
      .update({ status })
      .eq("id", activeThread.id);

    setActiveThread((prev) =>
      prev ? { ...prev, status: status as any } : null
    );
  };

  const getPartnerId = (thread: Thread) =>
    thread.initiator_id === sessionUser.id ||
    thread.initiator_id === sessionDid
      ? thread.receiver_id
      : thread.initiator_id;
  const getPartnerName = (thread: Thread) =>
    thread.initiator_id === sessionUser.id ||
    thread.initiator_id === sessionDid
      ? thread.receiver_name
      : thread.initiator_name;

  const requests = threads.filter(
    (t) =>
      t.status === "pending" &&
      (t.receiver_id === sessionUser.id || t.receiver_id === sessionDid)
  );
  const primary = threads.filter(
    (t) =>
      t.status === "accepted" ||
      (t.status === "pending" &&
        (t.initiator_id === sessionUser.id ||
          t.initiator_id === sessionDid))
  );

  const [newChatDid, setNewChatDid] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    if (newChatDid.length < 2) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await fetch(
          `https://registry.zynd.ai/agents?keyword=${encodeURIComponent(newChatDid)}&limit=10`
        );
        const json = await res.json();
        const items = json.data || json;
        const personas = Array.isArray(items)
          ? items.filter((a: any) => {
              const caps = a.capabilities || {};
              let parsed = caps;
              if (typeof caps === "string")
                try {
                  parsed = JSON.parse(caps);
                } catch {}
              return (
                typeof parsed === "object" &&
                Array.isArray(parsed?.services) &&
                parsed.services.includes("persona")
              );
            })
          : [];
        setSearchResults(personas);
      } catch (e) {
        console.error(e);
      }
      setIsSearching(false);
    }, 400);
    return () => clearTimeout(timer);
  }, [newChatDid]);

  const startNewChat = async (targetAgent: any) => {
    if (!targetAgent || !targetAgent.didIdentifier || !sessionUser) return;
    const targetDid = targetAgent.didIdentifier;

    const existing = threads.find(
      (t) =>
        ((t.initiator_id === sessionUser.id ||
          t.initiator_id === sessionDid) &&
          t.receiver_id === targetDid.trim()) ||
        ((t.receiver_id === sessionUser.id ||
          t.receiver_id === sessionDid) &&
          t.initiator_id === targetDid.trim())
    );
    if (existing) {
      setActiveThread(existing);
      setNewChatDid("");
      setSearchResults([]);
      return;
    }

    const { data } = await getSupabase()
      .from("dm_threads")
      .insert({
        initiator_id: sessionDid || sessionUser.id,
        receiver_id: targetDid.trim(),
        initiator_name: sessionName,
        receiver_name: targetAgent.name || "Network Agent",
        status: "pending",
      })
      .select()
      .single();

    if (data) {
      setActiveThread(data);
      setNewChatDid("");
      setSearchResults([]);

      getSupabase().channel("system_pings").send({
        type: "broadcast",
        event: "new_thread",
        payload: {
          receiver_id: targetDid.trim(),
          initiator_id: sessionDid || sessionUser.id,
        },
      });
    }
  };

  if (!sessionUser)
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          background: "var(--bg-base)",
        }}
      >
        <div className="status-pill">
          <span className="status-dot" />
          Authenticating...
        </div>
      </div>
    );

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        width: "100%",
        overflow: "hidden",
        background: "var(--bg-base)",
      }}
    >
      {/* ── Left: Thread Inbox ── */}
      <div
        style={{
          width: "300px",
          borderRight: "1px solid var(--border-subtle)",
          display: "flex",
          flexDirection: "column",
          background: "var(--bg-base)",
          flexShrink: 0,
        }}
      >
        {/* Header & Search */}
        <div
          style={{
            padding: "20px 16px",
            borderBottom: "1px solid var(--border-subtle)",
            position: "relative",
          }}
        >
          <h2
            style={{
              fontFamily: "Syne, sans-serif",
              fontSize: "15px",
              fontWeight: 700,
              marginBottom: "4px",
            }}
          >
            Network DMs
          </h2>
          <p className="section-label" style={{ marginBottom: "14px" }}>
            CROSS-AGENT MESSAGING
          </p>
          <input
            type="text"
            placeholder="Search Zynd Network..."
            value={newChatDid}
            onChange={(e) => setNewChatDid(e.target.value)}
            className="input"
            style={{ fontSize: "12px", padding: "8px 12px" }}
          />

          {/* Live Search Dropdown */}
          {(searchResults.length > 0 || isSearching) && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: "16px",
                right: "16px",
                background: "var(--bg-overlay)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--r-md)",
                zIndex: 100,
                maxHeight: "280px",
                overflowY: "auto",
                boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
                marginTop: "4px",
              }}
            >
              {isSearching ? (
                <div
                  style={{
                    padding: "14px",
                    fontSize: "11px",
                    color: "var(--text-muted)",
                    fontFamily: "IBM Plex Mono, monospace",
                  }}
                >
                  Searching network...
                </div>
              ) : (
                searchResults.map((p) => (
                  <div
                    key={p.didIdentifier}
                    onClick={() => startNewChat(p)}
                    style={{
                      padding: "12px 14px",
                      borderBottom: "1px solid var(--border-subtle)",
                      cursor: "pointer",
                      transition: "background 0.15s",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "var(--bg-raised)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = "transparent")
                    }
                  >
                    <div
                      style={{
                        fontFamily: "DM Sans, sans-serif",
                        fontSize: "13px",
                        fontWeight: 500,
                        color: "var(--text-primary)",
                      }}
                    >
                      {p.name}
                    </div>
                    <div
                      style={{
                        fontFamily: "IBM Plex Mono, monospace",
                        fontSize: "10px",
                        color: "var(--text-muted)",
                        marginTop: "2px",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {p.description || "Zynd Agent"}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Thread list */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {/* Requests */}
          {requests.length > 0 && (
            <div style={{ padding: "12px 16px" }}>
              <p
                className="section-label"
                style={{ color: "var(--accent-coral)", marginBottom: "8px" }}
              >
                REQUESTS ({requests.length})
              </p>
              {requests.map((t) => (
                <div
                  key={t.id}
                  onClick={() => setActiveThread(t)}
                  className="card"
                  style={{
                    padding: "12px",
                    marginBottom: "6px",
                    background:
                      activeThread?.id === t.id
                        ? "var(--bg-raised)"
                        : "var(--bg-surface)",
                    borderColor:
                      activeThread?.id === t.id
                        ? "var(--border-strong)"
                        : "var(--border-default)",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "DM Sans, sans-serif",
                      fontSize: "13px",
                      fontWeight: 500,
                      color: "var(--text-primary)",
                    }}
                  >
                    New Request
                  </div>
                  <div
                    style={{
                      fontFamily: "IBM Plex Mono, monospace",
                      fontSize: "10px",
                      color: "var(--text-muted)",
                      marginTop: "3px",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {getPartnerName(t)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Primary inbox */}
          <div style={{ padding: "12px 16px" }}>
            <p className="section-label" style={{ marginBottom: "8px" }}>
              PRIMARY INBOX
            </p>
            {primary.map((t) => {
              const partnerName = getPartnerName(t);
              return (
                <div
                  key={t.id}
                  onClick={() => setActiveThread(t)}
                  className="card"
                  style={{
                    padding: "12px",
                    marginBottom: "6px",
                    background:
                      activeThread?.id === t.id
                        ? "var(--bg-raised)"
                        : "var(--bg-surface)",
                    borderColor:
                      activeThread?.id === t.id
                        ? "var(--border-strong)"
                        : "var(--border-default)",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "DM Sans, sans-serif",
                      fontSize: "13px",
                      fontWeight: 500,
                      color: "var(--text-primary)",
                    }}
                  >
                    {partnerName}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      marginTop: "4px",
                    }}
                  >
                    {t.status === "pending" ? (
                      <span className="tag tag-amber" style={{ fontSize: "9px" }}>
                        PENDING
                      </span>
                    ) : (
                      <span className="tag tag-teal" style={{ fontSize: "9px" }}>
                        ACTIVE
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
            {primary.length === 0 && (
              <p
                style={{
                  fontSize: "12px",
                  color: "var(--text-muted)",
                  marginTop: "16px",
                  fontFamily: "DM Sans, sans-serif",
                }}
              >
                No active chats yet.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── Main Chat Area ── */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          background: "var(--bg-base)",
        }}
      >
        {activeThread ? (
          <>
            {/* Chat header */}
            <div
              className="topbar"
              style={{ gap: "14px", borderBottom: "1px solid var(--border-subtle)" }}
            >
              <div
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "var(--r-sm)",
                  background:
                    "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "Syne, sans-serif",
                  fontWeight: 800,
                  fontSize: "14px",
                  color: "#fff",
                  flexShrink: 0,
                }}
              >
                {getPartnerName(activeThread)?.charAt(0) || "Z"}
              </div>
              <div>
                <h3
                  style={{
                    fontFamily: "Syne, sans-serif",
                    fontSize: "14px",
                    fontWeight: 600,
                    color: "var(--text-primary)",
                  }}
                >
                  {getPartnerName(activeThread)}
                </h3>
                <p
                  style={{
                    fontFamily: "IBM Plex Mono, monospace",
                    fontSize: "9.5px",
                    color: "var(--text-muted)",
                    maxWidth: "280px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {getPartnerId(activeThread)}
                </p>
              </div>
              <div style={{ marginLeft: "auto" }}>
                {activeThread.status === "accepted" ? (
                  <span className="tag tag-teal" style={{ fontSize: "9px" }}>CONNECTED</span>
                ) : activeThread.status === "pending" ? (
                  <span className="tag tag-amber" style={{ fontSize: "9px" }}>PENDING</span>
                ) : (
                  <span className="tag tag-coral" style={{ fontSize: "9px" }}>BLOCKED</span>
                )}
              </div>
            </div>

            {/* Messages area */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "24px",
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              {/* Pending request banner */}
              {activeThread.status === "pending" &&
                (activeThread.receiver_id === sessionUser.id ||
                  activeThread.receiver_id === sessionDid) && (
                  <div
                    style={{
                      background: "var(--bg-surface)",
                      border: "1px solid var(--border-default)",
                      padding: "20px",
                      borderRadius: "var(--r-md)",
                      textAlign: "center",
                      alignSelf: "center",
                      maxWidth: "400px",
                    }}
                  >
                    <p
                      style={{
                        marginBottom: "16px",
                        fontSize: "13px",
                        color: "var(--text-secondary)",
                        lineHeight: 1.6,
                      }}
                    >
                      This network agent is requesting to connect with you.
                      Accepting allows them to message and orchestrate tools on
                      your behalf.
                    </p>
                    <div
                      style={{
                        display: "flex",
                        gap: "10px",
                        justifyContent: "center",
                      }}
                    >
                      <button
                        onClick={() => updateThreadStatus("accepted")}
                        className="btn-primary"
                        style={{ padding: "8px 20px", fontSize: "12px" }}
                      >
                        Accept Request
                      </button>
                      <button
                        onClick={() => updateThreadStatus("blocked")}
                        className="btn-danger"
                        style={{ padding: "8px 20px", fontSize: "12px" }}
                      >
                        Block
                      </button>
                    </div>
                  </div>
                )}

              {messages.map((m) => {
                const isMe =
                  m.sender_id === sessionUser.id ||
                  m.sender_id === sessionDid;
                return (
                  <div
                    key={m.id}
                    style={{
                      alignSelf: isMe ? "flex-end" : "flex-start",
                      maxWidth: "75%",
                      display: "flex",
                      gap: "10px",
                      animation: "slideIn 0.2s ease",
                    }}
                  >
                    {/* Partner avatar */}
                    {!isMe && (
                      <div
                        style={{
                          width: "28px",
                          height: "28px",
                          borderRadius: "var(--r-sm)",
                          background:
                            "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontFamily: "Syne, sans-serif",
                          fontWeight: 800,
                          fontSize: "11px",
                          color: "#fff",
                          flexShrink: 0,
                          marginTop: "2px",
                        }}
                      >
                        {getPartnerName(activeThread)?.charAt(0) || "A"}
                      </div>
                    )}
                    <div
                      className={isMe ? "msg-bubble-user" : "msg-bubble-ai"}
                      style={{ maxWidth: "100%" }}
                    >
                      <div className="markdown-content">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {m.content}
                        </ReactMarkdown>
                      </div>
                      <p className="msg-timestamp" style={{ marginTop: "6px" }}>
                        {new Date(m.created_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                    </div>
                  </div>
                );
              })}
              <div ref={scrollRef} />
            </div>

            {/* Input bar */}
            <div
              style={{
                padding: "16px 24px 20px",
                borderTop: "1px solid var(--border-subtle)",
                background: "rgba(13, 17, 23, 0.9)",
                backdropFilter: "blur(8px)",
              }}
            >
              <div
                style={{ maxWidth: "720px", margin: "0 auto" }}
              >
                <div className="input-wrap">
                  <input
                    className="chat-input"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleSend();
                    }}
                    placeholder={
                      activeThread.status === "accepted"
                        ? "Type a message..."
                        : "Awaiting approval..."
                    }
                    disabled={
                      activeThread.status !== "accepted" &&
                      (activeThread.receiver_id === sessionUser.id ||
                        activeThread.receiver_id === sessionDid)
                    }
                  />
                  <button
                    onClick={handleSend}
                    disabled={
                      !draft.trim() || activeThread.status === "blocked"
                    }
                    className="btn-primary"
                    style={{ padding: "8px 18px", fontSize: "12px" }}
                  >
                    Send
                  </button>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: "12px",
            }}
          >
            <div
              style={{
                width: "48px",
                height: "48px",
                borderRadius: "var(--r-md)",
                background: "var(--bg-surface)",
                border: "1px solid var(--border-default)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "20px",
                color: "var(--text-muted)",
              }}
            >
              ◈
            </div>
            <p
              style={{
                color: "var(--text-muted)",
                fontSize: "13px",
                fontFamily: "DM Sans, sans-serif",
              }}
            >
              Select a connection to start messaging
            </p>
            <p className="section-label">CROSS-NETWORK PROTOCOL</p>
          </div>
        )}
      </div>
    </div>
  );
}
