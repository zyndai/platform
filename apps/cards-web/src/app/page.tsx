import Link from "next/link";
import { Navbar } from "@/components/Navbar";

export default function HomePage() {
  return (
    <>
      <Navbar />
      <main
        style={{
          minHeight: "70vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          padding: "80px 24px",
          gap: "24px",
        }}
      >
        <h1 style={{ maxWidth: 780 }}>
          Your Zynd Card — a living profile AI agents can find and talk to.
        </h1>
        <p style={{ maxWidth: 620, color: "#bfbfb9", fontSize: "18px", lineHeight: 1.6 }}>
          One page that pulls together your work, your skills, and your writing —
          searchable by other people and by the AI agents acting on their behalf.
        </p>
        <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", justifyContent: "center" }}>
          <Link href="/create" className="zynd-nav-cta" style={{ padding: "14px 28px", fontSize: "16px" }}>
            Create your card
          </Link>
          <Link
            href="/directory"
            style={{
              padding: "14px 28px",
              fontSize: "16px",
              fontWeight: 700,
              borderRadius: "16px",
              border: "1px solid rgba(255,255,255,0.15)",
              color: "#fff",
              textDecoration: "none",
            }}
          >
            Browse the directory
          </Link>
        </div>
      </main>
    </>
  );
}
