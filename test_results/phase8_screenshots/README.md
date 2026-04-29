# Phase 8 — Sustained-Majority Voting Windows

## Browser-driven Suite P verification (2026-04-29)

P4/P5/P9 were converted from the original PASS-by-source declaration to actual Claude-in-Chrome browser verification against the local dev server. Two real bugs surfaced and were fixed during this pass — both lived purely in the React component layer and were not caught by the 67 backend tests, validating the decision not to extend the M31/M32 source-review precedent to a new component family.

### Test fixtures (created via direct DB ops in `backend/.venv/Scripts/python`)

```python
# Org settings patch (admin demo org)
demo.settings = {**demo.settings,
    'sustained_majority_enabled_default': False,
    'sustained_majority_per_proposal_override': True,
    'sustained_majority_threshold': 0.50,
    'sustained_majority_floor': 0.45,
    'sustained_majority_failure_mode': 'extend',
}

# P4 — comfortably above floor (yes 6 / no 3 → 0.667)
# P5 — APPROACHING floor (yes 6 direct + dave inherits via alice → 7 / no 7 → 0.50)
# P9 — approval, voting_start backdated 90h, voting_end +10h (90% elapsed → in final 25%)
```

The exact setup script lives in this conversation's history; rerunning is straightforward by reapplying the `make_p` and vote helpers from the fixture script. Personas come from the demo seed (`alice`, `frank`, `dave`, `carol`, `econ_bob`, `voter01`–`voter30`).

## Captured screenshots

| File | What it shows | Suite P case |
|---|---|---|
| `P4_proposal_detail_support_indicator.png` | SustainedMajorityPanel rendering with support-vs-floor bar (current support 66.7% tick + red sub-floor zone + dashed threshold marker) + Recharts historical chart + footer (Threshold 50.0% / Floor 45.0% / Failure mode: extend / Extensions: 0) | P4 |
| `P5_floor_approach_banner.png` | Frank (direct YES voter) viewing P5: amber "⚠ Support is approaching the floor" banner with "Review your vote" / "Review your delegation" links | P5(a) — direct vote contributor |
| `P5b_dave_inherited_banner.png` | Dave (delegates to alice via global topic=None delegation, alice voted yes → effective vote = yes) viewing P5: same amber banner appears | P5(b) — inheritance contributor |
| `P5c_carol_no_banner.png` | Carol (direct NO voter) viewing P5 *after* the bug fix: amber banner correctly absent. Sustained-majority status panel still visible | P5(c) — non-contributor |
| `P9_multi_option_stable_lock.png` | Approval proposal in final 25% of voting window: SustainedMajorityPanel shows green dot + "Stable-result lock active — final stretch of the voting window. A change to the computed winner now triggers the failure mode." + "Current winner: Adopt Plan A" (label, not UUID) | P9 |
| `audit_log_sample.txt` | Self-contained scenario emitting all six new event types in sequence (org config change, per-proposal toggle, window extend, fail, escalate, escalation resolve) — used by the Phase 8 docs to show the audit-log payload shape | P10 |
| `_capture_chrome.ps1` | Helper script: `powershell -File _capture_chrome.ps1 -Dest <path>` captures the foreground Chrome window region as PNG. Used to save the screenshots above. | tooling |

## Bugs found by browser verification

1. **`SustainedMajorityPanel.jsx` floor-approach banner gating ignored vote direction** — original `myVoteContributes` was just `myVote.is_direct === true || myVote.is_direct === false`, which is "the user voted at all" rather than "the user is contributing to the at-risk side". Fixed to also require `myVote.vote_value === 'yes'`. Reason: a no-voter sees the proposal failing as the desired outcome, not a problem to act on; showing them the urgent amber banner would be misleading.
2. **`SustainedMajorityPanel.jsx` multi-option current-winner rendered UUID** — the panel joined `sm.current_winners` directly into the display string, but `current_winners` is a list of option_ids, not labels. Fixed to look up `proposal.options.find(o => o.id === id)?.label || id`.

## Production verification — expanded sanity (2026-04-29, post-deploy of `58cc8f6` + follow-up `6633a73`)

Ran the 7-step expanded prod sanity against `https://www.liquiddemocracy.us`. Backend bundle deployed via Railway auto-deploy minutes after each push. Frontend bundle hash post-Phase-8: `index-DXU00ZZD.js` (then `index-BjI43aAs.js` after the help-page-public follow-up).

