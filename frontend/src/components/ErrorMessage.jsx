/**
 * Reusable error display component.
 * Maps HTTP status codes to user-friendly messages.
 */
export default function ErrorMessage({ error, onRetry }) {
  let message = 'Something went wrong. Please try again.';

  if (error) {
    if (error.status === 0 || error.message?.includes('Network')) {
      message = 'Unable to connect. Check your connection and try again.';
    } else if (error.status === 403) {
      message = "You don't have permission to do this.";
    } else if (error.status === 404) {
      message = 'Not found.';
    } else if (error.status === 500) {
      message = 'Something went wrong. Please try again.';
    } else if (typeof error === 'string') {
      message = error;
    } else if (error.message) {
      message = error.message;
    }
  }

  return (
    <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg">
      <p className="text-sm">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 text-sm text-red-600 hover:text-red-800 underline"
        >
          Try again
        </button>
      )}
    </div>
  );
}
