import { useRef, useState } from 'react';
import api from '../api';
import { useToast } from './Toast';
import useModalDialog from '../hooks/useModalDialog';

/**
 * Phase 86 (B-4) — content report modal.
 *
 * Reason picker + optional note + submit. Neutral copy, no loud framing.
 * States clearly that the report is visible to the org's moderators (and,
 * by omission, to no one else). Reports are signal only — submitting one
 * never hides or actions anything.
 *
 * Props:
 *   targetType — 'comment' | 'proposal'
 *   targetId   — id of the reported content
 *   onClose    — close callback
 */
const REASONS = [
  { value: 'spam', label: 'Spam or advertising' },
  { value: 'harassment', label: 'Harassment or abuse' },
  { value: 'misleading', label: 'Misleading or false' },
  { value: 'other', label: 'Something else' },
];

const NOTE_MAX = 500;

export default function ReportModal({ targetType, targetId, onClose }) {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const cancelRef = useRef(null);
  const dialogRef = useModalDialog({ onClose: submitting ? undefined : onClose, initialFocusRef: cancelRef });

  async function handleSubmit() {
    if (!reason) {
      toast.error('Please choose a reason');
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.post('/api/reports', {
        target_type: targetType,
        target_id: targetId,
        reason,
        note: note.trim() || undefined,
      });
      if (res && res.already_open) {
        toast.success('You have already reported this. Thanks.');
      } else {
        toast.success('Report submitted. Thank you.');
      }
      onClose?.();
    } catch (e) {
      toast.error(e?.message || 'Could not submit report');
    } finally {
      setSubmitting(false);
    }
  }

  const label = targetType === 'proposal' ? 'proposal' : 'comment';

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={submitting ? undefined : onClose} aria-hidden="true" />
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="report-dialog-title" aria-describedby="report-dialog-description" tabIndex={-1} className="relative bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6 space-y-4">
        <h3 id="report-dialog-title" className="text-lg font-semibold text-gray-800">Report this {label}</h3>
        <p id="report-dialog-description" className="text-sm text-gray-600">
          Tell this organization&apos;s moderators why. Your report is visible to
          this organization&apos;s moderators.
        </p>

        <fieldset className="space-y-2">
          <legend className="text-xs font-medium text-gray-600 mb-1">Choose a reason</legend>
          {REASONS.map((r) => (
            <label key={r.value} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="radio"
                name="report-reason"
                value={r.value}
                checked={reason === r.value}
                onChange={() => setReason(r.value)}
              />
              <span>{r.label}</span>
            </label>
          ))}
        </fieldset>

        <div>
          <label htmlFor="report-note" className="block text-xs text-gray-500 mb-1">
            Add a note (optional)
          </label>
          <textarea
            id="report-note"
            value={note}
            onChange={(e) => setNote(e.target.value.slice(0, NOTE_MAX))}
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
            placeholder="Anything the moderators should know"
          />
          <div className="text-right text-xs text-gray-400">{note.length} / {NOTE_MAX}</div>
        </div>

        <div className="flex justify-end gap-3 pt-1">
          <button
            ref={cancelRef}
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || !reason}
            className="text-sm px-4 py-2 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Submitting…' : 'Submit report'}
          </button>
        </div>
      </div>
    </div>
  );
}
