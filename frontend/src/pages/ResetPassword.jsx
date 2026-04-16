import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '../api';

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [status, setStatus] = useState(token ? 'form' : 'error'); // form, submitting, success, error
  const [error, setError] = useState(token ? '' : 'No reset token provided.');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setStatus('submitting');
    try {
      await api.post('/api/auth/reset-password', {
        token,
        new_password: password,
      });
      setStatus('success');
    } catch (err) {
      setError(err.message || 'Failed to reset password. The token may be invalid or expired.');
      setStatus('form');
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#F8F9FA] px-4">
      <div className="w-full max-w-md bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-4">Reset Password</h1>

        {status === 'success' ? (
          <div className="text-center">
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-green-700 mb-6">Your password has been reset successfully!</p>
            <Link
              to="/login"
              className="inline-block px-6 py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors"
            >
              Go to Login
            </Link>
          </div>
        ) : status === 'error' && !token ? (
          <div className="text-center">
            <p className="text-red-700 mb-6">{error}</p>
            <Link
              to="/login"
              className="inline-block px-6 py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors"
            >
              Go to Login
            </Link>
          </div>
        ) : (
          <div>
            <p className="text-gray-500 text-sm mb-6">
              Enter your new password below.
            </p>

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">New Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="••••••••"
                />
                <p className="mt-1 text-xs text-gray-400">Minimum 8 characters</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm Password</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="••••••••"
                />
              </div>
              <button
                type="submit"
                disabled={status === 'submitting'}
                className="w-full py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
              >
                {status === 'submitting' ? 'Resetting...' : 'Reset Password'}
              </button>
            </form>

            <div className="mt-4 text-center">
              <Link to="/login" className="text-sm text-[#2E75B6] hover:underline">
                Back to Login
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
