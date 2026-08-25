import { useRef } from 'react';
import useModalDialog from '../hooks/useModalDialog';
import { formatMembershipVerificationRequirements } from '../verificationLabels';

export default function VerificationJoinDialog({
  open,
  organizationName,
  detail,
  onClose,
  onGoToVerification,
}) {
  const primaryRef = useRef(null);
  const dialogRef = useModalDialog({ open, onClose, initialFocusRef: primaryRef });
  const presentation = formatMembershipVerificationRequirements(detail);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center px-4 py-6">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="verification-join-dialog-title"
        aria-describedby="verification-join-dialog-description"
        tabIndex={-1}
        className="relative max-h-full w-full max-w-lg overflow-y-auto rounded-xl bg-white p-5 shadow-xl sm:p-6"
      >
        <h2
          id="verification-join-dialog-title"
          className="text-xl font-semibold text-[var(--brand-primary)]"
        >
          Identity verification required
        </h2>
        <p id="verification-join-dialog-description" className="mt-3 text-sm text-gray-700">
          To join {organizationName || 'this organization'}, you need to verify a government-issued ID.
        </p>

        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-gray-700">
          {presentation.requirements.map((requirement) => (
            <li key={requirement}>{requirement}</li>
          ))}
        </ul>

        <p className="mt-4 text-sm text-gray-600">
          Identity verification is completed securely through Didit.{' '}
          <a
            href="https://didit.me/terms/privacy-policy/"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-[var(--brand-accent)] underline"
          >
            Didit&apos;s privacy policy
          </a>
        </p>

        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Not now
          </button>
          <button
            ref={primaryRef}
            type="button"
            onClick={onGoToVerification}
            className="rounded-lg bg-[var(--brand-primary)] px-4 py-2 text-sm text-white hover:bg-[var(--brand-accent)]"
          >
            Go to identity verification
          </button>
        </div>
      </div>
    </div>
  );
}
