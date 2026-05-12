"""
Westgate Tenants Coalition Bible — Demo Content for liquiddemocracy.us

PART 1 of 3 — Imports, charter, members, delegate pages (Priya, Hector, Marcus).
The full module concatenates Parts 1, 2, and 3 into activist_bible.py.

Companion modules:
- hoa_bible.py (Cedar Hollow HOA)
- union_bible.py (AFSCME Local 4021)
- trajectory_waypoints.py (per-proposal support-trajectory data, shared)
"""

from .schema import (
    Member, TopicVisibility, PositionStatement, VoteRationale,
    DelegatePage, Comment, Proposal, NotificationEvent, NotificationFeed,
    OrgBible,
)


# =============================================================================
# Westgate Tenants Coalition
# =============================================================================

CHARTER = """\
Westgate Tenants Coalition is a voluntary-association tenant advocacy
organization founded in 2019. Membership is open to any renter in Millbrook.
Current dues-paying membership is approximately 240, with a broader email
list of ~1,100. The Coalition organizes around tenant rights, housing
affordability, anti-displacement work, and engagement with Millbrook City
Council on housing policy. Structure: a Coordinating Committee of 9 elected
at-large members serves as leadership; working groups (Policy, Outreach,
Direct Action, Member Defense) handle ongoing work. There are no formal
officers — the Coordinating Committee operates by consensus when possible
and majority vote when not. The Coalition has no paid staff.\
"""

TONE_NOTES = """\
Earnest, more verbal, more ideologically self-aware than the other two orgs.
People here read theory and use the vocabulary (gentrification, displacement,
decommodification, tenant power) without it being academic-left jargon.
Proposals tend to be longer and more justified than in the HOA. Comments
engage with each other substantively, sometimes contentiously. Real anger
and real warmth visible. No sloganizing in deliberation; slogans only appear
in formal communications outside the platform.\
"""

RECENT_HISTORY = """\
- Right-to-counsel pilot program for eviction-facing tenants successfully passed City Council.
- YIMBY/anti-development split simmering across the membership; central narrative arc.
- Coordinating Committee 3-of-9 seats up for partial re-election.
- Riverside Properties direct-action campaign ongoing; recent escalation through P-C-04 force-close.\
"""


# -----------------------------------------------------------------------------
# Members
# -----------------------------------------------------------------------------

MEMBERS = [
    Member(user_id='coalition_priya', display_name='Priya Krishnan',
           quick_login=True, role='Coordinating Committee (Policy lead)',
           notification_preset='high'),
    Member(user_id='coalition_hector', display_name='Hector Ruiz',
           quick_login=True, role='Coordinating Committee (Direct Action lead)',
           notification_preset='high'),
    Member(user_id='coalition_marcus', display_name='Marcus Pham',
           quick_login=True, is_cross_org=True, role='Policy working group',
           notification_preset='medium'),
    Member(user_id='coalition_maya', display_name='Maya Goldberg',
           quick_login=True, role='Coordinating Committee (Outreach lead)',
           notification_preset='high'),
    Member(user_id='coalition_dana', display_name='Dana Whitfield',
           quick_login=True, is_cross_org=True, role='Member Defense working group',
           notification_preset='medium'),
    Member(user_id='coalition_will', display_name='Will Sutherland',
           quick_login=True, role='Policy working group (newer member)',
           notification_preset='medium'),
    Member(user_id='coalition_renee', display_name='Renée Castille',
           quick_login=False, role='Member Defense working group'),
    Member(user_id='coalition_jay', display_name='James "Jay" Okonkwo',
           quick_login=False, role='Member'),
]


# -----------------------------------------------------------------------------
# Delegate Pages — Part 1 (Priya, Hector, Marcus)
# -----------------------------------------------------------------------------

