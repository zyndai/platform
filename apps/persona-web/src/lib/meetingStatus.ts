/**
 * Human-facing meeting-status labels and timeline helpers.
 *
 * The backend uses a state machine (proposed → countered → accepted →
 * scheduled; plus declined/cancelled/book_failed). The UI should describe
 * those states from the current user's point of view.
 */

export type MeetingTicketStatus =
  | "proposed"
  | "countered"
  | "accepted"
  | "scheduled"
  | "declined"
  | "cancelled"
  | "book_failed";

export interface MeetingStatusContext {
  status: MeetingTicketStatus;
  /** True when the next required action is the current user's. */
  awaitingMe: boolean;
  /** True when the current user created/initiated the proposal. */
  iProposed: boolean;
}

const LABELS: Record<MeetingTicketStatus, string> = {
  proposed: "Proposed",
  countered: "Countered",
  accepted: "Accepted",
  scheduled: "Confirmed",
  declined: "Declined",
  cancelled: "Cancelled",
  book_failed: "Booking failed",
};

export function meetingStatusLabel(ctx: MeetingStatusContext): string {
  const { status, awaitingMe, iProposed } = ctx;

  switch (status) {
    case "proposed":
      if (awaitingMe) return "Waiting for your reply";
      if (iProposed) return "Request sent";
      return "Proposal received";

    case "countered":
      if (awaitingMe) return "Counter waiting for your reply";
      return iProposed ? "Waiting for their reply" : "Waiting for their reply";

    case "accepted":
      return "Accepted · booking calendars";

    case "scheduled":
      return "Confirmed";

    case "book_failed":
      return "Booking failed";

    case "declined":
      return "Declined";

    case "cancelled":
      return "Cancelled";
  }
}

export const MEETING_STATUS_LABELS = LABELS;

export type TimelineStepState = "done" | "active" | "pending";

export interface MeetingTimelineStep {
  label: string;
  state: TimelineStepState;
}

export function meetingTimeline(ctx: MeetingStatusContext): MeetingTimelineStep[] {
  const { status, awaitingMe, iProposed } = ctx;

  switch (status) {
    case "proposed":
      return [
        { label: iProposed ? "Request sent" : "They proposed", state: "active" },
        { label: awaitingMe ? "Waiting for you" : "Waiting for them", state: "pending" },
        { label: "Confirmed", state: "pending" },
      ];

    case "countered":
      return [
        { label: iProposed ? "Request sent" : "They proposed", state: "done" },
        { label: iProposed ? "You countered" : "They countered", state: "active" },
        { label: awaitingMe ? "Waiting for you" : "Waiting for them", state: "pending" },
      ];

    case "accepted":
      return [
        { label: "Proposed", state: "done" },
        { label: "Accepted", state: "done" },
        { label: "Booking calendars", state: "active" },
      ];

    case "scheduled":
      return [
        { label: "Proposed", state: "done" },
        { label: "Accepted", state: "done" },
        { label: "Confirmed", state: "active" },
      ];

    case "book_failed":
      return [
        { label: "Proposed", state: "done" },
        { label: "Accepted", state: "done" },
        { label: "Booking failed", state: "active" },
      ];

    case "declined":
      return [
        { label: "Proposed", state: "done" },
        { label: "Declined", state: "active" },
      ];

    case "cancelled":
      return [
        { label: "Proposed", state: "done" },
        { label: "Cancelled", state: "active" },
      ];
  }
}
