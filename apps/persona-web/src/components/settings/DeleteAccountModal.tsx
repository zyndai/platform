"use client";

import { useState } from "react";
import { Button, Input } from "@/components/ui";

interface DeleteAccountModalProps {
  personaName: string;
  deleting: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function DeleteAccountModal({
  personaName,
  deleting,
  error,
  onCancel,
  onConfirm,
}: DeleteAccountModalProps) {
  const [typed, setTyped] = useState("");
  const canConfirm = typed.trim() === personaName && !deleting;

  return (
    <div className="modal-scrim" onClick={onCancel}>
      <div
        className="confirm-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="confirm-modal-header">
          <h3 className="display-s">Delete your account?</h3>
        </div>
        <div className="confirm-modal-body">
          <p className="body secondary" style={{ marginBottom: 14 }}>
            This removes everything — your brief, your conversations, your scheduled
            meetings. It can&apos;t be undone.
          </p>
          <p className="body-s" style={{ marginBottom: 14 }}>
            You can sign back in later with the same account, but you&apos;ll start fresh
            with a new identity.
          </p>
          <label className="field-label" htmlFor="delete-confirm-input">
            Type <strong>{personaName}</strong> to confirm
          </label>
          <Input
            id="delete-confirm-input"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={personaName}
            autoFocus
            disabled={deleting}
          />
          {error && (
            <p className="body-s" style={{ color: "var(--danger)", marginTop: 12 }}>
              {error}
            </p>
          )}
        </div>
        <div className="confirm-modal-footer">
          <Button variant="tertiary" onClick={onCancel} disabled={deleting}>
            Keep it
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={!canConfirm}
          >
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </div>
    </div>
  );
}
