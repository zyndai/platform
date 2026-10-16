import Link from "next/link";
import { ArrowUpRight, Eye, Inbox, MessageSquare, Search, Sparkles, Zap } from "lucide-react";
import type { OwnerStatus } from "@/lib/owner-home";
import "./discovery-analytics.css";

const TOPIC_LABELS: Record<string, string> = {
  contact: "Contact", work: "Work", skills: "Skills", background: "Background", other: "Other",
};
const number = (value: number | null) => value === null ? "—" : value.toLocaleString("en-US");

export function DiscoveryAnalytics({ activity, profile, visitors }: {
  activity: OwnerStatus["activity"];
  profile: string;
  visitors?: OwnerStatus["visitors"];
}) {
  const topics = activity.chat_topics ?? [];
  const topicTotal = topics.reduce((total, topic) => total + topic.count, 0);
  const introAvailable = activity.intro_requests !== null;
  const questions = activity.chat_questions ?? [];

  return (
    <section className="oh-panel oh-wide oh-discovery" aria-labelledby="discovery-heading">
      <header className="oh-discovery-header">
        <div className="oh-discovery-title">
          <span className="oh-discovery-emblem"><Zap size={16} aria-hidden="true" /></span>
          <h2 id="discovery-heading">Who found you · Last 7 days</h2>
        </div>
        <span className={`oh-discovery-state${activity.available ? " is-active" : ""}`}>
          <i aria-hidden="true" />{activity.available ? "Activity recorded" : "Activity unavailable"}
        </span>
      </header>

      <div className="oh-discovery-metrics">
        <div className="oh-discovery-metric oh-discovery-human">
          <div className="oh-discovery-metric-top">
            <span className="oh-discovery-icon"><Eye size={20} aria-hidden="true" /></span>
            <span className="oh-discovery-period">7 days</span>
          </div>
          <strong>{number(activity.views)}</strong>
          <span className="oh-discovery-label">Human views</span>
          <p className="oh-discovery-detail">Recorded visits from human browsers</p>
        </div>
        <div className="oh-discovery-metric oh-discovery-agent">
          <div className="oh-discovery-metric-top">
            <span className="oh-discovery-icon"><Sparkles size={20} aria-hidden="true" /></span>
            <span className="oh-discovery-period">7 days</span>
          </div>
          <strong>{number(activity.agent_hits)}</strong>
          <span className="oh-discovery-label">Agent hits</span>
          <p className="oh-discovery-detail">Recorded requests from AI clients and crawlers</p>
        </div>
        <div className="oh-discovery-metric oh-discovery-intro">
          <div className="oh-discovery-metric-top">
            <span className="oh-discovery-icon"><Inbox size={20} aria-hidden="true" /></span>
            <span className="oh-discovery-badge">{introAvailable ? "Requests" : "Coming soon"}</span>
          </div>
          <strong>{number(activity.intro_requests)}</strong>
          <span className="oh-discovery-label">Intro requests</span>
          <p className="oh-discovery-detail">{introAvailable ? "People who asked to connect with you" : "Introduction tracking is not available yet"}</p>
        </div>
      </div>
      {!activity.available && <p className="oh-discovery-unavailable">Activity measurement is unavailable. Counts will appear when event collection is enabled.</p>}

      <div className="oh-discovery-insights">
        <section className="oh-discovery-insight" aria-labelledby="discovery-questions">
          <div className="oh-discovery-insight-title">
            <h3 id="discovery-questions"><Search size={17} aria-hidden="true" />Questions that found your card</h3>
            <span className="oh-discovery-count">{activity.query_capture_available ? `${activity.queries.length} questions` : "Unavailable"}</span>
          </div>
          <p className="oh-discovery-description">Recorded discovery questions that matched your profile.</p>
          {activity.queries.length ? (
            <ol className="oh-discovery-questions">
              {activity.queries.map((query, index) => (
                <li key={`${index}-${query.query}`}>
                  <span className="oh-discovery-index">{String(index + 1).padStart(2, "0")}</span>
                  <span>{query.query}</span>
                  {query.count !== undefined && <span className="oh-discovery-query-count">×{query.count}</span>}
                </li>
              ))}
            </ol>
          ) : <p className="oh-discovery-empty">{activity.query_capture_available ? "No matching questions recorded in the last 7 days." : "Matching queries are not recorded yet."}</p>}
        </section>

        <section className="oh-discovery-insight" aria-labelledby="discovery-topics">
          <div className="oh-discovery-insight-title">
            <h3 id="discovery-topics"><MessageSquare size={17} aria-hidden="true" />What people asked the assistant</h3>
            <span className="oh-discovery-count">{topicTotal.toLocaleString("en-US")} questions</span>
          </div>
          <p className="oh-discovery-description">Topics from questions asked on your card, without the private conversation.</p>
          {topics.length ? (
            <ul className="oh-discovery-topics">
              {topics.map((topic) => (
                <li key={topic.category}>
                  <div><span>{TOPIC_LABELS[topic.category] ?? topic.category}</span><span className="oh-discovery-count">{topic.count} {topic.count === 1 ? "question" : "questions"}</span></div>
                  <div className="oh-discovery-track" aria-hidden="true"><span style={{ width: `${topicTotal ? Math.min(100, topic.count / topicTotal * 100) : 0}%` }} /></div>
                </li>
              ))}
            </ul>
          ) : <p className="oh-discovery-empty">No assistant questions recorded yet.</p>}
        </section>
      </div>

      <section className="oh-discovery-insight oh-discovery-history" aria-labelledby="assistant-question-history">
        <div className="oh-discovery-insight-title">
          <h3 id="assistant-question-history"><MessageSquare size={17} aria-hidden="true" />Recent assistant questions</h3>
          <span className="oh-discovery-count">Latest 20 · Last 7 days</span>
        </div>
        <p className="oh-discovery-description">Questions sent to your profile assistant. Common contact details are redacted; only you can see this history.</p>
        {questions.length ? (
          <ol className="oh-discovery-questions">
            {questions.map((question, index) => (
              <li key={`${question.asked_at}-${index}`}>
                <span className="oh-discovery-index">{String(index + 1).padStart(2, "0")}</span>
                <div className="oh-discovery-question-body">
                  <p>{question.question}{question.truncated && <span> … (shortened)</span>}</p>
                  <span className="oh-discovery-question-meta">
                    {TOPIC_LABELS[question.category] ?? question.category}
                    {question.asked_at && !Number.isNaN(Date.parse(question.asked_at)) && (
                      <> · <time dateTime={question.asked_at}>{new Date(question.asked_at).toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} UTC</time></>
                    )}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        ) : <p className="oh-discovery-empty">{activity.available ? "New assistant questions will appear here. Earlier question text was not saved." : "Question history is unavailable while activity collection is disabled or unreachable."}</p>}
      </section>

      <section className="oh-discovery-insight oh-discovery-history" aria-labelledby="recent-visitors">
        <div className="oh-discovery-insight-title">
          <h3 id="recent-visitors"><Eye size={17} aria-hidden="true" />People who visited</h3>
          <span className="oh-discovery-count">Last 7 days</span>
        </div>
        <p className="oh-discovery-description">Names appear only for signed-in visitors who chose to share them. Anonymous visits still count above.</p>
        {visitors?.available && visitors.items.length ? (
          <ul className="oh-discovery-topics">
            {visitors.items.map((visitor, index) => <li key={`${visitor.visited_at}-${index}`}>
              <div><span>{visitor.name}</span><span className="oh-discovery-count">{visitor.visits} {visitor.visits === 1 ? "visit" : "visits"}</span></div>
              <time className="oh-discovery-question-meta" dateTime={visitor.visited_at}>{new Date(visitor.visited_at).toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} UTC</time>
            </li>)}
          </ul>
        ) : <p className="oh-discovery-empty">{visitors?.available ? "No visitors have chosen to share their name in the last 7 days." : "Visitor names are unavailable. Anonymous view counts are independent."}</p>}
      </section>

      <footer className="oh-discovery-footer">
        <p>Counts reflect recorded requests, rather than unique people. Anonymous visitors stay private. Names appear only with consent.</p>
        <Link href={`${profile}/edit`}>Manage your card <ArrowUpRight size={14} aria-hidden="true" /></Link>
      </footer>
    </section>
  );
}
