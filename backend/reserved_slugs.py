"""Phase 11: reserved slugs that conflict with top-level frontend routes.

Slugs at /{slug}/... cannot collide with these because the frontend route
table reserves them for marketing, auth, onboarding, and user-scoped pages.
Both Organization slugs (top-level) and SubOrganization slugs (nested) are
checked against this set on creation.
"""

RESERVED_SLUGS = {
    "admin", "api", "app", "assets", "auth", "blog", "delegates", "demo",
    "docs", "explore", "forgot-password", "help", "info", "invite", "login",
    "logout", "o", "orgs", "pilot", "pricing", "privacy", "public", "register",
    "reset-password", "security", "settings", "setup", "signup", "static",
    "support", "terms", "test", "tests", "uploads", "verify-email", "why",
}
# Phase 19 G1: 'delegates' added to reserve the per-org delegate browse URL
# `/{slug}/delegates`. Without this, a user could claim handle `delegates`
# (or an org slug `delegates`) and collide with the browse URL.
# Phase 55: 'explore' added to reserve the public org discovery URL
# `/explore`. Belt-and-suspenders with the route-table precedence (the
# public router's fixed `/explore` is registered before `/{slug}`), so an
# org can never claim the slug and collide.
