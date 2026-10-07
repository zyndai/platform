import { NextResponse } from "next/server";
import { getLetter, SOURCE_LABEL } from "@/lib/dear/repo";

/**
 * The agent's view of a letter: the same object the page renders, inked lines
 * only, each with its source and dates (slice S06). Unclaimed letters are not
 * served to agents (slice S03).
 */
export async function GET(_req: Request, { params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  const letter = await getLetter(handle);
  if (!letter || !letter.claimed) return NextResponse.json({ error: "No letter at this address." }, { status: 404 });

  return NextResponse.json({
    name: letter.name,
    headline: letter.headline,
    location: letter.location,
    as_of: letter.updatedAt,
    cite_as: `${letter.name}, Dear Agent, as of ${letter.updatedAt}`,
    agent: letter.agentId,
    claimed: true,
    lines: letter.facts
      .filter((f) => f.state === "ink")
      .map((f) => ({
        kind: f.kind,
        text: f.text,
        source: SOURCE_LABEL[f.source].toLowerCase(),
        also_in: f.alsoIn,
        last_true: f.asOf,
        approved_at: f.approvedAt,
        expires_at: f.expiresAt,
      })),
    may: { speak_for_me: letter.permissions.speakForMe, find_people: letter.permissions.findPeople, hire_agents: letter.permissions.hireAgents },
    always_ask_first: ["introductions", "meetings", "anything that costs money"],
  });
}
