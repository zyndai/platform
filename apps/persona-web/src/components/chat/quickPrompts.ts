import {
  Sparkles,
  Eye,
  MessageCircle,
  CalendarPlus,
  type LucideIcon,
} from "lucide-react";

export type QuickPrompt = {
  label: string;
  send: string;
  icon: LucideIcon;
  tone: "amber" | "blue" | "green" | "pink";
};

export const QUICK_PROMPTS: QuickPrompt[] = [
  {
    label: "Find people to meet",
    send: "Show me who's worth meeting.",
    icon: Sparkles,
    tone: "amber",
  },
  {
    label: "What's on my radar",
    send: "What's on your radar today?",
    icon: Eye,
    tone: "blue",
  },
  {
    label: "Think out loud",
    send: "I want to think out loud about something.",
    icon: MessageCircle,
    tone: "green",
  },
  {
    label: "Schedule a meeting",
    send: "Help me schedule a meeting with one of my contacts.",
    icon: CalendarPlus,
    tone: "pink",
  },
];