| Step | Check | Result | Artifact |
|---|---|---|---|
| 1 | Org Settings page renders the new "Sustained-Majority Voting" section with all five controls (default-on toggle, per-proposal-override toggle, threshold slider, floor slider, failure-mode radio with three options) | ✅ PASS | `PROD1_org_settings_section.png` |
| 2 | Proposal-creation toggle behaves correctly — visible when org allows override, disappears when override flipped to false, reappears when flipped back to true | ✅ PASS | `PROD2_create_form_toggle_visible.png` (org allows) + `PROD2b_create_form_toggle_absent.png` (org disallows) |
| 3 | `/help/sustained-majority` loads publicly without auth | ❌ initial / ✅ fixed | First check redirected to /login (route was gated under ProtectedRoute). Fixed in commit `6633a73` (move route to public scope). Re-verified: `PROD3_help_page_public.png` shows full content with no token in storage |
| 4 | Worker is alive and producing snapshots | ✅ PASS | Verified during step 6 — `time_series` populated within ~2 min of vote activity (cadence default 300s; first tick fired sooner than expected due to existing tally state). Snapshot count grew across polls. |
| 5 | `/results.sustained_majority` block returns the expected payload shape | ✅ PASS | `PROD5_results_sustained_majority_block.json` — full block with all 12 fields (active, threshold, floor, failure_mode, current_support, distance_to_floor, floor_breached, approaching_floor, in_stable_result_window, stable_result_locked, current_winners, extension_count, voting_end) |
| 6 | Real failure-cycle test on prod — extend mode fires when support drops below floor | ✅ PASS — bonus: full extend → fail cycle observed live | Created `Phase 8 Closeout — Failure-Cycle Test`, advanced to voting, cast 3 yes / 1 no (above floor). Flipped alice yes → no, support dropped to 0.25 (below 0.45 floor). At 11:49:14 (~2 min after flip) worker fired `proposal.window_extended` — voting_end pushed +6h, support_fraction=0.25 in breach_sample. At 11:54:15 (~5 min later, second tick still below floor) worker promoted to `proposal.failed_sustained_majority` — confirming the extend → fail second-breach mechanic on prod. `PROD6_failure_cycle_extension_fired.png` shows the SM panel as frank with ⛔ Floor breached banner + Extensions: 1 + Failure mode: extend. `PROD6_audit_log_window_extended.json` is the full audit timeline. |
| 7 | Cleanup: test proposals don't pollute the demo | ✅ PASS by natural progression | The failure-cycle proposal moved itself to `failed` status (terminal) before I had a chance to withdraw it. Title self-identifies as a closeout test ("Phase 8 Closeout — Failure-Cycle Test (sustained-majority extend)"); body says "Will be withdrawn after verification." Failed status keeps it out of the voting list. Org settings reverted to defaults: `sustained_majority_failure_mode=fail`, `sustained_majority_enabled_default=false`. |

### Bug found and fixed during prod sanity

- `/help/sustained-majority` was gated under `ProtectedRoute` (matching `VotingMethodsHelp`), but the floor-approach banner and SustainedMajorityPanel link from the proposal-detail page can be reached by future email-notification readers (Phase 10) before they log in. Fixed in commit `6633a73`: route is now public, matching `/why`, `/security`, `/privacy`, `/terms`.

### Audit timeline observed on prod (failure-cycle test proposal)

```
11:45:53  proposal.created + proposal.sustained_majority_enabled
11:46:05  proposal.status_changed (draft → deliberation)
11:46:05  proposal.status_changed (deliberation → voting)
[vote casting: alice yes, frank yes, carol no, dave inherits via alice]
[alice flips yes → no at 11:47:02, dropping support to 0.25]
11:49:14  proposal.window_extended       ← worker tick #1 (extend mode, count=0)
11:54:15  proposal.failed_sustained_majority  ← worker tick #2 (still below floor, count=1, promoted to fail)
```

Worker cadence on prod (default `SUSTAINED_MAJORITY_CHECK_INTERVAL_SECONDS=300`) — extension fired within 5 min of breach onset, fail-promotion fired ~5 min after that. End-to-end extend → fail cycle observed in 9 min from vote-flip to terminal status.
