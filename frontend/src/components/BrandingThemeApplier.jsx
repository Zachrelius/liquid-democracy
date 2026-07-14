import { useEffect } from 'react';
import { deriveDarker } from '../utils/color_derive';
import { accessibleAccentTextColor } from '../utils/colorContrast';

/**
 * Phase 14 F2 — standalone branding theme applier.
 *
 * Lifted out of App.jsx (which had a context-coupled inline version that
 * read from useOrg()) so the public org landing page can apply the same
 * CSS-variable theming without going through OrgScopedLayout's auth gate.
 *
 * Accepts an explicit `branding` object (the same shape the org-public
 * endpoint and /api/orgs both return: `{primary_color, accent_color, ...}`),
 * or null. When non-null and the colors are set, mutates
 * `document.documentElement` style with `--brand-primary`,
 * `--brand-primary-dark` (auto-derived via HSL), and `--brand-accent`. On
 * unmount or color change, removes the overrides so platform defaults from
 * `index.css` reapply automatically.
 *
 * Renders no DOM. Used by both OrgScopedLayout (member-gated org routes)
 * and OrgPublicLanding (public splash) so brand theming behaves
 * identically across the two surfaces.
 */
export default function BrandingThemeApplier({ branding }) {
  const primary = branding?.primary_color || null;
  const accent = branding?.accent_color || null;

  useEffect(() => {
    const root = document.documentElement;
    if (primary) {
      root.style.setProperty('--brand-primary', primary);
      root.style.setProperty('--brand-primary-dark', deriveDarker(primary, 10));
    } else {
      root.style.removeProperty('--brand-primary');
      root.style.removeProperty('--brand-primary-dark');
    }
    if (accent) {
      root.style.setProperty('--brand-accent', accent);
      root.style.setProperty('--brand-accent-text', accessibleAccentTextColor(accent));
    } else {
      root.style.removeProperty('--brand-accent');
      root.style.removeProperty('--brand-accent-text');
    }
    return () => {
      root.style.removeProperty('--brand-primary');
      root.style.removeProperty('--brand-primary-dark');
      root.style.removeProperty('--brand-accent');
      root.style.removeProperty('--brand-accent-text');
    };
  }, [primary, accent]);

  return null;
}
