export const introsEnabled = process.env.NEXT_PUBLIC_FEATURE_S12_INTROS === "true";

export interface Intro {
  id: string;
  handle: string;
  requester_uid: string;
  owner_uid: string;
  requester_name: string;
  owner_name: string;
  why: string;
  asks: string[];
  permissions: { can_request_meetings?: boolean };
  status: string;
  thread_id: string;
  meeting_task_id: string | null;
  conversation_url: string;
  created_at: string;
}
