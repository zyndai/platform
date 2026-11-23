import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Copy shared by the desktop canvas (1:1 Figma) and the mobile flow layout, so
 * the two can't drift. Layout-specific line breaks stay in each layout.
 */

export const NAV_LINKS = [
  { label: "Product", href: "#product" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Discover", href: "#discover" },
  { label: "FAQ", href: "#faq" },
];

export const HERO = {
  headline: ["Your Work Has a World", "Beyond Your Profile."],
  sub: "Turn what you build into a living identity, ready to be discovered.",
  urlLabel: "Your GitHub or LinkedIn URL",
  urlPlaceholder: "Paste your Github or Linkedin URL",
};

export const HOW_IT_WORKS = {
  headline: ["From your links", "to real opportunities."],
  intro:
    "In just a few steps, Zynd turns your existing online presence into a living profile — discoverable by people and AI agents.",
  steps: [
    { title: "Add your links", body: "Connect your GitHub, LinkedIn, portfolio or any URL that shows what you do." },
    { title: "Build your Identity", body: "Connect your GitHub, LinkedIn, portfolio or any URL that shows what you do." },
    {
      title: "Get Discovered",
      body: "Your profile becomes discoverable across the network — for people and AI agents looking for the right collaborators, creators and talent.",
    },
  ],
};

export const CTA_BANNER = {
  headline: ["Your next connection", "could be just a link away."],
  cta: "Create your Profile",
};

export const DISCOVER = {
  headline: ["Meet the right people.", "Not just followers."],
  body: "Discover collaborators, creators and fellow builders who share your interests, skills and goals — and actually want to work (or build) together.",
  cta: "Explore Networking",
};

export const MCP = {
  headline: ["Keep your profile", "updated in real time", "using MCP."],
  body: "Zynd connects with your tools and sources through the Model Context Protocol (MCP), so your profile stays fresh — automatically.",
  note: ["Auto-syncs across all", "your connected tools"],
  listTitle: "What MCP makes possible",
  features: [
    { title: "Auto-syncs your changes", body: "No more manual updates — your work, skills and achievements stay current." },
    { title: "Connects your favorite tools", body: "Integrates with GitHub, LinkedIn, Notion, Figma and more through MCP." },
    { title: "Real-time updates", body: "Get the latest changes, instantly, across your profile." },
    { title: "You stay in control", body: "Choose what to share, what to sync, and when." },
  ],
  cta: "Connect your tools",
};

export const EXPLORE = {
  headline: ["Explore what", "ZYND can do", "for you."],
  body: "From building your profile to finding opportunities, ZYND is your all-in-one companion for a bigger, brighter future.",
  cta: "Create your Profile",
  items: [
    { title: "Build Your Profile", body: "Showcase your skills, interests, and personality to get noticed." },
    { title: "Discover Opportunities", body: "Find jobs, projects, and experiences that match your goals." },
    { title: "Connect with People", body: "Meet like-minded individuals and grow your network." },
    { title: "Learn & Grow", body: "Access resources, tips, and personalized guidance." },
    { title: "Track Your Progress", body: "Set goals and celebrate your milestones." },
    { title: "Unlock New Paths", body: "From education to career, ZYND helps you go further." },
  ],
};

export const FAQ_HEADLINE = ["Got questions?", "We’ve got answers"];

export const FAQ_SUPPORT = {
  title: "Still have questions?",
  body: "Our support team is here to help.",
  cta: "Contact Support",
};

export type Faq = { question: string; answer: ReactNode };

export const FAQS: Faq[] = [
  {
    question: "What is Zynd ?",
    answer:
      "Zynd turns your GitHub, LinkedIn, X and website into one living professional profile: browsable by people and searchable by AI agents.",
  },
  {
    question: "Is ZYND free to use?",
    answer: "Yes. Creating, editing and publishing your Zynd card is free.",
  },
  {
    question: "How do I create a portfolio?",
    answer:
      "Paste your GitHub or LinkedIn URL. Zynd reads your public work and drafts your profile in about a minute; review it, edit anything, then publish.",
  },
  {
    question: "Can I find job opportunities on ZYND?",
    answer:
      "Your profile becomes discoverable across the network, for people and AI agents looking for the right collaborators, creators and talent.",
  },
  {
    question: "How do I get support?",
    answer: (
      <>
        Visit our <Link href="/support" className="underline underline-offset-2">support page</Link> or email{" "}
        <a href="mailto:contact@zynd.ai" className="underline underline-offset-2">contact@zynd.ai</a>.
      </>
    ),
  },
];

/** Product section feature pills (label + one-liner), in reading order. */
export const PRODUCT_FEATURES = [
  { key: "showcase", title: "Showcase", body: "Your work, projects, and achievements." },
  { key: "connect", title: "Connect", body: "Link your GitHub, LinkedIn, portfolio and more." },
  { key: "collaborate", title: "Collaborate", body: "Get found by the right people and opportunities." },
  { key: "skills", title: "Skills", body: "Let your skills speak for you." },
  { key: "ai", title: "AI Discovery", body: "Be matched with collaborators, creators and opportunities." },
  { key: "opportunities", title: "Opportunities", body: "More visibility. More possibilities." },
] as const;

export const PRODUCT_CTA = "Make your own";
