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
          Last updated: August 22, 2026
        </p>

        <p>
          Zynd AI Inc (&ldquo;Zynd,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;),
          a Delaware corporation, builds an AI-powered productivity agent that
          helps you schedule meetings, manage your Brief, and coordinate
          professional outreach. This Privacy Policy explains what information
          we access from your Google Account and LinkedIn account, how we use
          it, and your rights.
        </p>

        <Section title="1. Information We Access">
          <p>
            When you connect your Google Account or LinkedIn account to Zynd,
            you grant us permission to access the following types of data
            through each provider&rsquo;s OAuth scopes. We request only the
            minimum permissions needed to provide our service.
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
            scope=".../auth/drive.file"
            label="Google Drive"
          >
            We access only the specific Drive files created by Zynd or files
            you explicitly select through Google&rsquo;s file picker. We
            cannot see, list, or read any other files in your Drive. This
            per-file scope ensures your private documents remain private.
          </Scope>

          <Scope
            scope="openid profile email w_member_social"
            label="LinkedIn"
          >
            We access your LinkedIn profile information and recent posts that
            you authorize through LinkedIn&rsquo;s consent screen. This powers
            your Persona&rsquo;s understanding of your professional background
            and public activity. If you additionally approve posting, your
            Persona can share content to LinkedIn on your behalf.
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
              <strong>Brief management:</strong> Storing your Brief with
              context and content you provide or approve, so your Persona can
              represent you accurately.
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
            Your Brief is stored securely on Zynd&rsquo;s servers. Your calendar
            events remain stored in your Google Account. We do not copy,
            replicate, or store the full contents of your calendar events on
            our servers. We maintain OAuth tokens to act on your behalf, and
            these tokens are stored securely using industry-standard encryption.
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
          <p>
            Our website uses Google Analytics to understand aggregate,
            anonymized usage of our marketing site. This does not involve your
            Google Account, LinkedIn account, or any data we access on your
            behalf.
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
              to remove Zynd&rsquo;s access to your Google Account, or
              revoke Zynd&rsquo;s access through your LinkedIn account
              settings. Once revoked, we can no longer access your data.
            </li>
            <li>
              <strong>Disconnect or delete data:</strong> You can disconnect
              either integration or delete the data we store for a given
              provider through your Zynd account settings, without deleting
              your whole account. See our{' '}
              <a href="/data-deletion">Data Deletion</a> page for details.
            </li>
            <li>
              <strong>Delete your account:</strong> You can delete your entire
              Zynd account through the app settings. Calendar events created
              by Zynd remain in your Google Account; you control them directly
              through Google Calendar.
            </li>
            <li>
              <strong>Limited scope:</strong> We only request the specific
              OAuth scopes listed above. You can review these permissions at
              any time through each provider&rsquo;s consent screen.
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

        <Section title="7. LinkedIn Data">
          <p>
            If you connect your LinkedIn account, Zynd accesses only the
            LinkedIn data you authorize through LinkedIn&rsquo;s OAuth consent
            flow, such as your profile information and posts. We use this data
            solely to power your Persona&rsquo;s understanding of your
            professional background and activity.
          </p>
          <p>
            LinkedIn data is stored separately from your other data and is
            identifiable by source. We do not obtain LinkedIn data through
            scraping or crawling, and we do not combine LinkedIn data received
            through official LinkedIn APIs with data obtained through any
            scraping or crawling of LinkedIn.
          </p>
          <p>
            You may disconnect your LinkedIn account or delete the LinkedIn
            data Zynd has stored at any time through your account settings or
            by contacting us. When you request deletion, we delete the stored
            LinkedIn data and associated access tokens, subject to applicable
            legal requirements.
          </p>
        </Section>

        <Section title="8. Data Retention">
          <p>
            We retain OAuth tokens only while your integration is connected,
            and delete them when you disconnect. LinkedIn profile data is
            retained only while your LinkedIn integration is active. Your
            Brief and other account content are retained until you delete your
            account. When you delete your account, we delete your stored data
            and tokens, subject to legal retention obligations.
          </p>
        </Section>

        <Section title="9. Changes to This Policy">
          <p>
            We may update this Privacy Policy from time to time. When we
            make material changes, we will notify you through the Zynd
            application or via the email associated with your account.
          </p>
        </Section>

        <Section title="10. Contact Us">
          <p>
            If you have questions about this Privacy Policy or our data
            practices, or wish to exercise your data rights, contact us at{' '}
            <a href="mailto:contact@zynd.ai">contact@zynd.ai</a> or by mail at
            Zynd AI Inc, 8 The Green STE A, Dover, DE 19901.
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
        <a href="/terms">Terms of Service</a>
        <span>&middot;</span>
        <a href="/data-deletion">Data Deletion</a>
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
