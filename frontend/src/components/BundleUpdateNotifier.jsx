import { useEffect } from 'react';
import { useToast } from './Toast';

/**
 * Phase 10.1 W4 — stale-bundle update notifier.
 *
 * The service worker is registered with `registerType: 'autoUpdate'`, which
 * activates a new SW in the background but doesn't tell the user. The
 * controllerchange listener in main.jsx fires a CustomEvent
 * (`app:bundle-updated`) when a new SW takes control of the page; this
 * component surfaces that as a toast with a Refresh action.
 *
 * Mounted once at the App.jsx root so any tab can pick up the event.
 */
export default function BundleUpdateNotifier() {
  const toast = useToast();

  useEffect(() => {
    const handler = () => {
      toast.custom({
        message: 'A new version is available.',
        type: 'info',
        action: {
          label: 'Refresh',
          onClick: () => window.location.reload(),
        },
        duration: 30000,
      });
    };
    window.addEventListener('app:bundle-updated', handler);
    return () => window.removeEventListener('app:bundle-updated', handler);
  }, [toast]);

  return null;
}
