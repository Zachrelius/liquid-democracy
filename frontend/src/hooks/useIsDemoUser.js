import { useAuth } from '../AuthContext';

/**
 * Phase 59 D1 — true when the current user is a demo-stamped identity.
 *
 * Demo personas are stamped by the demo-seed pipeline with
 * `verification_provenance='demo_stub'`; `backdoor` is the auxiliary
 * admin-test marker. Both should NOT be able to create real
 * organizations. Real users have `none` (pre-verification) or one of
 * the production provenances (`didit`, `persona`, etc.).
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
