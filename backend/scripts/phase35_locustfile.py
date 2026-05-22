"""Phase 35 A3 — Locust load generator for the scalability audit.

Run against a temporary Railway service seeded with either the production
Cedar Hollow bible (1x baseline) or the synthetic 5x bible (5x projection).

Install:
    pip install locust

Run:
    # Headless, 5 users, 30 min, against 1x baseline
    locust -f scripts/phase35_locustfile.py \\
        --host https://<temp-railway-url> \\
        --headless -u 5 -r 1 --run-time 30m \\
        --csv phase35_1x_run

    # 5x: 15-20 users (proportional to ~5x member count)
    locust -f scripts/phase35_locustfile.py \\
        --host https://<temp-railway-url> \\
        --headless -u 20 -r 2 --run-time 30m \\
        --csv phase35_5x_run

The CSV output captures latencies + throughput. Correlate with the
instrumented JSON log lines (audit=request) in the Railway logs for
the same window for per-query / per-endpoint analysis.

Scenarios (weighted, mixing common user flows):
  - browse proposals list (most common)
  - view a proposal's detail (next most common)
  - cast a vote
  - view a delegate's public page
"""
import random
import os

from locust import HttpUser, task, between


# Demo persona that load test logs in as (must be in the seeded bible's
# personas allowlist). Cedar Hollow has marcus_pham; synthetic 5x has
# syn_0000. Configure via env var.
DEMO_USERNAME = os.environ.get("PHASE35_USERNAME", "marcus_pham")
DEMO_ORG_SLUG = os.environ.get("PHASE35_ORG_SLUG", "demo-cedar-hollow")


class AuditUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Log in via demo-login and stash the bearer token."""
        resp = self.client.post(
            "/api/auth/demo-login",
            json={"username": DEMO_USERNAME, "org_slug": DEMO_ORG_SLUG},
        )
        if resp.status_code != 200:
            print(f"demo-login failed: {resp.status_code} {resp.text[:200]}")
            self.token = None
            return
        self.token = resp.json().get("access_token")
        self._auth = {"Authorization": f"Bearer {self.token}"}

        # Cache the proposal list once so detail/vote tasks have IDs.
        plist = self.client.get(
            f"/api/orgs/{DEMO_ORG_SLUG}/proposals",
            headers=self._auth,
        )
        if plist.status_code == 200:
            self._proposal_ids = [p["id"] for p in plist.json()]
        else:
            self._proposal_ids = []

    @task(5)
    def browse_proposals(self):
        if not self.token:
            return
        self.client.get(
            f"/api/orgs/{DEMO_ORG_SLUG}/proposals",
            headers=self._auth,
            name="GET /api/orgs/{slug}/proposals",
        )

    @task(4)
    def view_proposal_detail(self):
        if not self.token or not self._proposal_ids:
            return
        pid = random.choice(self._proposal_ids)
        self.client.get(
            f"/api/proposals/{pid}",
            headers=self._auth,
            name="GET /api/proposals/{id}",
        )

    @task(2)
    def view_trajectory(self):
        if not self.token or not self._proposal_ids:
            return
        pid = random.choice(self._proposal_ids)
        self.client.get(
            f"/api/proposals/{pid}/trajectory",
            headers=self._auth,
            name="GET /api/proposals/{id}/trajectory",
        )

    @task(2)
    def browse_delegates(self):
        if not self.token:
            return
        self.client.get(
            f"/api/orgs/{DEMO_ORG_SLUG}/delegates",
            headers=self._auth,
            name="GET /api/orgs/{slug}/delegates",
        )

    @task(1)
    def list_topics(self):
        if not self.token:
            return
        self.client.get(
            f"/api/orgs/{DEMO_ORG_SLUG}/topics",
            headers=self._auth,
            name="GET /api/orgs/{slug}/topics",
        )
