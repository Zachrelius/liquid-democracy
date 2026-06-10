// Phase 43 Cluster F (2026-05-30) — promoted from Login.jsx where it lived
// since Phase 14 F2. Same-origin relative-path validator used by Login,
// VerifyEmail, and any future caller that consumes a `?next=` query param.
//
// Rejects: non-strings; non-leading-slash strings; protocol-relative (`//`)
// values that browsers interpret as off-site. Accepts: any leading-slash
// path under the same origin (e.g., `/orgs/create`, `/cedar-hollow/proposals`).
// On rejection, callers should fall back to their default post-auth landing
// rather than redirect anywhere — the goal is to not silently navigate to
// an unsafe target, not to error.
export function resolveNext(rawNext) {
  if (typeof rawNext !== 'string') return null;
  if (!rawNext.startsWith('/')) return null;
  // Reject protocol-relative targets in both slash flavors: browsers
  // normalize backslashes in URL resolution, so `/\evil.com` becomes
  // `//evil.com` (Phase 63 hardening).
  if (/^\/[\\/]/.test(rawNext)) return null;
  return rawNext;
}

export default resolveNext;
