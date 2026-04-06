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
  status: 'pending' | 'accepted' | 'blocked';
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
    getSupabase().auth.getSession().then(({ data }) => setSessionUser(data.session?.user));
  }, []);

  useEffect(() => {
    if (!sessionUser) return;
    
    let isMounted = true;
    
    const initializeNetwork = async () => {
      let activeDid = sessionDid;
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/persona/${sessionUser.id}/status`);
        if (res.ok) {
          const data = await res.json();
          if (data.deployed && data.did) {
            activeDid = data.did;
            if (isMounted) {
              setSessionDid(data.did);
              if (data.name) setSessionName(data.name);
            }
            await getSupabase().from("persona_dids").upsert({ user_id: sessionUser.id, did: data.did });
          }
        }
      } catch (e) {
        console.error("Failed DID sync:", e);
      }
      
      const sb = getSupabase();
      let queryStr = `initiator_id.eq.${sessionUser.id},receiver_id.eq.${sessionUser.id}`;
      // Query both local UUID or cross-network identity DID
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
    
    // Listen to global PubSub broadcast room
    const channel = getSupabase()
      .channel('system_pings')
      .on('broadcast', { event: 'new_thread' }, (payload) => {
        // If a thread is created involving us, aggressively refetch the DB
        if (payload.payload?.receiver_id === sessionUser.id || payload.payload?.receiver_id === sessionDid || payload.payload?.initiator_id === sessionUser.id) {
           initializeNetwork();
        }
      })
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'dm_threads' }, () => {
        initializeNetwork(); 
      })
      .subscribe();
      
    const pollId = setInterval(() => { if (isMounted) initializeNetwork(); }, 10000);
      
    return () => { 
      isMounted = false;
      clearInterval(pollId);
      getSupabase().removeChannel(channel); 
    }
  }, [sessionUser]);

  useEffect(() => {
    if (!activeThread) return;
    const sb = getSupabase();
    
    sb.from("dm_messages")
      .select("*")
      .eq("thread_id", activeThread.id)
      .order("created_at", { ascending: true })
      .then(({data}) => {
        if (data) setMessages(data);
        setTimeout(() => scrollRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
      });

    const channel = sb.channel(`thread-${activeThread.id}`)
      .on('postgres_changes', { 
        event: 'INSERT', 
        schema: 'public', 
        table: 'dm_messages',
        filter: `thread_id=eq.${activeThread.id}`
      }, (payload) => {
        setMessages(prev => [...prev, payload.new as Message]);
        setTimeout(() => scrollRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
      })
      .subscribe();

    return () => { sb.removeChannel(channel); }
  }, [activeThread]);

  const handleSend = async () => {
    if (!draft.trim() || !activeThread || !sessionUser) return;
    const content = draft;
    setDraft(""); // clear payload
    
    await getSupabase().from("dm_messages").insert({
      thread_id: activeThread.id,
      sender_id: sessionDid || sessionUser.id,
      content: content
    });
  };

  const updateThreadStatus = async (status: string) => {
    if (!activeThread) return;
    await getSupabase()
      .from("dm_threads")
      .update({ status })
      .eq("id", activeThread.id);
      
    setActiveThread(prev => prev ? { ...prev, status: status as any } : null);
  };

  // Extract the specific partner metadata inherently snapped at thread creation
  const getPartnerId = (thread: Thread) => (thread.initiator_id === sessionUser.id || thread.initiator_id === sessionDid) ? thread.receiver_id : thread.initiator_id;
  const getPartnerName = (thread: Thread) => (thread.initiator_id === sessionUser.id || thread.initiator_id === sessionDid) ? thread.receiver_name : thread.initiator_name;

  // Categorize threads into visual inboxes
  const requests = threads.filter(t => t.status === 'pending' && (t.receiver_id === sessionUser.id || t.receiver_id === sessionDid));
  const primary = threads.filter(t => t.status === 'accepted' || (t.status === 'pending' && (t.initiator_id === sessionUser.id || t.initiator_id === sessionDid)));
  
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
        const res = await fetch(`https://registry.zynd.ai/agents?keyword=${encodeURIComponent(newChatDid)}&limit=10`);
        const json = await res.json();
        const items = json.data || json;
        const personas = Array.isArray(items) ? items.filter((a: any) => {
          const caps = a.capabilities || {};
          let parsed = caps;
          if (typeof caps === 'string') try { parsed = JSON.parse(caps) } catch {}
          return typeof parsed === 'object' && Array.isArray(parsed?.services) && parsed.services.includes("persona");
        }) : [];
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
    
    // Check if thread already exists comparing string equivalencies
    const existing = threads.find(t => 
      ((t.initiator_id === sessionUser.id || t.initiator_id === sessionDid) && t.receiver_id === targetDid.trim()) ||
      ((t.receiver_id === sessionUser.id || t.receiver_id === sessionDid) && t.initiator_id === targetDid.trim())
    );
    if (existing) {
      setActiveThread(existing);
      setNewChatDid("");
      setSearchResults([]);
      return;
    }
    
    // Save SNAPSHOT of Names natively in Postgres Database to bypass lookup latency!
    const { data } = await getSupabase().from("dm_threads").insert({
      initiator_id: sessionDid || sessionUser.id,
      receiver_id: targetDid.trim(),
      initiator_name: sessionName,
      receiver_name: targetAgent.name || "Network Agent",
      status: 'pending'
    }).select().single();
    
    if (data) {
      setActiveThread(data);
      setNewChatDid("");
      setSearchResults([]);
      
      // Fire a PubSub ping explicitly targeting the receiver's app instance to wake them up
      getSupabase().channel('system_pings').send({
          type: 'broadcast',
          event: 'new_thread',
          payload: { receiver_id: targetDid.trim(), initiator_id: sessionDid || sessionUser.id }
      });
    }
  };

  if (!sessionUser) return <div style={{ padding: '40px', color: '#fff' }}>Authenticating user...</div>;

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%', overflow: 'hidden', background: 'var(--bg-primary)' }}>
      {/* ── Left Sidebar: Thread Inbox ── */}
      <div style={{ width: '320px', borderRight: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', background: 'rgba(255,255,255,0.02)' }}>
        
        {/* Header & New Chat */}
        <div style={{ padding: '24px', borderBottom: '1px solid var(--border-color)', position: 'relative' }}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '16px' }}>Messages</h2>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input 
              type="text" 
              placeholder="Search Zynd Network..." 
              value={newChatDid}
              onChange={(e) => setNewChatDid(e.target.value)}
              className="input"
              style={{ padding: '10px 14px', flex: 1, fontSize: '0.8rem', borderRadius: '8px' }}
            />
          </div>
          
          {/* Live Search Floating Dropdown */}
          {(searchResults.length > 0 || isSearching) && (
            <div style={{
              position: 'absolute', top: '100%', left: '24px', right: '24px',
              background: 'var(--bg-card)', border: '1px solid var(--border-color)',
              borderRadius: '8px', zIndex: 100, maxHeight: '300px', overflowY: 'auto',
              boxShadow: '0 10px 30px rgba(0,0,0,0.5)', marginTop: '4px'
            }}>
              {isSearching ? (
                <div style={{ padding: '16px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>Searching network...</div>
              ) : (
                searchResults.map(p => (
                  <div key={p.didIdentifier} onClick={() => startNewChat(p)} style={{
                    padding: '12px 16px', borderBottom: '1px solid var(--border-color)',
                    cursor: 'pointer', transition: 'background 0.2s', background: 'transparent'
                  }} onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'} onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#fff' }}>{p.name}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.description || "Zynd Agent"}</div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {requests.length > 0 && (
            <div style={{ padding: '16px 24px', background: 'rgba(239, 68, 68, 0.04)' }}>
              <p style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--error)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Requests ({requests.length})</p>
              {requests.map(t => (
               <div key={t.id} onClick={() => setActiveThread(t)} style={{ padding: '14px', background: activeThread?.id === t.id ? 'rgba(255,255,255,0.06)' : 'transparent', cursor: 'pointer', borderRadius: '12px', marginTop: '10px', transition: 'all 0.2s ease', border: activeThread?.id === t.id ? '1px solid rgba(255,255,255,0.1)' : '1px solid transparent' }}>
                  <div style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-primary)' }}>New Request</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{getPartnerName(t)}</div>
                </div>
              ))}
            </div>
          )}
          
          <div style={{ padding: '16px 24px' }}>
             <p style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Primary Inbox</p>
             {primary.map(t => {
                const partnerName = getPartnerName(t);
                return (
                  <div key={t.id} onClick={() => setActiveThread(t)} style={{ padding: '14px', background: activeThread?.id === t.id ? 'rgba(255,255,255,0.04)' : 'transparent', cursor: 'pointer', borderRadius: '12px', marginTop: '10px', transition: 'all 0.2s ease', border: activeThread?.id === t.id ? '1px solid rgba(255,255,255,0.08)' : '1px solid transparent' }}>
                    <div style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-primary)' }}>{partnerName}</div>
                    <div style={{ fontSize: '0.75rem', color: t.status === 'pending' ? 'var(--warning)' : 'var(--text-muted)', marginTop: '4px' }}>{t.status === 'pending' ? 'Pending Acceptance...' : 'Active'}</div>
                  </div>
                );
              })}
              {primary.length === 0 && <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '20px' }}>No active chats yet.</p>}
          </div>
        </div>
      </div>

      {/* ── Main Chat Area ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {activeThread ? (
          <>
            <div style={{ padding: '24px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-card)', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
              <div style={{ width: '40px', height: '40px', background: 'var(--accent-primary)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, color: '#fff', marginRight: '16px' }}>
                {getPartnerName(activeThread)?.charAt(0) || "Z"}
              </div>
              <div>
                <h3 style={{ fontSize: '1.15rem', fontWeight: 700 }}>{getPartnerName(activeThread)}</h3>
                <p style={{ fontSize: '0.65rem', color: 'var(--text-muted)', fontFamily: 'monospace', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{getPartnerId(activeThread)}</p>
              </div>
            </div>
            
            <div style={{ flex: 1, overflowY: 'auto', padding: '32px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {activeThread.status === 'pending' && (activeThread.receiver_id === sessionUser.id || activeThread.receiver_id === sessionDid) && (
                <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', padding: '24px', borderRadius: '16px', textAlign: 'center', alignSelf: 'center', maxWidth: '400px' }}>
                  <p style={{ marginBottom: '20px', fontSize: '0.95rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    This network agent is requesting to connect with you. Accepting this request allows them to message and orchestrate tools on your behalf.
                  </p>
                  <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                    <button onClick={() => updateThreadStatus('accepted')} className="btn btn-primary" style={{ padding: '0 24px' }}>Accept Request</button>
                    <button onClick={() => updateThreadStatus('blocked')} className="btn btn-outline" style={{ borderColor: 'rgba(239, 68, 68, 0.3)', color: '#ef4444', padding: '0 24px' }}>Block</button>
                  </div>
                </div>
              )}
              
              {messages.map(m => {
                const isMe = (m.sender_id === sessionUser.id || m.sender_id === sessionDid);
                return (
                  <div key={m.id} style={{ alignSelf: isMe ? 'flex-end' : 'flex-start', maxWidth: '75%' }}>
                    <div style={{
                      padding: '14px 20px',
                      background: isMe ? 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))' : 'var(--bg-card)',
                      color: isMe ? '#fff' : 'var(--text-primary)',
                      border: isMe ? 'none' : '1px solid var(--border-color)',
                      borderRadius: isMe ? '20px 20px 4px 20px' : '20px 20px 20px 4px',
                      fontSize: '0.95rem',
                      lineHeight: 1.5,
                      boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                    }}>
                      <div className="markdown-content">
                        <ReactMarkdown
                          components={{
                            h1: ({node, ...props}) => <h1 style={{ fontSize: '1.8rem', fontWeight: 800, margin: '20px 0 12px', color: '#fff', display: 'block' }} {...props} />,
                            h2: ({node, ...props}) => <h2 style={{ fontSize: '1.4rem', fontWeight: 700, margin: '18px 0 10px', color: '#fff', display: 'block' }} {...props} />,
                            p: ({node, ...props}) => <p style={{ marginBottom: '12px', lineHeight: '1.6', display: 'block' }} {...props} />,
                          }}
                        >
                          {m.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                  </div>
                );
              })}
              <div ref={scrollRef} />
            </div>

            <div style={{ padding: '24px', background: 'var(--bg-card)', borderTop: '1px solid var(--border-color)' }}>
              <div style={{ display: 'flex', gap: '16px', maxWidth: '900px', margin: '0 auto' }}>
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSend() }}
                  placeholder={activeThread.status === 'accepted' ? "Type a message..." : "Awaiting approval..."}
                  disabled={activeThread.status !== 'accepted' && (activeThread.receiver_id === sessionUser.id || activeThread.receiver_id === sessionDid)}
                  style={{ flex: 1, padding: '16px 24px', borderRadius: '100px', border: '1px solid var(--border-color)', background: 'var(--bg-main)', color: '#fff', outline: 'none', fontSize: '1rem', transition: 'all 0.2s ease' }}
                />
                <button 
                  onClick={handleSend} 
                  disabled={!draft.trim() || activeThread.status === 'blocked'} 
                  className="btn btn-primary" 
                  style={{ borderRadius: '100px', padding: '0 32px', fontWeight: 700 }}
                >
                  Send
                </button>
              </div>
            </div>
          </>
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '1.1rem' }}>
            Select a connection to start messaging.
          </div>
        )}
      </div>
    </div>
  );
}
