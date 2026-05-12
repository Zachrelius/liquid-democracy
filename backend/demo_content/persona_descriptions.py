"""Phase 23.1 — quick-login persona descriptions per Stage 8 §6.

These populate the ``description`` field on the personas JSONB column on
each demo Organization. The seed pipeline reads from this dict; the
fallback is ``Member.role`` if a user_id is missing.

Defect being fixed: C4 — persona descriptions on /demo were rendering the
role string twice (the seed pipeline copied ``m.role`` into both the
``role`` and ``description`` keys). Stage 8 §6 of the demo design table
specifies distinct one-sentence descriptions; this module is the
canonical source for them.
"""

QUICK_LOGIN_DESCRIPTIONS: dict[str, str] = {
    # Cedar Hollow HOA
    "hoa_janet": "The current President filling out an unexpired term, running for the full one; competent and busy, accepts delegation on Budget.",
    "hoa_brenda": "The Secretary who reads the bylaws so you don't have to and votes to preserve procedural integrity even when it's inconvenient.",
    "hoa_marcus": "A city planner and Cedar Court resident; quietly progressive, accepts delegation on Cedar Court Issues, also active in the Tenants Coalition.",
    "hoa_don": "A 31-year resident and former VP who pushes back hard on board spending; transparent voting record, refuses delegations on principle.",
    "hoa_linda": "The Treasurer with a CFO day job; spreadsheet-anchored, accepts delegation on Budget, won't back spending without a credible funding source.",
    "hoa_tomas": "A newer Cedar Court resident and high school PE teacher; mostly engaged on pool issues, votes his own way and recommends you do too.",
    # AFSCME Local 4021
    "local_keisha": "The mid-term President steering toward the 2027 contract; accepts delegation on Contract & Grievances, shows her work in the rationales.",
    "local_sam": "An 18-year DPW Sanitation steward who reasons from Article 14 and past practice; accepts delegation on Grievances and Contract Interpretation.",
    "local_dana": "The Local's first Library steward and also an active member of the Tenants Coalition; accepts delegation on Library Issues and Health & Safety.",
    "local_tony": "The Treasurer and a Parks heavy-equipment operator; accepts delegation on Local Finances and Strike Fund, votes for what builds bargaining capacity.",
    "local_aisha": "A Parks recreation programmer running for VP in the current special election; transparent only, not accepting delegations during the campaign.",
    "local_walt": "A retired DPW Streets member with 31 years in; transparent only on Pension issues, declines delegations so members do their own thinking.",
    # Westgate Tenants Coalition
    "coalition_priya": "A Coordinating Committee member up for re-election; qualified-YIMBY bridge-builder, accepts delegation on Land Use Policy and Council Engagement.",
    "coalition_hector": "The Direct Action lead and proposer of the Riverside Properties escalation; accepts delegation on Direct Action and Anti-Displacement.",
    "coalition_marcus": "A city planner in the Policy working group; same person as Cedar Hollow's Member-at-Large, with a substantive Land Use Policy position statement.",
    "coalition_maya": "A Coordinating Committee member up for re-election and Outreach lead; accepts delegation on Tenant Protections and Public Housing.",
    "coalition_dana": "A Member Defense working group regular and the Local 4021 Library steward; accepts delegation on Member Defense, brings labor-tenant solidarity.",
    "coalition_will": "A newer member with a `private_delegators` delegate page in draft on Tenant Tech Issues; try clicking through to see how the private-page surface renders.",
}


__all__ = ["QUICK_LOGIN_DESCRIPTIONS"]
