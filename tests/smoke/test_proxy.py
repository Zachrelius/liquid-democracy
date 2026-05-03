# Phase 10.2 W-FIX-C: nginx / proxy boundary smoke checks.
#
# These checks exist because pytest never exercises the nginx layer in
# front of the FastAPI app. Each historical regression below was caught
# only by manual curl after deploy:
#   - Phase 9.8: missing `^~` modifier on `location /uploads/` caused
#     nginx to fall through to the SPA catch-all instead of proxying.
#   - Phase 9.9: default `client_max_body_size` (1 MB) silently rejected
#     5 MB avatar uploads with nginx HTML 413 instead of letting FastAPI
#     respond.
#   - Phase 10 closeout: `manifest.webmanifest` served as
#     `application/octet-stream` because nginx had no MIME mapping for
#     `.webmanifest` (Lighthouse PWA install affordance flagged it).
#   - Phase 10: `registerSW.js` is auto-emitted by vite-plugin-pwa; codify
#     that it is reachable so a future build/config change cannot drop it.
#
# Each test is independent and re-runnable. No fixtures beyond `target_url`.

import uuid

import httpx

# Generous timeouts because we are crossing the public internet.
TIMEOUT = 30.0


def test_uploads_proxies_to_backend(target_url):
    """Phase 9.8 regression guard.

    GET /uploads/{nonexistent}/file.jpg should hit the FastAPI StaticFiles
    mount (which 404s as JSON), NOT the SPA fallback (which would 200 with
    HTML) and NOT nginx's HTML 404. The presence of `application/json`
    plus a `detail` body proves the request reached FastAPI.
    """
    bogus = uuid.uuid4().hex
    url = f"{target_url}/uploads/{bogus}/128.jpg"
    r = httpx.get(url, timeout=TIMEOUT)
    assert r.status_code == 404, (
        f"expected 404 from FastAPI StaticFiles for missing upload, "
        f"got {r.status_code}; body={r.text[:200]!r}"
    )
    ct = r.headers.get("content-type", "")
    assert "application/json" in ct, (
        f"expected JSON 404 from FastAPI (proxy hit backend), got "
        f"content-type={ct!r}; body={r.text[:200]!r}. "
        "If this is HTML, nginx /uploads/ proxy regressed (likely missing "
        "`^~` modifier — see Phase 9.8)."
    )


def test_body_size_limit_passes_through_to_backend(target_url):
    """Phase 9.9 regression guard.

    POST a 5 MB body with no Authorization header. Expected behavior:
    nginx forwards the request (because client_max_body_size >= 5 MB)
    and FastAPI's auth dependency rejects it with 401. If nginx returns
    413, the body-size limit has drifted back below 5 MB.
    """
    url = f"{target_url}/api/users/me/avatar"
    body = b"A" * (5 * 1024 * 1024)
    r = httpx.post(url, content=body, timeout=TIMEOUT)
    assert r.status_code != 413, (
        "nginx returned 413 — client_max_body_size has regressed below "
        "5 MB (Phase 9.9 hot-fix lost). Check `frontend/nginx.conf`."
    )
    assert r.status_code == 401, (
        f"expected FastAPI 401 (proxy passed through), got {r.status_code}; "
        f"body={r.text[:200]!r}"
    )


def test_manifest_mime_type(target_url):
    """Phase 10 closeout open-issue guard (CURRENTLY EXPECTED TO FAIL).

    Lighthouse and several browsers expect `Content-Type:
    application/manifest+json` for `.webmanifest`. Without the right MIME,
    PWA install affordance is degraded and Chrome warns in DevTools.

    The fix is a one-line addition to `frontend/nginx.conf`:
        types { application/manifest+json webmanifest; }
    inside the `http {}` (or `server {}`) block, OR add the MIME mapping
    in the existing `types` block.

    Until that lands, this check fails — and that failure is the signal
    the lead/QA looks for to confirm the regression has not silently
    reappeared once the fix ships.
    """
    url = f"{target_url}/manifest.webmanifest"
    r = httpx.get(url, timeout=TIMEOUT)
    assert r.status_code == 200, (
        f"manifest.webmanifest not served, status={r.status_code}"
    )
    ct = r.headers.get("content-type", "")
    assert "application/manifest+json" in ct, (
        f"expected Content-Type: application/manifest+json, got {ct!r}. "
        "Add a `.webmanifest` MIME mapping to frontend/nginx.conf — see "
        "Phase 10 closeout open issue."
    )


def test_register_sw_js_served(target_url):
    """Phase 10 PWA install affordance guard.

    vite-plugin-pwa with `injectRegister: 'auto'` emits a small
    /registerSW.js shim and references it from index.html. Codify that
    the file is reachable + served as JS so a future build/config change
    cannot silently drop the registration shim (which would break SW
    install on first visit).
    """
    url = f"{target_url}/registerSW.js"
    r = httpx.get(url, timeout=TIMEOUT)
    assert r.status_code == 200, (
        f"registerSW.js missing or unreachable, status={r.status_code}"
    )
    ct = r.headers.get("content-type", "")
    assert "javascript" in ct.lower(), (
        f"expected JS Content-Type for registerSW.js, got {ct!r}"
    )
