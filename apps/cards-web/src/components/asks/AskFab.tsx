"use client";

import { Plus } from "lucide-react";
import { ASK_FAB_ID } from "./AskComposer";

/** The floating Post button on the feed. Fixed bottom right, above the phone's safe area; the page
 *  leaves room under the list so it never covers the last item or "Load more". */
export function AskFab({ onClick }: { onClick: () => void }) {
  return (
    <button id={ASK_FAB_ID} type="button" className="ac-fab" aria-label="Post an ask" aria-haspopup="dialog" onClick={onClick}>
      <Plus size={20} aria-hidden="true" /> Post
    </button>
  );
}
