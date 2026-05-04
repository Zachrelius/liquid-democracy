/**
 * Phase 12 Stage 2 — Role Permissions matrix page (Cluster F).
 *
 * Renders a permissions × roles matrix the org's "Steward" or "Admin"
 * (anyone with `role_permissions.edit`) can edit. Members without that
 * permission see the same matrix in read-only mode (F6) — the route is
 * NOT gated by AdminRoute so direct navigation lands on the read-only
 * view rather than a 403.
 *
 * Data sources:
 *   GET /api/permissions/registry          (Stage 1, 24 keys + categories)
 *   GET /api/orgs/{slug}/role-permissions  (Stage 2 B1, current matrix +
 *                                           locked-cells map)
 *   PATCH /api/orgs/{slug}/role-permissions (Stage 2 B2, applies cell-level
 *                                           changes; returns updated matrix)
 *
 * Save flow (F3):
 *   - Pending changes accumulate in a Map keyed by `role:permission`.
 *   - Toggling a cell back to its server value drops the entry (so a
 *     toggle-then-untoggle saves nothing).
 *   - Save opens a confirmation modal with a grant/revoke breakdown,
 *     PATCHes the changes, replaces serverMatrix from the response, and
 *     toasts on success or error.
 *
 * Out-of-band sync (F4): not implemented — last-writer-wins on backend
 * is fine for friend-pilot scale.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import ErrorMessage from '../../components/ErrorMessage';

// Display order is taken from the server's `roles` array (each role has
// `display_order`). We re-derive it here as a fallback so the table still
// renders in a sensible order if the server payload is somehow incomplete.
const ROLE_ORDER_FALLBACK = ['steward', 'admin', 'moderator', 'member'];

function lockKey(roleSystemKey, permissionKey) {
  return `${roleSystemKey}:${permissionKey}`;
}

export default function RolePermissionsPage() {
  const { currentOrg } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();

  // Whether the current user can edit the matrix. Tier shortcut per spec
  // (F6): admin or steward (matches DEFAULT_GRANTS for role_permissions.edit).
  // The legacy 'owner' system_key is also accepted for safety during deploy
  // cutover, mirroring OrgContext's isAdmin/isOwner derivation.
  const canEdit = !!(
    currentOrg &&
    (currentOrg.user_role === 'steward' ||
      currentOrg.user_role === 'admin' ||
      currentOrg.user_role === 'owner')
  );

  const [registry, setRegistry] = useState(null);    // {permissions:[], categories:[]}
  const [serverMatrix, setServerMatrix] = useState(null); // full B1 payload
  const [pendingChanges, setPendingChanges] = useState(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setError(null);
    try {
      // Fetch in parallel — the two endpoints are independent.
      const [reg, matrix] = await Promise.all([
        api.get('/api/permissions/registry'),
        api.get(`/api/orgs/${slug}/role-permissions`),
      ]);
      setRegistry(reg);
      setServerMatrix(matrix);
      setPendingChanges(new Map());
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { load(); }, [load]);

  // Locked-cell lookup. Keyed by `role:permission`; value is `true` when the
  // cell is hardcoded TRUE and not user-editable.
  const lockedSet = useMemo(() => {
    const set = new Set();
    if (!serverMatrix?.locked) return set;
    for (const [role, keys] of Object.entries(serverMatrix.locked)) {
      for (const k of keys) set.add(lockKey(role, k));
    }
    return set;
  }, [serverMatrix]);

  // Roles to render as columns, in display_order. Falls back to a fixed
  // order when serverMatrix is missing fields (defensive — not expected).
  const roles = useMemo(() => {
    if (!serverMatrix?.roles?.length) {
      return ROLE_ORDER_FALLBACK.map(k => ({ system_key: k, name: k }));
    }
    return [...serverMatrix.roles].sort(
      (a, b) => (a.display_order ?? 99) - (b.display_order ?? 99),
    );
  }, [serverMatrix]);

  // Permissions grouped by category in the canonical order from the
  // registry (the server preserves insertion order in CATEGORIES).
  const groupedPermissions = useMemo(() => {
    if (!registry?.permissions) return [];
    const byCat = new Map();
    for (const perm of registry.permissions) {
      if (!byCat.has(perm.category)) byCat.set(perm.category, []);
      byCat.get(perm.category).push(perm);
    }
    // Order categories by registry.categories; any unknown trailing.
    const ordered = [];
    const cats = registry.categories || [];
    for (const cat of cats) {
      if (byCat.has(cat)) {
        ordered.push({ category: cat, permissions: byCat.get(cat) });
        byCat.delete(cat);
      }
    }
    for (const [cat, perms] of byCat.entries()) {
      ordered.push({ category: cat, permissions: perms });
    }
    return ordered;
  }, [registry]);

  // Display value for a (role, permission) cell: pending change if any,
  // otherwise serverMatrix; default false if unknown.
  function displayValue(roleKey, permKey) {
    const k = lockKey(roleKey, permKey);
    if (pendingChanges.has(k)) return pendingChanges.get(k);
    const cell = serverMatrix?.permissions?.[permKey];
    return !!cell?.[roleKey];
  }

  function serverValue(roleKey, permKey) {
    const cell = serverMatrix?.permissions?.[permKey];
    return !!cell?.[roleKey];
  }

  function handleToggle(roleKey, permKey) {
    if (!canEdit) return;
    const k = lockKey(roleKey, permKey);
    if (lockedSet.has(k)) return; // belt-and-suspenders; no onChange wired anyway
    const newValue = !displayValue(roleKey, permKey);
    const sv = serverValue(roleKey, permKey);
    setPendingChanges(prev => {
      const next = new Map(prev);
      if (newValue === sv) {
        // Toggled back to the server value — drop the pending entry so a
        // toggle-then-untoggle is a true no-op.
        next.delete(k);
      } else {
        next.set(k, newValue);
      }
      return next;
    });
  }

  async function handleSave() {
    if (pendingChanges.size === 0) return;

    // Build a grant/revoke breakdown for the confirmation modal copy.
    let grants = 0;
    let revokes = 0;
    for (const v of pendingChanges.values()) {
      if (v) grants += 1; else revokes += 1;
    }
    const total = pendingChanges.size;
    const breakdown =
      `${grants} permission${grants === 1 ? '' : 's'} will be granted, ` +
      `${revokes} will be revoked.`;

    const ok = await confirm({
      title: 'Save permission changes?',
      message:
        `You are about to change ${total} role permission${total === 1 ? '' : 's'} ` +
        `in ${currentOrg?.name || 'this organization'}. ${breakdown} Continue?`,
    });
    if (!ok) return;

    const changes = Array.from(pendingChanges.entries()).map(([key, enabled]) => {
      const [role_system_key, permission_key] = key.split(':');
      return { role_system_key, permission_key, enabled };
    });

    setSaving(true);
    try {
      const resp = await api.patch(
        `/api/orgs/${slug}/role-permissions`,
        { changes },
      );
      // The B2 response includes the full updated matrix in the same shape
      // as B1 (org_id, org_slug, roles, permissions, locked).
      setServerMatrix(resp);
      setPendingChanges(new Map());
      const applied = resp?.changes_applied ?? changes.length;
      toast.success(
        `Permissions updated. ${applied} change${applied === 1 ? '' : 's'} saved.`,
      );
    } catch (e) {
      // Defense in depth: a 400 from the server about a locked cell
      // shouldn't normally surface here (the UI doesn't render an editable
      // checkbox for locked cells), but if it does, name the case explicitly.
      if (e?.status === 400 && /locked/i.test(e?.message || '')) {
        toast.error(`Some changes were rejected by the server: ${e.message}`);
      } else {
        toast.error(e?.message || 'Failed to save permissions.');
      }
      // Leave pendingChanges intact so the user can retry or modify.
    } finally {
      setSaving(false);
    }
  }

  async function handleDiscard() {
    if (pendingChanges.size === 0) return;
    const ok = await confirm({
      title: 'Discard unsaved changes?',
      message:
        `Discard ${pendingChanges.size} unsaved change${pendingChanges.size === 1 ? '' : 's'}? ` +
        'This cannot be undone.',
      destructive: true,
    });
    if (!ok) return;
    setPendingChanges(new Map());
  }

  // ---------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------

  if (!currentOrg) {
    return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8">
        <ErrorMessage error={error} onRetry={load} />
      </div>
    );
  }

  const pendingCount = pendingChanges.size;
  const headerSuffix = canEdit ? '' : ' (read-only)';

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Header (D1 verbatim copy) */}
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
          Role Permissions for {currentOrg.name}{headerSuffix}
        </h1>
        <div className="bg-white border border-gray-200 rounded-xl p-5 text-sm text-gray-700 space-y-3">
          <p>
            Each member of your organization has a role: Steward, Admin,
            Moderator, or Member. This page controls which actions each role
            can perform.
          </p>
          <p>
            Some Steward permissions are locked because they&apos;re required
            to keep your organization configurable. The Steward will always be
            able to manage roles, edit organization settings, and edit this
            page itself.
          </p>
          <p>
            Changes are saved when you click &ldquo;Save changes&rdquo; and are
            recorded in the org&apos;s audit log.
          </p>
        </div>
      </div>

      {/* Matrix table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Permission
                </th>
                {roles.map(r => (
                  <th
                    key={r.system_key}
                    className="text-center px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-32"
                  >
                    {r.name || r.system_key}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groupedPermissions.map(({ category, permissions }) => (
                <CategorySection
                  key={category}
                  category={category}
                  permissions={permissions}
                  roles={roles}
                  displayValue={displayValue}
                  serverValue={serverValue}
                  lockedSet={lockedSet}
                  pendingChanges={pendingChanges}
                  canEdit={canEdit}
                  onToggle={handleToggle}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Footer — save / discard / counter. Hidden in read-only mode (F6). */}
      {canEdit && (
        <div className="flex items-center gap-3 pb-4">
          <button
            onClick={handleSave}
            disabled={saving || pendingCount === 0}
            className="px-6 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : 'Save changes'}
          </button>
          <button
            onClick={handleDiscard}
            disabled={saving || pendingCount === 0}
            className="px-4 py-2 border border-gray-300 text-gray-600 text-sm rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Discard changes
          </button>
          <span className="text-sm text-gray-500" aria-live="polite">
            {pendingCount} pending change{pendingCount === 1 ? '' : 's'}
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * One category section in the table — a header row plus the permission
 * rows that belong to it. Pulled out so the table-cell logic stays close
 * to the parent without bloating the main render.
 */
function CategorySection({
  category,
  permissions,
  roles,
  displayValue,
  serverValue,
  lockedSet,
  pendingChanges,
  canEdit,
  onToggle,
}) {
  return (
    <>
      <tr className="bg-gray-50/60 border-t border-gray-200">
        <td
          colSpan={1 + roles.length}
          className="px-4 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide"
        >
          {category}
        </td>
      </tr>
      {permissions.map(perm => (
        <tr key={perm.key} className="border-t border-gray-100 hover:bg-gray-50/40">
          <td className="px-4 py-3 align-top">
            <div className="text-sm text-gray-800 font-medium">{perm.label}</div>
            <div className="text-xs text-gray-500 mt-0.5">{perm.description}</div>
            <div className="text-[10px] text-gray-400 mt-0.5 font-mono">{perm.key}</div>
          </td>
          {roles.map(role => {
            const k = lockKey(role.system_key, perm.key);
            const isLocked = lockedSet.has(k);
            const isPending = pendingChanges.has(k);
            const checked = displayValue(role.system_key, perm.key);
            const sv = serverValue(role.system_key, perm.key);
            const flipped = isPending && checked !== sv;
            return (
              <td key={role.system_key} className="px-4 py-3 text-center">
                {isLocked ? (
                  <span
                    title="Required for Stewards — cannot be changed."
                    className="inline-flex items-center justify-center gap-1 text-gray-400"
                  >
                    <input
                      type="checkbox"
                      checked
                      disabled
                      readOnly
                      aria-label={`${role.name || role.system_key} — ${perm.label} (locked)`}
                      className="accent-[var(--brand-accent)] cursor-not-allowed"
                    />
                    <span aria-hidden="true">🔒</span>
                  </span>
                ) : (
                  <span
                    className={`inline-flex items-center justify-center ${
                      flipped ? 'ring-2 ring-amber-400 ring-offset-1 rounded' : ''
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!canEdit}
                      onChange={() => onToggle(role.system_key, perm.key)}
                      aria-label={`${role.name || role.system_key} — ${perm.label}`}
                      className="accent-[var(--brand-accent)]"
                    />
                  </span>
                )}
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}
