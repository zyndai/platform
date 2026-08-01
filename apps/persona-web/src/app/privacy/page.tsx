import { Monogram } from "@/components/ui";

export default function PrivacyPage() {
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
          Privacy Policy
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
          Last updated: July 27, 2026
        </p>

        <p>
          ZyndAI (&ldquo;Zynd,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;)
          builds an AI-powered productivity agent that helps you schedule
          meetings, manage brief documents, and coordinate professional
          outreach. This Privacy Policy explains what information we access
          from your Google Account, how we use it, and your rights.
        </p>

        <Section title="1. Information We Access">
          <p>
            When you connect your Google Account to Zynd, you grant us
            permission to access the following types of data through
            Google&rsquo;s OAuth scopes. We request only the minimum
            permissions needed to provide our service.
          </p>

          <Scope
            scope=".../auth/calendar"
            label="Google Calendar"
          >
            We read your calendar&rsquo;s free/busy
            availability and create, update, or delete calendar events on
            your behalf. This powers AI-assisted meeting scheduling and
            coordination. We use Google Calendar&rsquo;s{' '}
            <code>freebusy.query</code> API to read availability
            without accessing event titles, attendees, or descriptions.
          </Scope>

          <Scope
            scope=".../auth/documents"
            label="Google Docs"
          >
            We create, read, and update Google Docs documents that serve as
            your &ldquo;Brief&rdquo; &mdash; long-form notes, context, and
            AI-generated content that you own. Your Brief helps your AI
            Persona understand your work, goals, and background so it can
            act on your behalf accurately.
          </Scope>

          <Scope
            scope=".../auth/drive.file"
            label="Google Drive"
          >
            We access only the specific Drive files created by Zynd or files
            you explicitly select through Google&rsquo;s file picker. We
            cannot see, list, or read any other files in your Drive. This
            per-file scope ensures your private documents remain private.
          </Scope>
        </Section>

        <Section title="2. How We Use Your Data">
          <p>We use the data we access solely to provide Zynd&rsquo;s core features, and only after you explicitly connect your account and initiate an action:</p>
          <ul>
            <li>
              <strong>Meeting scheduling:</strong> Reading your availability
              to find open times, and creating/updating calendar events when
              you or your Persona schedules a meeting.
            </li>
            <li>
              <strong>Brief management:</strong> Creating, reading, and
              updating your Brief document with context and content you
              provide or approve.
            </li>
            <li>
              <strong>File access:</strong> Managing only the Drive files
              created by Zynd or explicitly shared by you.
            </li>
          </ul>
          <p>
            All access is user-initiated. Your Persona acts on your behalf
            only when you direct it to. We do not scan, mine, or analyze
            your data for advertising, profiling, or any purpose unrelated
            to your use of Zynd.
          </p>
        </Section>

        <Section title="3. Data Storage & Security">
          <p>
            Your documents and calendar events remain stored in your Google
            Account. We do not copy, replicate, or store the full contents
            of your Google Docs or calendar events on our servers. We
            maintain OAuth tokens to act on your behalf, and these tokens
            are stored securely using industry-standard encryption.
          </p>
          <p>
            Zynd fetches data from Google&rsquo;s APIs in real time when
            needed to respond to your requests. We maintain a privacy-first
            architecture: for calendar data, we use only free/busy queries
            that reveal your availability without exposing meeting details.
            The application also maintains an audit log of
            privacy-sensitive data accesses so you can review when your
            data was read and by whom.
          </p>
        </Section>

        <Section title="4. Data Sharing">
          <p>
            We do not sell, rent, or share your personal data with third
            parties. Your Google Account data is accessed only by Zynd&rsquo;s
            services acting on your behalf, and only for the purposes
            described in this policy.
          </p>
          <p>
            We do not transfer your Google data to any third-party
            advertising networks, data brokers, or analytics services.
          </p>
        </Section>

        <Section title="5. Your Control">
          <p>
            You have full control over the data we access:
          </p>
          <ul>
            <li>
              <strong>Revoke access anytime:</strong> Visit{' '}
              <a href="https://myaccount.google.com/permissions">
                myaccount.google.com/permissions
              </a>{' '}
              and remove Zynd&rsquo;s access to your Google Account. Once
              revoked, we can no longer access your data.
            </li>
            <li>
              <strong>Delete your data:</strong> You can delete your Zynd
              account through the app settings. Documents and calendar
              events created by Zynd remain in your Google Account; you
              control them directly through Google Docs and Google Calendar.
            </li>
            <li>
              <strong>Limited scope:</strong> We only request the specific
              OAuth scopes listed above. You can review these permissions
              at any time through Google&rsquo;s consent screen.
            </li>
          </ul>
        </Section>

        <Section title="6. Use of Google User Data">
          <p>
            Zynd&rsquo;s use and transfer of information received from
            Google APIs conforms to the{' '}
            <a href="https://developers.google.com/terms/api-services-user-data-policy">
              Google API Services User Data Policy
            </a>
            , including the Limited Use requirements. We access Google user
            data only to provide and improve our service&rsquo;s core
            functionality. We do not use Google user data for advertising
            or to build user profiles for ad targeting.
          </p>
        </Section>

        <Section title="7. Changes to This Policy">
          <p>
            We may update this Privacy Policy from time to time. When we
            make material changes, we will notify you through the Zynd
            application or via the email associated with your account.
          </p>
        </Section>

        <Section title="8. Contact Us">
          <p>
            If you have questions about this Privacy Policy or our data
            practices, contact us at{' '}
            <a href="mailto:tech@zynd.ai">tech@zynd.ai</a>.
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
        <span>&copy; ZyndAI</span>
        <span>&middot;</span>
        <a href="/terms">Terms of Service</a>
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

function Scope({
  scope,
  label,
  children,
}: {
  scope: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-subtle)",
        borderRadius: 12,
        padding: "16px 18px",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontFamily:
              "var(--font-geist-mono), ui-monospace, monospace",
            fontSize: 11,
            fontWeight: 600,
            color: "var(--accent)",
            background: "var(--accent-soft-bg)",
            padding: "2px 8px",
            borderRadius: 999,
            letterSpacing: "0.2px",
          }}
        >
          {scope}
        </span>
        <span
          style={{
            fontFamily:
              "var(--font-geist), 'Inter', system-ui, sans-serif",
            fontWeight: 600,
            fontSize: 14,
            color: "var(--ink)",
          }}
        >
          {label}
        </span>
      </div>
      <p
        style={{
          margin: 0,
          fontSize: "13.5px",
          color: "var(--ink-secondary)",
          lineHeight: 1.6,
        }}
      >
        {children}
      </p>
    </div>
  );
}
