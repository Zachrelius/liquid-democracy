import { useState } from 'react';
import { useAuth } from '../AuthContext';
import api from '../api';

/**
 * Phase 9.8 W B2 — small inline note rendered next to disabled vote/delegate
 * controls when the current user hasn't verified their email. Mirrors the
 * resend action surfaced by ``EmailVerificationBanner`` so the user can
 * unblock without scrolling back to the top banner.
 *
 * Props:
 *   action — short verb to interpolate, e.g. 'vote' or 'delegate'.
 *   className — optional extra wrapper classes.
 */
export default function VerifyEmailInlineNote({ action = 'continue', className = '' }) {
  const { refreshUser } = useAuth();
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  async function handleResend() {
    setSending(true);
    setError('');
    setSent(false);
    try {
      await api.post('/api/auth/resend-verification', {});
      setSent(true);
      // In case the user verified in another tab between page load and this
      // click — pick up the new state so the disabled buttons re-enable.
      await refreshUser();
    } catch (e) {
      setError(e.message || 'Failed to send verification email');
    } finally {
      setSending(false);
    }
  }

  return (
    <span className={`text-xs text-amber-700 ${className}`}>
      Verify your email to {action}.
      {' '}
      {sent ? (
        <span className="text-green-700">Verification email sent.</span>
      ) : (
        <button
          type="button"
          onClick={handleResend}
          disabled={sending}
          className="underline hover:text-amber-900 disabled:opacity-50"
        >
          {sending ? 'Sending…' : 'Resend verification email'}
        </button>
      )}
      {error && <span className="text-red-600 ml-1">{error}</span>}
    </span>
  );
}
