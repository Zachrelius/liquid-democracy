# Phase 10.2 W-FIX-C: service worker cache-denylist smoke check.
#
# Workbox compiles the configured `navigateFallbackDenylist` patterns
# directly into the generated `sw.js` source. Fetching the deployed
# `sw.js` and asserting the literal denylist substrings are present
# catches the case where someone edits `frontend/vite.config.js` (e.g.,
# adds a new live-data path like `/notifications`) and forgets to add
# the corresponding denylist entry.
#
# String-contains check (not regex eval) is sufficient: Workbox emits
# the source as `denylist:[/^\/api/,/^\/uploads/]` literally — it is not
# minified beyond removing whitespace. If Workbox's emit format ever
# changes shape, this check needs updating; that is acceptable churn.

import httpx

TIMEOUT = 30.0


def test_navigate_fallback_denylist_includes_api_and_uploads(target_url):
    """Workbox denylist for /api and /uploads must be present in sw.js."""
    url = f"{target_url}/sw.js"
    r = httpx.get(url, timeout=TIMEOUT)
    assert r.status_code == 200, f"sw.js not served, status={r.status_code}"

    ct = r.headers.get("content-type", "")
    assert "javascript" in ct.lower(), (
        f"expected JS Content-Type for sw.js, got {ct!r}"
    )

    body = r.text
    # Workbox emits the configured RegExp objects in source form. The
    # exact format `[/^\/api/,/^\/uploads/]` is what
    # `navigateFallbackDenylist: [/^\/api/, /^\/uploads/]` in
    # `frontend/vite.config.js` compiles to.
    assert "/^\\/api/" in body, (
        "service worker denylist missing /api pattern — a future live-data "
        "API path could be silently cached. Check "
        "`navigateFallbackDenylist` in frontend/vite.config.js."
    )
    assert "/^\\/uploads/" in body, (
        "service worker denylist missing /uploads pattern — uploaded "
        "user avatars could be silently cached. Check "
        "`navigateFallbackDenylist` in frontend/vite.config.js."
    )
