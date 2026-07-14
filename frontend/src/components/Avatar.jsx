import { useState } from 'react';

/**
 * Phase 9.8 W A2 — Avatar component.
 *
 * Renders a user's uploaded avatar (when ``avatar_url`` is set on the user
 * shape) or a deterministic initials-on-colored-background fallback. The
 * fallback color is derived from a stable hash of the user's id (or username)
 * so the same person renders in the same color across every surface.
 *
 * Sizes: 'sm' = 24px (nav, member rows), 'md' = 48px (graph nodes), 'lg' = 96px
 * (profile headers, settings page). The small URL (48px) is used for sm/md;
 * the full URL (128px) is used for lg.
 *
 * Defensive: if the avatar image 404s the component swaps to the initials
 * state via the ``onError`` handler.
 *
 * URL resolution: avatar URLs come back from the API as root-relative paths
 * (e.g. ``/uploads/avatars/{user_id}/128.jpg``). Production serves these via
 * the same nginx that proxies ``/api`` (see ``frontend/nginx.conf`` for the
 * matching ``/uploads/`` location); dev serves them via Vite proxy (see
 * ``vite.config.js``). Either way the path can be used as-is — no API base
 * prepending needed.
 */

const SIZE_PX = { sm: 24, md: 48, lg: 96 };
const FONT_SIZE_PX = { sm: 11, md: 18, lg: 36 };

/** Tiny djb2-ish hash → non-negative integer. Stable across renders. */
function hashStringToInt(str) {
  let h = 5381;
  const s = String(str || '');
  for (let i = 0; i < s.length; i++) {
    // ((h << 5) + h) === h * 33; XOR with charCode.
    h = ((h << 5) + h) ^ s.charCodeAt(i);
  }
  // Force non-negative.
  return h >>> 0;
}

/** Stable hue (0-359) derived from the user's id (or username). */
function hueFor(user) {
  const seed = user?.id || user?.username || user?.display_name || '';
  return (hashStringToInt(seed) * 137) % 360;
}

/** Initials from a display name (uppercase first character). */
function initialsFor(user) {
  const name = user?.display_name || user?.username || '?';
  const trimmed = String(name).trim();
  if (!trimmed) return '?';
  return trimmed.charAt(0).toUpperCase();
}

export default function Avatar({ user, size = 'md', className = '' }) {
  const [imgFailed, setImgFailed] = useState(false);
  const px = SIZE_PX[size] || SIZE_PX.md;
  const fontPx = FONT_SIZE_PX[size] || FONT_SIZE_PX.md;

  // Pick the appropriate URL: small (48px) for sm/md, full (128px) for lg.
  // The backend ships ``avatar_url`` (128) and clients can derive the small
  // URL deterministically from it; some endpoints also ship ``avatar_url_small``
  // explicitly. Prefer the explicit field when present.
  const fullUrl = user?.avatar_url || null;
  const smallUrl =
    user?.avatar_url_small ||
    (fullUrl ? fullUrl.replace(/\/128\.jpg$/, '/48.jpg') : null);
  const url = size === 'lg' ? fullUrl : smallUrl;

  const showImage = url && !imgFailed;

  if (showImage) {
    return (
      <img
        src={url}
        alt=""
        aria-hidden="true"
        onError={() => setImgFailed(true)}
        className={`inline-block rounded-full object-cover ${className}`}
        style={{ width: px, height: px }}
      />
    );
  }

  // Initials-on-colored-background fallback.
  const hue = hueFor(user);
  const bg = `hsl(${hue}, 65%, 55%)`;
  return (
    <span
      aria-hidden="true"
      className={`inline-flex items-center justify-center rounded-full text-white font-semibold select-none ${className}`}
      style={{
        width: px,
        height: px,
        backgroundColor: bg,
        fontSize: fontPx,
        lineHeight: 1,
      }}
    >
      {initialsFor(user)}
    </span>
  );
}
