/**
 * Shimmer placeholder shown in the chat thread while `/api/chat/history`
 * hydrates — so opening the chat doesn't flash the empty welcome hero before
 * past messages arrive. Alternating assistant/user rows mimic a real thread.
 */
export default function ChatThreadSkeleton() {
  // width % per bubble — varied so it reads like real message lengths.
  const rows: { role: "aria" | "user"; w: number }[] = [
    { role: "aria", w: 62 },
    { role: "user", w: 40 },
    { role: "aria", w: 78 },
    { role: "user", w: 52 },
    { role: "aria", w: 48 },
  ];
  return (
    <div className="chat-thread chat-skeleton" aria-hidden="true">
      {rows.map((r, i) => (
        <div key={i} className={`chat-skel-row ${r.role}`}>
          {r.role === "aria" && <span className="chat-skel-avatar" />}
          <span className="chat-skel-bubble" style={{ width: `${r.w}%` }} />
        </div>
      ))}
    </div>
  );
}
