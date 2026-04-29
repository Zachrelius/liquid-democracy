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

## Production verification (post-deploy)

After this branch ships to Railway, run the expanded prod sanity from `browser_testing_playbook.md` Suite P epilogue (7 steps) and append results here.
