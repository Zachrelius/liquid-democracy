import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useToast } from './Toast';
import { useIsDemoPersona } from '../hooks/useIsDemoUser';

/**
 * Phase 79 — shared fence message. Used by this app-level guard (Layer 1)
 * and by OrgScopedLayout's org-resolution guard (Layer 2) so both surfaces
 * speak with one voice.
 */
export const DEMO_FENCE_MESSAGE =
  'Demo sessions are limited to demo organizations. Create an account to explore the full platform.';

/**
 * Phase 79 — Layer 1 app-level demo session fence.
 *
 * Demo personas (verification_provenance demo_stub) get a real JWT on
 * demo login but should only roam demo orgs + account settings. Note we
 * fence demo_stub ONLY (useIsDemoPersona), not backdoor: backdoor marks
 * real admin-verified users who legitimately belong to real orgs.
 * When a demo user lands on a route that implies real-org participation or
 * recruitment, log them out, redirect to /demo, and explain via toast.
 *
 * This guard owns the small set of fixed trigger routes (`/`, `/explore`,
 * `/orgs/create`, `/setup`). Whether a `/:org_slug/*` path points at a real
 * org is Layer 2's job (OrgScopedLayout), because it needs the resolved
 * OrgContext to know `is_demo`.
 *
 * Mounted inside AuthProvider + ToastProvider in App.jsx, so it can consume
 * useAuth/useToast; inside the Router so it can consume useLocation/navigate.
 * Renders nothing.
 */
export default function DemoUserGuard() {
  const isDemoUser = useIsDemoPersona();
  const { logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  // Guard against double-firing the async logout for one trigger (React
  // StrictMode double-invokes effects in dev; also belt-and-suspenders if
  // the effect re-runs before logout clears the demo identity).
  const firedRef = useRef(false);

  useEffect(() => {
    if (!isDemoUser) {
      firedRef.current = false;
      return;
    }
    const p = location.pathname;
    const isTrigger =
      p === '/' ||
      p === '/explore' || p.startsWith('/explore/') ||
      p === '/orgs/create' || p.startsWith('/orgs/create/') ||
      p === '/setup' || p.startsWith('/setup/');
    if (!isTrigger || firedRef.current) return;
    firedRef.current = true;
    (async () => {
      // logout() clears tokens + user, then navigates to /login. Await it
      // so our /demo redirect lands last (replace so the /login bounce
      // doesn't linger in history).
      await logout();
      toast.info(DEMO_FENCE_MESSAGE);
      navigate('/demo', { replace: true });
    })();
  }, [isDemoUser, location.pathname, logout, navigate, toast]);

  return null;
}
