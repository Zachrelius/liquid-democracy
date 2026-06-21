import { useAuth } from '../AuthContext';

/**
 * Phase 59 D1 — true when the current user is restricted from creating
 * real organizations: the demo-seeded personas (``demo_stub``) AND the
 * ``backdoor`` admin-verification marker.
 *
 * This hook is paired with the backend create-org gate
 * (routes/organizations.py), which 403s BOTH provenances by deliberate
 * Phase 59 decision (test_phase_59_demo_user_org_guard.py). Use it ONLY
 * to hide/alter the create-org affordance so the FE doesn't surface a
 * control the backend will reject. Do NOT use it for session fencing /
 * auto-logout — ``backdoor`` marks REAL users an admin verified via the
 * verification-state endpoint (routes/admin.py), and they legitimately
 * belong to real orgs. For fencing, use ``useIsDemoPersona`` below.
 *
 * Returns false when there's no user (logged out) so a logged-out
 * visitor still sees the CTA + can register before creating an org.
 */
export function useIsDemoUser() {
  const { user } = useAuth();
  if (!user) return false;
  const prov = user.verification_provenance;
  return prov === 'demo_stub' || prov === 'backdoor';
}

/**
 * Phase 79 — true ONLY for genuine demo personas (``demo_stub``), the
 * accounts the demo seed pipeline creates inside demo orgs. This is the
 * narrow identity used by the demo session fence (DemoUserGuard +
 * OrgScopedLayout): those guards log the user out of real-org and
 * recruitment routes, so they must NOT fire for ``backdoor`` — a real
 * user verified via the admin tool — or they'd kick real members out of
 * their own orgs. ``backdoor`` is intentionally excluded here.
 *
 * Returns false when logged out.
 */
export function useIsDemoPersona() {
  const { user } = useAuth();
  if (!user) return false;
  return user.verification_provenance === 'demo_stub';
}
