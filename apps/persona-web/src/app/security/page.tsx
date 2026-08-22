import { Monogram } from "@/components/ui";

export default function SecurityPage() {
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
          Security
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
          Zynd is built to handle your Google and LinkedIn data with care.
          This page summarizes the security controls we apply.
        </p>

        <Section title="Encryption">
          <p>
            Data is encrypted in transit (TLS) and at rest. OAuth access
            tokens used to act on your behalf are stored separately from your
            account content and are never exposed to your Persona&rsquo;s
            public card or to other users.
          </p>
        </Section>

        <Section title="Access control">
          <p>
            Your connected-account data is isolated to your account through
            database row-level security. Only your own account, or Zynd&rsquo;s
            service backend operating on your behalf, can read or modify your
            data.
          </p>
        </Section>

        <Section title="Scopes and minimization">
          <p>
            We request only the minimum OAuth scopes needed for each feature.
            You can review exactly which scopes you have granted on each
            provider&rsquo;s consent screen at any time.
          </p>
        </Section>

        <Section title="Data segregation">
          <p>
            LinkedIn data is stored separately from your other data and is
            identifiable by source. We do not combine data received through
            official provider APIs with data obtained through scraping or
            crawling.
          </p>
        </Section>

        <Section title="Reporting a vulnerability">
          <p>
            If you believe you have found a security issue, please report it
            to{' '}
            <a href="mailto:contact@zynd.ai">contact@zynd.ai</a>. We will
            acknowledge your report and investigate promptly.
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
        <a href="/data-deletion">Data Deletion</a>
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