DELEGATE_PAGES_PART_1 = [
    DelegatePage(
        member_user_id='coalition_priya',
        page_visibility='public',
        intro=(
            "I joined the Coalition through Member Defense in 2017 — landlord "
            "wouldn't fix anything, the Coalition walked me through filing "
            "complaints, building got repaired. Stayed since. Day job: housing "
            "policy researcher at a regional nonprofit, which I try to put to "
            "use without overweighting it. Coordinating Committee, currently "
            "up for re-election. Policy working group lead.\n\n"
            "If you delegate to me, read the rationales. Pull the delegation "
            "if my reasoning stops tracking with yours."
        ),
        topics=[
            TopicVisibility('Land Use Policy', 'public_accepting'),
            TopicVisibility('City Council Engagement', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Land Use Policy',
                text=(
                    "I'm a qualified YIMBY: support new construction with strong "
                    "affordability mandates and tenant protections, against "
                    "either alone.\n\n"
                    "I know this puts me in a faction. Hector and Maya read the "
                    "same evidence and weight displacement risk differently. I "
                    "don't think they're wrong about a settled question — "
                    "there's a real strategic disagreement about how much "
                    "displacement risk to accept for what amount of supply, and "
                    "I respect the case they make.\n\n"
                    "What I keep coming back to is that the Coalition's strength "
                    "has always been holding disagreement inside the room. If "
                    "you delegate to me here, expect me to vote for upzoning-"
                    "with-mandates, vote for stronger tenant protections paired "
                    "with it, and vote against either in isolation."
                ),
            ),
            PositionStatement(
                topic='City Council Engagement',
                text=(
                    "We move Council votes when we show up with specifics, not "
                    "preferences. The right-to-counsel pilot worked because we "
                    "brought program design, budget, and comparison cities — "
                    "not just an ask.\n\n"
                    "That's an expensive way to organize and it shouldn't fall "
                    "entirely on members with policy training. The Policy "
                    "working group's job, as I see it, is to make this kind of "
                    "engagement repeatable.\n\n"
                    "If you delegate to me on Council Engagement, expect me to "
                    "support Coalition positions that come with specific policy "
                    "alternatives and oppose ones that are just statements of "
                    "preference."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-C-01', 'yes',
                          "Proposing, voting yes. Real reservations on set-aside size and rider enforcement specifics — what tipped me is the leverage argument from the proposer post. If you disagree about where the leverage actually is, this is the kind of vote where pulling the delegation and voting your own way is the right call."),
            VoteRationale('P-C-02', 'no',
                          "Voted no on the amendment despite agreeing the affordability mandate should be stronger. Timing: amendment window in committee closed two weeks ago, so the amendment would mean we don't endorse and the proposal passes anyway. I'd rather organize for stronger mandates in implementation and in the next upzoning than spend our leverage at the endorsement moment."),
            VoteRationale('P-C-04', 'yes',
                          "Came in leaning no over Will's doxing concern. Tenant-protection protocol amendment from extension 1 addressed most of it; Dana's capacity assessment in extension 2 addressed the rest. Considered changing vote after Renée's enforcement concern at hour 92 but didn't — the protocols are worth the work."),
            VoteRationale('P-C-05', 'yes', "Proposer; voted yes. The work is the work."),
            VoteRationale('P-C-06', 'yes', "Voted yes. Dana's proposal formalizes capacity that's been informal for too long."),
            VoteRationale('P-C-07', 'yes', "Voted yes. The relational infrastructure point Hector makes is right."),
            VoteRationale('P-C-08', 'approval_quarterly_monthly', "Approval on both. Quarterly minimum, monthly preferred if CC bandwidth allows."),
            VoteRationale('P-C-09', 'yes', "Voted yes. The Riverside outreach component is well-targeted to the moment."),
            VoteRationale('P-C-10', 'yes', "Voted yes."),
            VoteRationale('P-C-11', 'yes', "Will's formalization captures what came out of P-C-04's extensions. Voted yes."),
        ],
    ),

    DelegatePage(
        member_user_id='coalition_hector',
        page_visibility='public',
        intro=(
            "Coordinating Committee, first year. Direct Action working group "
            "lead.\n\n"
            "Came to the Coalition through an eviction defense action in "
            "2022 — landlord tried to push my neighbor out, the Coalition "
            "organized a response, the eviction got reversed. Stayed.\n\n"
            "Day job is bartender at a downtown place. The Coalition work is "
            "in evenings and weekends, which is most of the time these days.\n\n"
            "`public_accepting` on Direct Action and Anti-Displacement. Both "
            "topics involve tradeoffs that some Coalition members weigh "
            "differently than I do. Read the vote rationales; pull the "
            "delegation if my reasoning stops tracking with yours."
        ),
        topics=[
            TopicVisibility('Direct Action', 'public_accepting'),
            TopicVisibility('Anti-Displacement', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Direct Action',
                text=(
                    "Direct action is necessary when the other channels have "
                    "failed or aren't available. The right-to-counsel pilot was "
                    "won partly through direct action — tenant testimony at "
                    "Council, public pressure on specific Council members, "
                    "escalation when negotiations stalled.\n\n"
                    "What direct action isn't: random confrontation, "
                    "undisciplined tactics, or escalation for its own sake. "
                    "Each campaign should have a specific target, a theory of "
                    "how the action moves that target, and protocols protecting "
                    "the tenants involved. The Riverside Properties campaign "
                    "is the current test of whether we can do escalation "
                    "responsibly.\n\n"
                    "If you delegate to me here, expect votes for tactical "
                    "proposals that include those three elements and votes "
                    "against proposals that don't."
                ),
            ),
            PositionStatement(
                topic='Anti-Displacement',
                text=(
                    "The qualified-YIMBY position holds that supply-with-"
                    "mandates produces less displacement than supply-constrained "
                    "status quo. I disagree, and I want to explain where the "
                    "disagreement actually is rather than caricature it.\n\n"
                    "Priya and Marcus argue that displacement happens whether "
                    "or not you build new housing, and the question is which "
                    "path produces less. I think they're underweighting two "
                    "things: the displacement that happens during construction "
                    "phases when existing tenants get pushed out and don't "
                    "come back, and the indirect displacement when new "
                    "buildings raise rents in adjacent older buildings. The "
                    "1:1 replacement language in the Riverside rider doesn't "
                    "address either fully.\n\n"
                    "Where I agree with the qualified-YIMBY case: supply "
                    "constraints do cause displacement. Doing nothing isn't a "
                    "neutral position. The disagreement is about whether the "
                    "proposed remedies actually work or whether they "
                    "restructure the displacement without reducing it.\n\n"
                    "If you delegate to me on Anti-Displacement: I'll vote "
                    "against upzoning that doesn't include strong tenant "
                    "protections and against proposals that treat new "
                    "construction as the primary remedy for affordability. I "
                    "respect the qualified-YIMBY case enough to engage with "
                    "it; I'm not going to be persuaded out of this position "
                    "by the rider language as currently written."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-C-01', 'no',
                          "The rider doesn't address construction-phase displacement or indirect-displacement effects on adjacent buildings. Voted no. Priya and Marcus's leverage argument is real but doesn't outweigh the substantive concerns."),
            VoteRationale('P-C-02', 'yes',
                          "The amendment was the right move. Voted yes. Membership weighed the precedent question differently than the tactical question and the amendment failed; that's a fair outcome."),
            VoteRationale('P-C-04', 'yes', "Proposer; yes."),
            VoteRationale('P-C-05', 'yes', "Right to counsel permanence is the Coalition's most concrete win available right now. Voted yes."),
            VoteRationale('P-C-06', 'yes', "Dana's proposal is sharper than I expected and the Member Defense capacity issue is real. Voted yes."),
            VoteRationale('P-C-07', 'yes', "Proposer; yes."),
            VoteRationale('P-C-08', 'approval_quarterly', "Quarterly is the right cadence."),
            VoteRationale('P-C-09', 'yes', "Maya's outreach plan is well-targeted. Voted yes."),
            VoteRationale('P-C-10', 'yes', "Proposer; yes."),
            VoteRationale('P-C-11', 'yes', "Will's proposal formalizes what we worked out during P-C-04's extensions. Voted yes."),
        ],
    ),

    DelegatePage(
        member_user_id='coalition_marcus',
        page_visibility='public',
        intro=(
            "City planner at a regional agency — most of my work is "
            "transportation funding and parcel-level zoning research, not "
            "housing directly, but adjacent enough that I end up in the "
            "housing conversation.\n\n"
            "Joined the Coalition in 2023 after Member Defense walked my "
            "neighbor through fighting an illegal eviction notice. Stayed. "
            "Policy working group; not Coordinating Committee, not running "
            "for it.\n\n"
            "Also Member-at-Large on the Cedar Hollow HOA — different org, "
            "same name, sometimes asked about.\n\n"
            "If you delegate to me on Land Use Policy, the position statement "
            "on that topic is longer than the others. Worth reading before "
            "deciding."
        ),
        topics=[
            TopicVisibility('Land Use Policy', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Land Use Policy',
                text=(
                    "Qualified YIMBY. Support upzoning where existing zoning "
                    "is functioning as an artificial supply cap, paired with "
                    "affordability mandates at levels that get built (15-20% "
                    "in Millbrook's market) and tenant protections including "
                    "right-of-return with rent locks.\n\n"
                    "Don't support upzoning without mandates. Don't buy the "
                    "supply-alone-solves-affordability argument at any "
                    "politically feasible volume.\n\n"
                    "What I take seriously from Hector and Maya's position: "
                    "displacement from new construction in tight markets is "
                    "real, and protections are imperfect. The question isn't "
                    "whether displacement happens — it does, both with and "
                    "without new construction — but which path produces less "
                    "of it. I think the evidence favors building-with-mandates "
                    "over the supply-constraint status quo. I don't think "
                    "that question is settled, and the people most exposed "
                    "to displacement risk should weigh most heavily on it."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-C-01', 'yes',
                          "Voting yes after weighing it longer than most votes. The set-aside is low, the rider needs implementation specifics, the disagreement with Hector and Maya isn't resolved by this vote. What tips me is the leverage argument — implementation fight is where the affordability mandate gets enforced or doesn't, and inside-the-coalition has more pull there than outside."),
            VoteRationale('P-C-02', 'no',
                          "Same direction as Priya: agree with the goal, disagree about whether this amendment is the way to get it. Council members who voted for the current language respond to organized advocacy on implementation. Members who'd have voted no anyway won't be moved by an endorsement-conditional. The Coalition's organized capacity during implementation is the leverage; the amendment routes it through the wrong moment."),
            VoteRationale('P-C-04', 'yes',
                          "Came in leaning no over Will's doxing concern. Tenant-protection protocol amendment from extension 1 addressed most of it; Dana's capacity assessment in extension 2 addressed the rest. Voted yes during extension 2."),
            VoteRationale('P-C-05', 'yes', "Voted yes. Right to counsel permanence is the Coalition's most concrete near-term win."),
            VoteRationale('P-C-06', 'yes', "Dana's proposal addresses the capacity question that surfaced during P-C-04. Voted yes."),
            VoteRationale('P-C-07', 'yes', "Voted yes."),
            VoteRationale('P-C-08', 'approval_quarterly', "Quarterly is the right cadence. Approval only on quarterly."),
            VoteRationale('P-C-09', 'yes', "Maya's outreach plan is well-scoped. Voted yes."),
            VoteRationale('P-C-10', 'yes', "Foundational skill-building. Voted yes."),
            VoteRationale('P-C-11', 'yes', "Will's protocols are the right formalization. Voted yes."),
        ],
    ),
]
