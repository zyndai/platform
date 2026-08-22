import { Monogram } from "@/components/ui";

export default function ContactPage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        background: "var(--paper)",
        color: "var(--ink)",
        fontFamily: "var(--font-geist), 'Inter', system-ui, sans-serif",
      }}
    >
      <nav
        style={{
          padding: "12px 22px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <a href="/" aria-label="Zynd home" style={{ display: "inline-flex" }}>
          <Monogram size="md" />
        </a>
        <span
          style={{
            fontFamily:
              "var(--font-instrument-sans), 'Instrument Sans', system-ui, sans-serif",
            fontWeight: 600,
            fontSize: 18,
            letterSpacing: "-0.3px",
          }}
        >
          Contact
        </span>
      </nav>

      <article
        style={{
          maxWidth: 720,
          margin: "0 auto",
          padding: "48px 24px 80px",
          fontSize: "14.5px",
          lineHeight: 1.7,
          color: "var(--ink-secondary)",
        }}
      >
        <p>
          For support, privacy, data-deletion, or security questions, reach
          out to:
        </p>

        <div
          style={{
            background: "var(--surface-raised)",
            border: "1px solid var(--border-subtle)",
            borderRadius: 12,
            padding: "18px 20px",
            margin: "20px 0 32px",
          }}
        >
          <p style={{ margin: "0 0 6px" }}>
            <strong>Email:</strong>{' '}
            <a href="mailto:contact@zynd.ai">contact@zynd.ai</a>
          </p>
          <p style={{ margin: 0 }}>
            <strong>Mailing address:</strong> Zynd AI Inc, 8 The Green STE A,
            Dover, DE 19901
          </p>
        </div>

        <p>
          Please include as much detail as possible so we can route your
          request correctly. For data-deletion requests, see our{' '}
          <a href="/data-deletion">Data Deletion</a> page.
        </p>
      </article>

      <footer
        style={{
          maxWidth: 720,
          margin: "0 auto",
          padding: "0 24px 48px",
          fontSize: 13,
          color: "var(--ink-muted)",
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span>&copy; Zynd AI Inc</span>
        <span>&middot;</span>
        <a href="/privacy">Privacy Policy</a>
        <span>&middot;</span>
        <a href="/terms">Terms of Service</a>
        <span>&middot;</span>
        <a href="/data-deletion">Data Deletion</a>
        <span>&middot;</span>
        <a href="/security">Security</a>
      </footer>
    </main>
  );
}
