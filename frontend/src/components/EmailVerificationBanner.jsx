import { useState } from 'react';
import { useAuth } from '../AuthContext';
import api from '../api';

export default function EmailVerificationBanner() {
  const { user, refreshUser } = useAuth();
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  if (!user || user.email_verified) return null;

  async function handleResend() {
    setSending(true);
    setError('');
    setSent(false);
    try {
      await api.post('/api/auth/resend-verification', {});
      setSent(true);
      // Refresh user data in case verification happened
      await refreshUser();
    } catch (err) {
      setError(err.message || 'Failed to send verification email');
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-3">
      <div className="max-w-6xl mx-auto flex items-center justify-between flex-wrap gap-2">
        <p className="text-amber-800 text-sm">
          Please verify your email to participate in votes and create delegations.
        </p>
        <div className="flex items-center gap-3">
          {sent && (
            <span className="text-green-700 text-xs">Verification email sent!</span>
          )}
          {error && (
            <span className="text-red-700 text-xs">{error}</span>
          )}
          <button
            onClick={handleResend}
            disabled={sending}
            className="text-sm text-amber-800 underline hover:text-amber-900 disabled:opacity-50"
          >
            {sending ? 'Sending...' : 'Resend verification email'}
          </button>
        </div>
      </div>
    </div>
  );
}
