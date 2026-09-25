import { Monogram } from "@/components/ui";

export default function DataDeletionPage() {
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
          Data Deletion
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
        <p
          style={{
            fontFamily:
              "var(--font-geist-mono), ui-monospace, monospace",
            fontSize: 12,
            color: "var(--ink-muted)",
            marginBottom: 24,
            letterSpacing: "0.2px",
          }}
        >
          Last updated: August 22, 2026
        </p>

        <p>
          You control the data Zynd stores. This page explains how to delete
          the data associated with your Google or LinkedIn integrations, and
          how to delete your account entirely.
        </p>

        <Section title="Disconnect an integration">
          <p>
            Disconnecting removes Zynd&rsquo;s access to that provider and
            deletes the stored OAuth tokens for it. You can disconnect from
            your Zynd account settings, or directly from the provider:
          </p>
          <ul>
            <li>
              <strong>Google:</strong> visit{' '}
              <a href="https://myaccount.google.com/permissions">
                myaccount.google.com/permissions
              </a>{' '}
              and remove Zynd&rsquo;s access.
            </li>
            <li>
              <strong>LinkedIn:</strong> remove Zynd&rsquo;s access in your
              LinkedIn account security settings.
            </li>
          </ul>
        </Section>

        <Section title="Delete provider data without deleting your account">
          <p>
            You can delete the data Zynd has stored for a specific provider
            while keeping your Zynd account. For example, deleting LinkedIn
            data removes your stored LinkedIn profile information and access
            tokens, but leaves your Zynd persona and other connections intact.
            Use the &ldquo;Delete data&rdquo; action in your account settings.
          </p>
        </Section>

        <Section title="Delete your account">
          <p>
            Deleting your Zynd account removes your persona, brief,
            conversations, scheduled meetings, connected integrations, and
            stored provider tokens. This action cannot be undone. You can
            delete your account from your Zynd account settings.
          </p>
        </Section>

        <Section title="What we retain">
          <p>
            When you delete data or your account, we delete the relevant
            stored data and tokens promptly, subject to legal obligations
            (such as fraud prevention or legal retention requirements). Data
            that remains in the provider&rsquo;s own systems (for example,
            calendar events created in your Google Calendar) is controlled by
            you through that provider.
          </p>
        </Section>

        <Section title="Requesting deletion">
          <p>
            To request deletion of any data we hold about you, contact us at{' '}
            <a href="mailto:contact@zynd.ai">contact@zynd.ai</a>. We will
            respond to verifiable requests in accordance with applicable law.
          </p>
        </Section>
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
        <a href="/security">Security</a>
        <span>&middot;</span>
        <a href="/contact">Contact</a>
      </footer>
    </main>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 36 }}>
      <h2
        style={{
          fontFamily:
            "var(--font-fraunces), ui-serif, Georgia, serif",
          fontWeight: 500,
          fontSize: 20,
          lineHeight: 1.3,
          color: "var(--ink)",
          marginBottom: 14,
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}
