// Phase 10.1 W3 — In-app PWA install banner.
//
// Gentle, mobile-only, dismissible-forever affordance for installing the
// Liquid Democracy PWA. Background: Phase 10 shipped the manifest + SW + offline
// page correctly, but the install path on iOS is "Share -> Add to Home Screen"
// and on Android Chrome it's a browser-driven banner — neither of which most
// users discover on their own.
//
// Render conditions (all must be true):
//   1. localStorage.getItem('pwa_install_dismissed') !== '1'  (never dismissed)
//   2. window.matchMedia('(display-mode: standalone)').matches === false
//      (not already installed)
//   3. window.innerWidth < 768  (mobile only — same breakpoint as Tailwind md:)
//
// Two install paths:
//   - Android Chrome / desktop Chrome: capture `beforeinstallprompt`, then
//     call event.prompt() on Install button click.
//   - iOS Safari (no beforeinstallprompt available): show inline help popover
//     with Share -> Add to Home Screen instructions.
//
// Dismiss persists to localStorage forever — never re-appears once dismissed
// on that device. Per design decision 5, this is intentionally NOT a nag-loop.
import { useState, useEffect } from 'react';

const STORAGE_KEY = 'pwa_install_dismissed';

export default function InstallPWABanner() {
  const [visible, setVisible] = useState(false);
  const [installEvent, setInstallEvent] = useState(null);
  const [showIosHelp, setShowIosHelp] = useState(false);

  useEffect(() => {
    // Already dismissed on this device?
    if (localStorage.getItem(STORAGE_KEY) === '1') return;
    // Already running as installed PWA?
    if (
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(display-mode: standalone)').matches
    ) {
      return;
    }
    // Mobile viewport only? Use the same breakpoint Tailwind uses for `md`.
    if (window.innerWidth >= 768) return;

    setVisible(true);

    // Capture beforeinstallprompt for Android Chrome / desktop Chrome path.
    // Browser fires this when the page meets PWA install criteria; calling
    // preventDefault stashes the event so we can prompt() later from a user
    // gesture (the Install button click).
    const handler = (e) => {
      e.preventDefault();
      setInstallEvent(e);
    };
    window.addEventListener('beforeinstallprompt', handler);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  const dismiss = () => {
    try {
      localStorage.setItem(STORAGE_KEY, '1');
    } catch (e) {
      // localStorage can throw in Safari private mode — fail silently and
      // just hide the banner for the session.
    }
    setVisible(false);
  };

  const install = () => {
    if (installEvent) {
      installEvent.prompt();
      installEvent.userChoice.then(() => {
        // Whether user accepted or dismissed the native prompt, hide the
        // banner. They can re-install via browser menu later if needed.
        dismiss();
      });
    } else {
      // iOS Safari path — no beforeinstallprompt available, so surface
      // inline help with Share -> Add to Home Screen instructions.
      setShowIosHelp(true);
    }
  };

  if (!visible) return null;

  return (
    <div className="fixed bottom-0 inset-x-0 z-40 bg-[var(--brand-primary)] text-white px-4 py-3 shadow-lg flex items-center gap-3">
      <span className="flex-1 text-sm">
        Install Liquid Democracy as an app
      </span>
      <button
        type="button"
        onClick={install}
        className="px-3 py-1.5 bg-white text-[var(--brand-primary)] rounded font-semibold text-sm"
      >
        Install
      </button>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="text-white/80 hover:text-white text-xl leading-none px-1"
      >
        ×
      </button>
      {showIosHelp && (
        <div className="absolute bottom-full inset-x-0 mb-2 mx-3 bg-white text-gray-900 rounded-lg shadow-lg p-4 text-sm">
          <p className="font-semibold mb-2">To install on iOS:</p>
          <p>
            Tap the Share icon{' '}
            <span aria-hidden="true">⬆️</span>
            {' '}at the bottom of Safari, then choose{' '}
            <strong>Add to Home Screen</strong>.
          </p>
          <button
            type="button"
            onClick={() => setShowIosHelp(false)}
            className="mt-3 text-xs text-gray-500 underline"
          >
            Got it
          </button>
        </div>
      )}
    </div>
  );
}
