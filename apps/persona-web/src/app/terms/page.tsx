import { Monogram } from "@/components/ui";

export default function TermsPage() {
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
          Terms of Service
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

        <Section title="1. Acceptance of Terms">
          <p>
            By accessing or using Zynd (&ldquo;the Service&rdquo;), a
            product of Zynd AI Inc (&ldquo;Zynd,&rdquo; &ldquo;we,&rdquo;
            &ldquo;us&rdquo;), a Delaware corporation, you agree to be bound
            by these Terms of Service (&ldquo;Terms&rdquo;). If you do not
            agree, do not use the Service.
          </p>
        </Section>

        <Section title="2. Service Description">
          <p>
            Zynd provides AI-powered productivity features that integrate
            with your Google Workspace data after your explicit consent.
            The Service includes:
          </p>
          <ul>
              <li>
                An AI &ldquo;Persona&rdquo; that represents you in
                professional outreach, scheduling, and coordination.
              </li>
              <li>
                Automated meeting scheduling through your Google Calendar.
              </li>
              <li>
                Professional context and profile enrichment through your
                LinkedIn account, when you connect it.
              </li>
            <li>
              A personal &ldquo;Brief&rdquo; stored securely in your Zynd
              account for long-form notes, context, and AI-generated content.
            </li>
            <li>
              File management limited to files the Service creates or
              that you explicitly select.
            </li>
          </ul>
        </Section>

        <Section title="3. Google & LinkedIn API Services">
          <p>
            Zynd uses Google and LinkedIn APIs to provide its core
            functionality. When you connect either account, you authorize the
            following OAuth scopes:
          </p>

          <Scope
            scope=".../auth/calendar"
            label="Google Calendar"
          >
            To read your availability (free/busy) and create, update, or
            delete calendar events for AI-assisted meeting scheduling and
            coordination. More limited scopes are insufficient because the
            Service must modify calendar events to deliver its core
            scheduling functionality.
          </Scope>

          <Scope
            scope=".../auth/drive.file"
            label="Google Drive"
          >
            To create, access, search, and manage only the files created by
            the Service or explicitly selected by you through
            Google&rsquo;s file picker. This per-file scope cannot see,
            list, or read your other Drive files.
          </Scope>

          <Scope
            scope="openid profile email w_member_social"
            label="LinkedIn"
          >
            To access the LinkedIn profile information and posts you authorize
            through LinkedIn&rsquo;s consent screen, so your Persona can
            understand your professional background and activity. If you
            approve posting, your Persona may share content to LinkedIn on
            your behalf.
          </Scope>

          <p>
            All Google API access is initiated by you and limited to
            providing the features described above. Zynd&rsquo;s use of
            information received from Google APIs adheres to the{' '}
            <a href="https://developers.google.com/terms/api-services-user-data-policy">
              Google API Services User Data Policy
            </a>
            , including the Limited Use requirements.
          </p>
          <p>
            Zynd&rsquo;s use of information received from LinkedIn APIs is
            limited to providing the features you request. LinkedIn data is
            stored separately and is not obtained through scraping or
            crawling. Your use of LinkedIn is also subject to LinkedIn&rsquo;s
            own terms and policies.
          </p>
        </Section>

        <Section title="4. Your Account">
          <p>
            You are responsible for maintaining the security of your
            account credentials. You must provide accurate and complete
            information when creating your account. You may not use the
            Service for any illegal or unauthorized purpose.
          </p>
        </Section>

        <Section title="5. User Responsibilities">
          <p>
            When using Zynd, you agree that:
          </p>
          <ul>
            <li>
              You will not use the Service to send spam, harass others, or
              impersonate any person or entity.
            </li>
            <li>
              You are responsible for the content of messages and meeting
              invitations sent through your Persona.
            </li>
            <li>
              You will respect the privacy and data rights of others,
              including obtaining necessary consent before sharing data
              about others through the Service.
            </li>
            <li>
              You will not attempt to reverse-engineer, decompile, or
              extract the source code of the Service.
            </li>
          </ul>
        </Section>

        <Section title="6. Intellectual Property">
          <p>
            The Zynd platform, including its AI models, software, design,
            and branding, is owned by ZyndAI and protected by intellectual
            property laws. You retain ownership of your data, including
            your Brief content, calendar entries, and any files stored in
            your Google Account.
          </p>
          <p>
            By using the Service, you grant ZyndAI a limited license to
            access and process your data solely as necessary to provide the
            Service to you. This license ends when you disconnect your
            account or revoke our access to your Google Account.
          </p>
        </Section>

        <Section title="7. Third-Party Services">
          <p>
            Zynd integrates with Google services through official APIs. Your
            use of those services is also subject to Google&rsquo;s own
            terms and policies:
          </p>
          <ul>
            <li>
              <a href="https://policies.google.com/terms">
                Google Terms of Service
              </a>
            </li>
            <li>
              <a href="https://policies.google.com/privacy">
                Google Privacy Policy
              </a>
            </li>
          </ul>
        </Section>

        <Section title="8. Limitation of Liability">
          <p>
            THE SERVICE IS PROVIDED &ldquo;AS IS&rdquo; WITHOUT WARRANTY
            OF ANY KIND, EITHER EXPRESS OR IMPLIED. TO THE MAXIMUM EXTENT
            PERMITTED BY LAW, ZYNDAI SHALL NOT BE LIABLE FOR ANY
            INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE
            DAMAGES ARISING FROM YOUR USE OF THE SERVICE.
          </p>
          <p>
            ZyndAI does not guarantee that the Service will be
            uninterrupted, error-free, or that AI-generated content will
            always be accurate or appropriate. You use the Service at your
            own discretion and risk.
          </p>
        </Section>

        <Section title="9. Termination">
          <p>
            You may stop using the Service at any time. You can revoke
            Zynd&rsquo;s access to your Google Account through{' '}
            <a href="https://myaccount.google.com/permissions">
              Google Account permissions
            </a>
            . We reserve the right to suspend or terminate your access to
            the Service for violations of these Terms.
          </p>
        </Section>

        <Section title="10. Changes to These Terms">
          <p>
            We may modify these Terms from time to time. If we make
            material changes, we will notify you through the Zynd
            application or via the email associated with your account. Your
            continued use of the Service after changes take effect
            constitutes your acceptance of the revised Terms.
          </p>
        </Section>

        <Section title="11. Governing Law">
          <p>
            These Terms shall be governed by and construed in accordance
            with the laws of the State of Delaware, without regard to its
            conflict of law provisions.
          </p>
        </Section>

        <Section title="12. Contact">
          <p>
            For questions about these Terms, contact us at{' '}
            <a href="mailto:contact@zynd.ai">contact@zynd.ai</a> or by mail
            at Zynd AI Inc, 8 The Green STE A, Dover, DE 19901.
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
