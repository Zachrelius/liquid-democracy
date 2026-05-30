"""Phase 43a — Capture 5 help-page screenshots from prod Cedar Hollow demo.

Run from repo root:
    backend/.venv/Scripts/python.exe frontend/scripts/capture_help_screenshots.py

Saves PNGs to frontend/public/help-screenshots/.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

BASE = "https://www.liquiddemocracy.us"
OUT = Path(__file__).resolve().parents[1] / "public" / "help-screenshots"
OUT.mkdir(parents=True, exist_ok=True)
VIEWPORT = {"width": 1440, "height": 900}


def sign_in_as_janet(page: Page) -> None:
    page.goto(f"{BASE}/demo", wait_until="networkidle")
    cedar_card = page.get_by_text("Cedar Hollow", exact=False).first
    cedar_card.scroll_into_view_if_needed()
    janet = page.get_by_role("button", name="Sign in as Janet Reilly").or_(
        page.get_by_text("Janet Reilly").first.locator(
            "xpath=ancestor::*[self::a or self::button][1]"
        )
    )
    try:
        janet.first.click(timeout=5000)
    except PlaywrightTimeoutError:
        for btn in page.get_by_role("button").all():
            txt = (btn.inner_text() or "").lower()
            if "janet" in txt:
                btn.click()
                break
        else:
            raise RuntimeError("Could not find Janet Reilly sign-in control on /demo")
    page.wait_for_url(lambda url: "/demo" not in url, timeout=15000)
    page.wait_for_load_state("networkidle")


def screenshot_proposals_list(page: Page) -> Path:
    page.goto(f"{BASE}/demo-cedar-hollow/proposals", wait_until="networkidle")
    time.sleep(1.5)
    out = OUT / "member-proposals-list.png"
    page.screenshot(path=str(out), full_page=False)
    return out


def screenshot_vote_cast(page: Page) -> Path:
    page.goto(f"{BASE}/demo-cedar-hollow/proposals", wait_until="networkidle")
    time.sleep(1.0)
    proposal_hrefs = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/proposals/"]'))
            .map(a => a.getAttribute('href'))
            .filter(h => /\\/proposals\\/[^/]+$/.test(h))"""
    )
    if not proposal_hrefs:
        raise RuntimeError("No proposal links found on /proposals")
    for href in proposal_hrefs[:8]:
        page.goto(f"{BASE}{href}", wait_until="networkidle")
        time.sleep(0.8)
        clicked = page.evaluate(
            """() => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.innerText.trim() === 'Vote Now');
                if (btn) { btn.click(); return true; }
                return false;
            }"""
        )
        if not clicked:
            continue
        time.sleep(0.6)
        has_controls = page.evaluate(
            """() => {
                const txts = Array.from(document.querySelectorAll('button'))
                    .map(b => b.innerText.trim());
                return ['Yes','No','Abstain'].every(l => txts.includes(l));
            }"""
        )
        if has_controls:
            page.evaluate(
                """() => {
                    const btn = Array.from(document.querySelectorAll('button'))
                        .find(b => b.innerText.trim() === 'Yes');
                    if (btn) btn.scrollIntoView({block: 'center'});
                }"""
            )
            time.sleep(0.4)
            out = OUT / "member-vote-cast.png"
            page.screenshot(path=str(out), full_page=False)
            return out
    raise RuntimeError("No proposal with Yes/No/Abstain controls found")


def screenshot_browse_delegates(page: Page) -> Path:
    page.goto(f"{BASE}/demo-cedar-hollow/delegates", wait_until="networkidle")
    time.sleep(1.5)
    out = OUT / "member-browse-delegates.png"
    page.screenshot(path=str(out), full_page=False)
    return out


def screenshot_admin_menu(page: Page) -> Path:
    page.goto(f"{BASE}/demo-cedar-hollow/proposals", wait_until="networkidle")
    time.sleep(0.8)
    admin_btn = page.get_by_role("button", name="Admin").or_(page.locator("button:has-text('Admin')")).first
    admin_btn.click()
    time.sleep(0.6)
    out = OUT / "steward-admin-menu.png"
    page.screenshot(path=str(out), full_page=False)
    return out


def screenshot_my_delegate_page(page: Page) -> Path:
    page.goto(f"{BASE}/demo-cedar-hollow/delegate-profile", wait_until="networkidle")
    time.sleep(1.5)
    out = OUT / "delegate-my-delegate-page.png"
    page.screenshot(path=str(out), full_page=False)
    return out


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = ctx.new_page()
        try:
            print("Signing in as Janet Reilly on Cedar Hollow...")
            sign_in_as_janet(page)
            print(f"  signed in; landed on {page.url}")

            results = []
            for fn in (
                screenshot_proposals_list,
                screenshot_browse_delegates,
                screenshot_admin_menu,
                screenshot_my_delegate_page,
                screenshot_vote_cast,
            ):
                print(f"Capturing {fn.__name__}...")
                p = fn(page)
                size = p.stat().st_size
                print(f"  -> {p.name} ({size:,} bytes)")
                results.append((p.name, size))
            print("\nAll 5 screenshots captured.")
            for name, size in results:
                print(f"  {name:40s} {size:>10,} bytes")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
