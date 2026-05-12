"""
AFSCME Local 4021 Bible — Demo Content for liquiddemocracy.us

This module contains the full content set for the AFSCME Local 4021 demo
organization. Consumed by the Phase 23 seed pipeline to populate the demo's
state at reset moment.

Companion modules:
- hoa_bible.py (Cedar Hollow HOA)
- activist_bible.py (Westgate Tenants Coalition)
- trajectory_waypoints.py (per-proposal support-trajectory data, shared)

Dataclass shapes are imported from hoa_bible (illustrative).
"""

from .schema import (
    Member, TopicVisibility, PositionStatement, VoteRationale,
    DelegatePage, Comment, Proposal, NotificationEvent, NotificationFeed,
    OrgBible,
)


# =============================================================================
# AFSCME Local 4021
# =============================================================================

CHARTER = """\
AFSCME Local 4021 represents approximately 380 City of Millbrook public-sector
employees: Department of Public Works (sanitation, streets, water/sewer),
Parks Department (groundskeepers, recreation staff), and Public Library
(librarians, branch staff, library aides). Chartered in 1978. Officers:
President, Vice President, Recording Secretary, Treasurer, three Trustees.
Stewards (one per work site, ~12 total) handle on-the-ground member
representation. The Local is currently in the second year of a three-year
contract with the City; contract negotiations for the next agreement begin
in roughly 14 months. Member dues are set at the AFSCME-standard 1.5% of
base wages.\
"""

TONE_NOTES = """\
Earnest, plainspoken, occasionally wry. The voice is shop-floor: working
people talking about their working conditions in concrete terms. Not
academic-left, not anti-management performatively — pragmatic, sometimes
frustrated, sometimes proud. Officers write in slightly more formal register
than rank-and-file. Stewards have a distinct voice (proceduralist, references
to contract articles by number). When members are angry about something, they
say so directly; when they're proud, they say that too. Dry humor, especially
about management decisions. No slogans except in formal contexts.\
"""

RECENT_HISTORY = """\
- 2024 contract ratified narrowly (52% in favor); wage increases didn't fully cover health-insurance premium increases.
- Sanitation route restructuring grievance (Article 14 violation, unilateral change without consultation) in arbitration; outcome expected within months.
- Library workers more vocal after branch hour reduction proposals threatening library aide positions.
- President Keisha Brooks mid-term; seat not up. VP special election active after previous VP took job outside bargaining unit.\
"""


# -----------------------------------------------------------------------------
# Members
# -----------------------------------------------------------------------------

MEMBERS = [
    Member(user_id='local_keisha', display_name='Keisha Brooks',
           quick_login=True, role='President (DPW Sanitation supervisor)',
           notification_preset='high'),
    Member(user_id='local_sam', display_name='Sam Cole',
           quick_login=True, role='DPW Sanitation steward',
           notification_preset='high'),
    Member(user_id='local_dana', display_name='Dana Whitfield',
           quick_login=True, is_cross_org=True, role='Library steward (Reference librarian)',
           notification_preset='medium'),
    Member(user_id='local_tony', display_name="Tony D'Amico",
           quick_login=True, role='Treasurer (Parks Department)',
           notification_preset='medium'),
    Member(user_id='local_aisha', display_name='Aisha Robinson',
           quick_login=True, role='Parks Department (VP candidate)',
           notification_preset='high'),
    Member(user_id='local_walt', display_name='Walter "Walt" Hennessy',
           quick_login=True, role='Retiree member (former DPW Streets)',
           notification_preset='low'),
    Member(user_id='local_janet', display_name='Janet Reilly',
           quick_login=False, is_cross_org=True, role='Parks Department member',
           notification_preset='low'),
    # Non-quick-login named members:
    Member(user_id='local_marisol', display_name='Marisol Vega',
           quick_login=False, role='Library worker (VP candidate)'),
    Member(user_id='local_frank', display_name='Frank Boczek',
           quick_login=False, role='DPW Water/Sewer steward'),
]


# -----------------------------------------------------------------------------
# Delegate Pages
# -----------------------------------------------------------------------------

DELEGATE_PAGES = [
    DelegatePage(
        member_user_id='local_keisha',
        page_visibility='public',
        intro=(
            "President, mid-second term. DPW Sanitation, route supervisor — "
            "worker side, in the bargaining unit. Nineteen years with the "
            "City, thirteen in the Local in some capacity.\n\n"
            "`public_accepting` on Contract & Negotiations and Grievances. Both "
            "topics matter for the next contract; both deserve more delegator "
            "scrutiny than they usually get. If you delegate to me, read the "
            "vote rationales — that's where I show my work."
        ),
        topics=[
            TopicVisibility('Contract & Negotiations', 'public_accepting'),
            TopicVisibility('Grievances', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Contract & Negotiations',
                text=(
                    "The 2024 contract ratified at 52%. That's not a mandate; "
                    "that's a membership that took the best deal available and "
                    "made clear they expected better next time. My job between "
                    "now and the next negotiation is keeping the Local unified "
                    "enough that 'better next time' is achievable.\n\n"
                    "I'll vote with the bargaining team's strategic position on "
                    "pre-commitments, public stances, and demand structure. I'll "
                    "vote against tactical moves that I think weaken our "
                    "negotiating posture even when they have membership "
                    "support — and explain my reasoning so delegators can pull "
                    "the delegation if they disagree."
                ),
            ),
            PositionStatement(
                topic='Grievances',
                text=(
                    "Article 14 is the foundation of how this Local stays "
                    "meaningful between contracts. When management violates the "
                    "contract, we grieve. When the contract is ambiguous, we "
                    "interpret in favor of past practice. When management "
                    "normalizes unilateral changes without grievance, the next "
                    "contract starts from a weaker position.\n\n"
                    "`public_accepting` here for the same reason as Contract: "
                    "this topic deserves member attention, not just officer "
                    "judgment."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-L-01', 'yes', "Proposer; voting yes."),
            VoteRationale('P-L-02', 'yes', "Solidarity statement, broad consensus, voting yes."),
            VoteRationale('P-L-03', 'yes', "Library work is union work. Dana's proposal is well-scoped."),
            VoteRationale('P-L-05', 'yes', "Voted yes. Tony's case is right; the strike fund needs to be ready before negotiations start, and rebuilding it after they begin is too late."),
            VoteRationale('P-L-07', 'yes', "Proposer; voting yes. The case is in the rationale."),
            VoteRationale('P-L-08', 'yes', "Sam's safety audit is overdue."),
            VoteRationale('P-L-09', 'yes', "Stipending member work matters when the work matters."),
            VoteRationale('P-L-10', 'yes', "Proposer; voting yes."),
        ],
    ),

    DelegatePage(
        member_user_id='local_sam',
        page_visibility='public',
        intro=(
            "DPW Sanitation steward, eighteen years. Twenty-four years with the "
            "City total. Spent most of those years working the same routes I "
            "now represent.\n\n"
            "`public_accepting` on Grievances and Contract Interpretation. If "
            "you delegate to me on either: the contract is the floor, past "
            "practice is the ceiling, and management bears the burden when "
            "they want something the contract doesn't give them. That framework "
            "determines almost every vote I cast on these topics."
        ),
        topics=[
            TopicVisibility('Grievances', 'public_accepting'),
            TopicVisibility('Contract Interpretation', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Grievances',
                text=(
                    "Grievances are how the contract stays meaningful between "
                    "negotiations. The Local's grievance record is the "
                    "credibility we bring to the next bargaining table. Weak "
                    "grievance work in year two means weak contract terms in "
                    "year four.\n\n"
                    "Past pattern: we filed 14 grievances in 2018, 11 in 2019, "
                    "9 in 2020. Win rate held above 60% through 2020. In "
                    "2021-2022 the volume dropped to 5 per year combined, and "
                    "the win rate dropped with it. Reason was capacity, not "
                    "contract clarity — fewer stewards, less training. We "
                    "grieved this in 2022 internally and started rebuilding; "
                    "the Sanitation route case is the first major case in the "
                    "rebuild.\n\n"
                    "I vote to grieve when the contract is clear and "
                    "management's done something the contract doesn't allow. I "
                    "vote not to grieve when past practice has already settled "
                    "the question against us, even if I think we should "
                    "renegotiate it. The contract says what it says."
                ),
            ),
            PositionStatement(
                topic='Contract Interpretation',
                text=(
                    "Interpretive framework: the contract language is the floor "
                    "of what we're entitled to. Past practice that's been "
                    "established without grievance becomes the ceiling of what "
                    "we can claim under the current language. Management bears "
                    "the burden of proving operational necessity when they want "
                    "to deviate from established practice. If a steward or "
                    "officer wants to interpret in a way that contradicts past "
                    "practice, the burden is on them to show why the change is "
                    "justified.\n\n"
                    "This framework is conservative on purpose. It treats the "
                    "contract as a long-run instrument and treats interpretive "
                    "precedent as a form of contract-strengthening between "
                    "bargaining rounds."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-L-01', 'yes', "Yes. The precedent risk is the case."),
            VoteRationale('P-L-02', 'yes', "Proposer; yes."),
            VoteRationale('P-L-03', 'yes', "Voted yes. Spoke to the priorities question in comments — Dana's response addressed it."),
            VoteRationale('P-L-05', 'yes', "The strike fund needs to be ready. Voted yes."),
            VoteRationale('P-L-07', 'yes', "Pre-commitment is the right move. We gave this up internally in 2024 and the membership paid for three years. Voted yes."),
            VoteRationale('P-L-08', 'yes', "Proposer; yes."),
            VoteRationale('P-L-09', 'yes', "The editor's been doing real work. Stipend's appropriate."),
            VoteRationale('P-L-10', 'yes', "Karen Davila's training is what built the 2020 cohort. Yes."),
        ],
    ),

    DelegatePage(
        member_user_id='local_dana',
        page_visibility='public',
        intro=(
            "Library steward. Reference librarian at the main branch downtown, "
            "seven years with the City. Local 4021's first Library steward — "
            "the position was added two years ago after the Library workers' "
            "first formal grievance cluster.\n\n"
            "`public_accepting` on Library Issues and Health & Safety. The "
            "Library workers are the Local's newest constituency and the work "
            "isn't fully integrated yet; I want to be visible to delegators "
            "because that visibility is part of how the integration happens.\n\n"
            "I also organize with Westgate Tenants Coalition. It comes up here "
            "when the issues overlap — library branch hours affect tenants in "
            "the neighborhoods we'd cut from, and the Local's experience "
            "formalizing capacity has informed how I think about the Coalition's "
            "work. I'll flag the cross-org connection in comments when it's "
            "relevant."
        ),
        topics=[
            TopicVisibility('Library Issues', 'public_accepting'),
            TopicVisibility('Health & Safety', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Library Issues',
                text=(
                    "Library workers are the Local's smallest department by "
                    "headcount and the most exposed to budget-cycle volatility. "
                    "Branch hour reductions, library aide position cuts, and "
                    "contract-out threats have all surfaced in the last 24 "
                    "months. Each one is a discrete issue; collectively they're "
                    "a pattern.\n\n"
                    "My voting framework: every Library-impacting proposal also "
                    "needs to ask what it does for the Local's long-term capacity "
                    "to fight the next round. Defensive wins matter; building "
                    "toward proactive contract language matters more.\n\n"
                    "If you delegate to me here, expect votes that prioritize "
                    "building durable Library workforce protections in the next "
                    "contract over isolated wins on the current cycle's threats."
                ),
            ),
            PositionStatement(
                topic='Health & Safety',
                text=(
                    "Practice over rhetoric. When I started as steward I read "
                    "the past five years of Health & Safety filings — almost "
                    "all of them had been resolved with management's verbal "
                    "assurances and no documentary follow-up. Two of those "
                    "situations escalated to grievable events within twelve "
                    "months.\n\n"
                    "I vote for proposals that document conditions and create "
                    "paper trails. I vote against proposals that route safety "
                    "issues through informal channels even when those channels "
                    "seem faster."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-L-01', 'yes', "Yes. Sam's framing on Article 14 precedent is the case."),
            VoteRationale('P-L-02', 'yes', "Solidarity statement; voting yes."),
            VoteRationale('P-L-03', 'yes', "Proposer; yes."),
            VoteRationale('P-L-05', 'yes', "Tony's case is right and Brother Hennessy's historical reference matters. Voted yes."),
            VoteRationale('P-L-07', 'yes', "Pre-commitment binds the team to bring real-time trades back for membership review. Voted yes."),
            VoteRationale('P-L-08', 'yes', "Documentation matters more than informal resolution. Voted yes."),
            VoteRationale('P-L-09', 'yes', "Stipending the editor reflects that we treat member work as work."),
            VoteRationale('P-L-10', 'yes', "The 2019 training cohort built the grievance capacity that the Sanitation route case is testing. Yes."),
        ],
    ),

    DelegatePage(
        member_user_id='local_tony',
        page_visibility='public',
        intro=(
            "Treasurer, third term. Twenty-six years with the City — Parks "
            "Department, heavy equipment operator.\n\n"
            "`public_accepting` on Local Finances and Strike Fund. By my count, "
            "neither topic gets the member attention it needs between "
            "negotiations, and that's the season we're in now."
        ),
        topics=[
            TopicVisibility('Local Finances', 'public_accepting'),
            TopicVisibility('Strike Fund', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Local Finances',
                text=(
                    "The Local's financial discipline is solidarity in slow "
                    "motion. Dues income, strike fund accumulation, legal "
                    "reserve — they're the difference between credible threats "
                    "and bluffs at the bargaining table.\n\n"
                    "Current strike fund: $187K at 0.5% of base wages "
                    "contribution rate. Assets-to-monthly-payroll ratio that "
                    "supports roughly six weeks of strike pay for the full "
                    "membership. Health of the operating fund is steady; legal "
                    "reserve is thin after the Sanitation arbitration "
                    "authorization.\n\n"
                    "I vote for spending that builds bargaining capacity and "
                    "against spending that doesn't."
                ),
            ),
            PositionStatement(
                topic='Strike Fund',
                text=(
                    "Strike fund readiness is the silent variable in every "
                    "contract negotiation. The City reads our fund balance the "
                    "same way we'd read theirs if they had one. By my count, "
                    "every contract we've ratified since 1998 has been better "
                    "when our fund was above ten weeks of cover than below it.\n\n"
                    "The proposal to increase contribution to 0.75% (P-L-05) "
                    "moves us from six weeks to nine. Worth the cost."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-L-01', 'yes', "$12K is appropriate given the precedent risk. Voted yes."),
            VoteRationale('P-L-02', 'yes', "Solidarity resolution; voted yes."),
            VoteRationale('P-L-03', 'yes', "Dana's proposal is well-scoped and Brother Cole's question got the right answer. Voted yes."),
            VoteRationale('P-L-05', 'yes', "Proposer; yes."),
            VoteRationale('P-L-07', 'yes', "Pre-commitment is the right call. Voted yes."),
            VoteRationale('P-L-08', 'yes', "Sam's audit is overdue. Voted yes."),
            VoteRationale('P-L-09', 'yes', "Proposer; yes."),
            VoteRationale('P-L-10', 'yes', "Karen Davila's training has paid back four times its cost in grievance outcomes. Yes."),
        ],
    ),

    DelegatePage(
        member_user_id='local_aisha',
        page_visibility='public',
        intro=(
            "Parks Department, recreation programmer. Eleven years with the "
            "City. Active in the Local for six years — working group on "
            "grievance support, on health & safety, on member outreach.\n\n"
            "Running for Vice President in the current special election.\n\n"
            "Transparent only on Parks Issues. Not accepting new delegations "
            "during the campaign — would rather members hear my positions and "
            "decide than delegate to a candidate."
        ),
        topics=[
            TopicVisibility('Parks Issues', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Parks Issues',
                text=(
                    "Parks Department has been underrepresented in Local "
                    "leadership since I started — no Parks member has held an "
                    "officer position since 2017. The work is no less skilled "
                    "than DPW or Library work; the underrepresentation is "
                    "structural, and it shows up in how Parks-specific issues "
                    "get prioritized.\n\n"
                    "My approach: vote with the broader Local on cross-"
                    "departmental issues, vote for Parks-specific improvements "
                    "when they're materially affected, and use my engagement "
                    "to make sure Parks voices reach the bargaining team.\n\n"
                    "Transparent rather than `public_accepting` because I'm "
                    "running for office. If I win the VP race, I'll reassess."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-L-01', 'yes', "Voted yes; the precedent matters across departments."),
            VoteRationale('P-L-02', 'yes', "Solidarity resolution; yes."),
            VoteRationale('P-L-03', 'yes', "Voted yes. Building on Brother Cole's concern about sequencing — Dana's response addressed it well."),
            VoteRationale('P-L-05', 'yes', "Voted yes. Acknowledged the cost concern in comments; the case is the case."),
            VoteRationale('P-L-07', 'yes', "Voted yes. Building on Brother Cole's framing about the 2024 contract — pre-commitment is how we don't repeat that."),
            VoteRationale('P-L-08', 'yes', "Documentation is the foundation. Yes."),
            VoteRationale('P-L-09', 'yes', "Stipending real work matters. Yes."),
            VoteRationale('P-L-10', 'yes', "Training builds capacity. Yes."),
        ],
    ),

    DelegatePage(
        member_user_id='local_walt',
        page_visibility='public',
        intro=(
            "Retired from DPW Streets eight months ago. Thirty-one years in. "
            "Still a Local member at retiree dues — vote on retiree issues, "
            "comment on anything.\n\n"
            "Transparent only on Pension & Retiree Issues. I'm here to share "
            "what I remember and what I've learned; the votes themselves should "
            "be the membership's. Don't take new delegations on principle."
        ),
        topics=[
            TopicVisibility('Pension & Retiree Issues', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Pension & Retiree Issues',
                text=(
                    "The pension is what makes a long career here viable. When "
                    "we negotiated the 1998 contract, the pension formula was "
                    "the demand that almost broke negotiations and the one we "
                    "held the longest on. Twenty-six years later, the formula "
                    "is what makes my retirement work.\n\n"
                    "I vote to protect the existing pension structure. I vote "
                    "against changes that would weaken vesting, reduce employer "
                    "contributions, or alter the benefit calculation, even when "
                    "those changes are framed as solvency measures. Pension "
                    "solvency questions belong in actuarial review, not in "
                    "bargaining-table compromise."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-L-01', 'yes', "$12K for arbitration is right. I remember when we tried the 2011 Streets case without outside counsel; we won, but barely, and it cost us in subsequent grievance posture."),
            VoteRationale('P-L-02', 'yes', "Solidarity matters. Voted yes."),
            VoteRationale('P-L-05', 'yes', "Voted yes. The pre-1990s strike fund collapse is what makes 9.5 weeks of cover worth $35K/year."),
            VoteRationale('P-L-07', 'yes', "Voted yes. In '98, '07, and '13, pre-commitment on the priority demand strengthened our position. In '17 and '24 we kept the priority demand internal; in both cases the bargaining team gave it up under pressure. The pattern is clear enough."),
            VoteRationale('P-L-10', 'yes', "Karen Davila's training has been the foundation of the Local's grievance capacity for fifteen years."),
        ],
    ),

    # Janet Reilly in Local 4021: page_visibility='private' — no delegate page rendered.
    # See cross-org notes.
]


# -----------------------------------------------------------------------------
# Proposals
# -----------------------------------------------------------------------------

PROPOSALS = [
    Proposal(
        proposal_id='P-L-01',
        title='Authorization of Legal Expenses for Sanitation Grievance Arbitration',
        proposer_user_id='local_keisha',
        voting_method='binary',
        state_at_reset='passed, 28 days ago (87-13)',
        body=(
            "Requesting authorization of $12K for outside counsel during the "
            "Sanitation route restructuring arbitration.\n\n"
            "Background: The City changed Sanitation route assignments without "
            "consultation, in apparent violation of Article 14, Section 3. The "
            "grievance was filed in March; arbitration is scheduled within four "
            "months.\n\n"
            "The $12K covers external labor counsel for arbitration prep and "
            "the hearing itself. The Local's standard practice on Article 14 "
            "cases has been to use member representation, but the route "
            "restructuring case has procedural complexity (multi-route impact, "
            "City's claim of operational necessity exception) that I don't "
            "think we should walk into without specialist counsel.\n\n"
            "Look — I know the cost is real. Tony will speak to the financial "
            "impact. What I'd ask the membership to weigh: a loss at "
            "arbitration sets the precedent that the City can restructure "
            "without consultation under the operational necessity claim, which "
            "would affect every department under the contract. The cost of "
            "losing this arbitration is much higher than $12K."
        ),
    ),

    Proposal(
        proposal_id='P-L-02',
        title='Resolution of Member Solidarity with Sanitation Grievance',
        proposer_user_id='local_sam',
        voting_method='binary',
        state_at_reset='passed, 21 days ago (94-6)',
        body=(
            "Proposing a resolution of member solidarity with the Sanitation "
            "route grievance currently in arbitration. Non-binding statement.\n\n"
            "The resolution language: 'Local 4021 members affirm their support "
            "for the grievance filed regarding unilateral Sanitation route "
            "restructuring, and direct that the Local's resources continue to "
            "be made available to pursue the grievance through arbitration and "
            "any subsequent proceedings.'\n\n"
            "What the resolution does: signals to the City and to the "
            "arbitrator that the membership backs the case rather than treating "
            "it as a steward-and-officer initiative. Past arbitrations have "
            "weighted membership engagement in their findings.\n\n"
            "What it doesn't do: doesn't bind future Locals, doesn't pre-judge "
            "the arbitration outcome, doesn't commit additional funds beyond "
            "what's already been authorized.\n\n"
            "The contract says what it says; this resolution says the "
            "membership agrees we should make management prove it."
        ),
    ),

    Proposal(
        proposal_id='P-L-03',
        title='Library Branch Hours Defense Campaign',
        proposer_user_id='local_dana',
        voting_method='binary',
        state_at_reset='passed, 12 days ago (78-22) [Library sub-org]',
        body=(
            "Proposing the Local coordinate a response to the City's proposed "
            "branch hour reductions: member testimony at the City Council vote, "
            "an op-ed campaign in the Ledger, and formal engagement with the "
            "Council's Public Services committee.\n\n"
            "Background: the City budget proposal cuts evening hours at three "
            "of the five branches, eliminating ~22 hours/week of library aide "
            "work distributed across six positions. Two of those positions are "
            "full-time; their elimination is a layoff in everything but "
            "contractual language.\n\n"
            "The campaign components:\n"
            "- Testimony from Library workers and patrons at the Public "
            "Services committee hearing and the full Council vote\n"
            "- Op-ed series in the Ledger framing branch hour reductions as "
            "both a labor issue and a public services issue\n"
            "- Coordinated engagement with the four Council members who voted "
            "against last year's library funding cut\n\n"
            "The case for Local resources: this is union work even though it's "
            "adjacent to broader public-services advocacy. The aide positions "
            "are bargaining-unit positions. Preserving them means defending "
            "the membership's economic interest, not just defending public "
            "libraries.\n\n"
            "I want to acknowledge what this proposal doesn't address: the "
            "underlying pattern of the City treating Library as a discretionary "
            "cut target. We can't fix that pattern through one campaign. We "
            "can win this round."
        ),
    ),

    Proposal(
        proposal_id='P-L-04',
        title='Vice President Special Election 2026',
        proposer_user_id='local_keisha',  # election proposals from President
        voting_method='rcv',
        state_at_reset='voting, hour 30 of 96',
        body=(
            "Special election to fill the Vice President seat. Two candidates "
            "running. RCV with 2 candidates collapses to first-choice majority.\n\n"
            "Voting closes 66 hours after reset."
        ),
        candidate_statements={
            'local_aisha': (
                "Running for Vice President. Eleven years with the City, six in "
                "the Local.\n\n"
                "What I'd bring to the role: a Parks voice in the leadership "
                "for the first time in seven years, working relationships with "
                "both the Library and DPW factions, and continuity with the "
                "bargaining team's current direction. The next contract "
                "negotiation starts in fourteen months; the VP role is going "
                "to be heavily involved in preparation.\n\n"
                "What I'd prioritize: bridge work between Parks and Library on "
                "shared interests (both are smaller departments facing "
                "budget-cycle volatility), engagement with the Sanitation "
                "arbitration's broader implications for all DPW work, and "
                "visible Parks Department participation in contract preparation.\n\n"
                "I want to acknowledge: my opponent Marisol Vega brings a "
                "stronger Library perspective and has been more publicly active "
                "on contract preparation than I have. Members who prioritize "
                "either of those over my Parks angle should vote that way.\n\n"
                "Building on what Sister Vega has said in her statement: the "
                "Library/DPW tension is real, and the next VP needs to manage "
                "it actively rather than navigate around it. I think my Parks "
                "background gives me a useful position for that work — Parks "
                "is in neither faction. Marisol's view is that the Library "
                "workers need direct representation in leadership; that's a "
                "defensible position and I'd encourage members to weigh both "
                "arguments."
            ),
            'local_marisol': (
                "Library aide turned library assistant, six years with the "
                "City. Running for Vice President because the Library "
                "workforce needs direct representation in Local leadership and "
                "the current officer structure doesn't provide it.\n\n"
                "If we're being honest with each other, the Library/DPW "
                "tension in this Local is structural. It's not personal "
                "between members; it's about which department's priorities "
                "get treated as the Local's priorities. Right now, when "
                "there's a conflict, DPW issues take precedence — not because "
                "anyone decided that, but because DPW has the officer "
                "positions and the longer institutional history.\n\n"
                "What I'd bring: a Library voice in the leadership when "
                "contract preparation begins. Substantive engagement with the "
                "Library aide position protections that need to be in the next "
                "contract. A direct argument inside leadership for treating "
                "Library issues with the same weight as DPW issues.\n\n"
                "My opponent Aisha Robinson brings a Parks perspective and "
                "bridge-building skill set. Those are real strengths. Members "
                "who think the bridge approach is what the Local needs should "
                "vote for her. Members who think the Library workers need "
                "direct representation should vote for me.\n\n"
                "This isn't about Aisha or me. It's about whether the Local "
                "treats its smallest department as a member of the family or "
                "as a guest at the table."
            ),
        },
    ),

    Proposal(
        proposal_id='P-L-05',
        title='Strike Fund Contribution Increase',
        proposer_user_id='local_tony',
        voting_method='binary',
        state_at_reset='passed, 18 days ago (54-46) — close vote',
        body=(
            "Proposing an increase in strike fund contribution from 0.5% to "
            "0.75% of base wages, effective immediately.\n\n"
            "The numbers:\n"
            "- Current contribution: 0.5% across roughly $14M annual base "
            "wages = $70K/year to the fund.\n"
            "- Proposed contribution: 0.75% = $105K/year. Net increase: "
            "$35K/year.\n"
            "- Current strike fund balance: $187K, covering ~6 weeks of "
            "strike pay at full membership.\n"
            "- Projected balance at the 2027 contract deadline under 0.5%: "
            "$237K, ~7.5 weeks.\n"
            "- Projected balance under 0.75%: $292K, ~9.5 weeks.\n\n"
            "What 9.5 weeks of cover changes that 7.5 doesn't: the City's "
            "strategic calculation about whether we'd actually walk. Six weeks "
            "is symbolic; nine is operational. They know the difference.\n\n"
            "I want to acknowledge the cost is real. For a member at the "
            "median wage, the increase is roughly $7/week. That's not nothing. "
            "The case is that $7/week now produces better contract terms in "
            "fourteen months, which compounds over the three-year contract."
        ),
    ),

    Proposal(
        proposal_id='P-L-06',
        title='Trustee Election 2026',
        proposer_user_id='local_keisha',  # election from President
        voting_method='stv',
        state_at_reset='voting, hour 42 of 120',
        body=(
            "Trustee election. Three seats up; five candidates running. "
            "Single Transferable Vote with cascade for vote transfers.\n\n"
            "Candidates: see candidate statements. Voting closes 78 hours "
            "after reset."
        ),
        # STV candidate statements omitted (non-quick-login candidates not produced in main content).
    ),

    Proposal(
        proposal_id='P-L-07',
        title='Cost-of-Living Adjustment Bargaining Demand for 2027 Contract',
        proposer_user_id='local_keisha',
        voting_method='binary',
        state_at_reset='voting, SRR extension 1, hour 14 of 24 [SRR extended-then-closed-early]',
        body=(
            "Authorizing the bargaining team to make a specific cost-of-living "
            "adjustment demand a non-negotiable in the upcoming contract "
            "negotiations.\n\n"
            "The demand: COLA tied to regional CPI, computed annually, with a "
            "floor of 2.5% and no ceiling. Currently we have flat-rate annual "
            "increases negotiated as part of the wage package; in three of the "
            "past five years, real wages declined because the negotiated "
            "increase didn't cover inflation.\n\n"
            "The strategic question: should this be a public pre-commitment "
            "now, or should it remain in the bargaining team's internal "
            "package?\n\n"
            "The case for public pre-commitment: when we kept this demand "
            "internal in 2024, the bargaining team gave it up early to preserve "
            "other priorities. Public commitment establishes it as a floor — "
            "the bargaining team can't trade it away without going back to the "
            "membership. That changes the negotiation.\n\n"
            "The case against — and I want to acknowledge this seriously: a "
            "public pre-commitment also tells the City exactly what we're "
            "going to insist on. That gives them time to structure their "
            "opening offer around assuming we'll concede other ground to "
            "protect COLA. Some members think this is the wrong move; I "
            "disagree, but I respect the analysis.\n\n"
            "I'm proposing public pre-commitment. The bargaining team needs "
            "the membership mandate; the membership deserves a chance to weigh "
            "in before negotiations start."
        ),
    ),

    Proposal(
        proposal_id='P-L-08',
        title='Health and Safety Equipment Audit (DPW)',
        proposer_user_id='local_sam',
        voting_method='binary',
        state_at_reset='passed, 9 days ago (81-19) [DPW sub-org]',
        body=(
            "Proposing a steward-led audit of safety equipment across DPW work "
            "sites, with findings reported to management and any deficiencies "
            "entered into grievance procedure if not remediated within 60 days "
            "of notice.\n\n"
            "Background: last comprehensive safety audit was 2018. In the six "
            "years since, equipment has aged, work site conditions have "
            "changed (route restructuring among them), and several near-misses "
            "haven't been formally documented. The audit creates a documentary "
            "record management can't dismiss.\n\n"
            "Scope: sanitation truck operating equipment, Streets work zone "
            "safety materials, Water/Sewer confined space equipment. Audit "
            "conducted by stewards from each work site, results compiled by "
            "the steward council.\n\n"
            "Should have done this five years ago. Brother Hennessy will "
            "probably say so."
        ),
    ),

    Proposal(
        proposal_id='P-L-09',
        title='Local Newsletter Editor Stipend',
        proposer_user_id='local_tony',
        voting_method='binary',
        state_at_reset='passed, 45 days ago (76-24)',
        body=(
            "Proposing a $200/month stipend for the rank-and-file member who "
            "edits the Local's quarterly newsletter.\n\n"
            "Current editor (Ravi Patel) has been doing this work since 2022. "
            "By my count, he averages 8-12 hours per quarter on layout, copy "
            "editing, and distribution coordination. The Local has stipended "
            "other member work — bargaining team members get per diem during "
            "negotiations, election coordinators get a small honorarium — but "
            "newsletter work has always been treated as volunteer.\n\n"
            "$200/month works out to approximately $50/hour at the editor's "
            "typical workload. Not generous; appropriate.\n\n"
            "Stipending member work when the work matters is part of how we "
            "recognize that member labor has value."
        ),
    ),

    Proposal(
        proposal_id='P-L-10',
        title='Steward Training Workshop Authorization',
        proposer_user_id='local_keisha',
        voting_method='binary',
        state_at_reset='passed, 60 days ago (91-9)',
        body=(
            "Requesting $3K for a one-day steward training workshop with "
            "outside trainer Karen Davila (AFSCME District 1, fifteen years "
            "training stewards in contract interpretation and grievance "
            "handling).\n\n"
            "Twelve current stewards; eight have been in the role for over "
            "five years and would benefit from refresh; four were appointed "
            "in the last 18 months and need foundational training. Last "
            "formal training was 2019.\n\n"
            "The case is straightforward — stewards are how the contract gets "
            "enforced day-to-day, and we've been under-investing in their "
            "development."
        ),
    ),
]


# -----------------------------------------------------------------------------
# Drafts
# -----------------------------------------------------------------------------

DRAFTS = [
    Proposal(
        proposal_id='P-L-NEW-D1',
        title='Grievance Procedure Refinement (Draft)',
        proposer_user_id='local_sam',
        voting_method='binary',
        state_at_reset='draft (not yet posted for deliberation)',
        body=(
            "Draft proposal codifying internal Local procedures for early-stage "
            "grievance handling, based on lessons from the Sanitation route "
            "case.\n\n"
            "Specifically: the proposal would establish that any potential "
            "Article 14 violation (operational changes without consultation) "
            "be documented and reviewed by the steward council within 14 days "
            "of management notice, regardless of whether a grievance is filed. "
            "Most cases won't warrant a full grievance; documenting them "
            "anyway preserves the record for future negotiations and prevents "
            "past practice from drifting through accumulated unchallenged "
            "actions.\n\n"
            "Will post after the VP election concludes — don't want it "
            "competing with that for member attention."
        ),
    ),
]


# -----------------------------------------------------------------------------
# Comments
# -----------------------------------------------------------------------------

COMMENTS = [
    # P-L-01
    Comment('P-L-01', 'local_keisha', 'voting hour 4',
            "Voting yes; the precedent risk is what makes this worth the cost."),
    Comment('P-L-01', 'local_sam', 'voting hour 8',
            "The precedent argument matters. Article 14, Section 3 reads 'operational changes affecting bargaining unit work shall be subject to consultation prior to implementation.' We grieved a similar case in 2011 against the Streets reorganization — won at the arbitration level on the same language. If we lose this one, the precedent reverses. That's the case for outside counsel."),
    Comment('P-L-01', 'local_dana', 'voting hour 12',
            "Voted yes. The precedent argument applies across departments, not just Sanitation."),
    Comment('P-L-01', 'local_tony', 'voting hour 16',
            "$12K from the legal reserve, currently at $34K. Leaves $22K for the rest of the year. By my count, that's adequate for routine arbitration support but doesn't leave margin for a second case."),
    Comment('P-L-01', 'local_walt', 'voting hour 24',
            "I remember the 2011 Streets case. We won at arbitration but the City came back six months later with a different operational-necessity argument and we'd already shown them how thin our counsel was. Outside counsel is appropriate here."),
    Comment('P-L-01', 'local_frank', 'voting hour 30',
            "Voted yes but the Local needs more discipline next contract. We left money on the table last time, and outside counsel for this arbitration is the cost of cleaning that up. Won't fix the pattern by itself."),

    # P-L-02
    Comment('P-L-02', 'local_sam', 'voting hour 4',
            "Voting yes; the membership's backing strengthens the case."),

    # P-L-03 (includes cross-org addendum from Stage 6.5)
    Comment('P-L-03', 'local_dana', 'deliberation hour 4',
            "Glad to hear the early questions; the proposal is sharper for them."),
    Comment('P-L-03', 'local_sam', 'deliberation hour 12',
            "I want to support this proposal and I want to be honest about the concern I have with it.\n\n"
            "The Sanitation grievance arbitration is the Local's most important active case. The Library branch hours fight is also important, and it's winnable on a different timeline. We can fight on multiple fronts but our political capital isn't infinite, and I don't want to find out in nine months that we under-invested in arbitration prep because the Library campaign demanded coordination capacity we needed elsewhere.\n\n"
            "This isn't a vote against Dana's proposal. It's a question about whether we have a plan for sequencing."),
    Comment('P-L-03', 'local_dana', 'deliberation hour 18',
            "Brother Cole, I want to engage with this carefully because the concern is right and the framing matters.\n\n"
            "Political capital isn't infinite — agreed. The Sanitation arbitration is the bigger fight — agreed. What I'd push back on is the framing that the Library campaign competes with arbitration prep for capacity.\n\n"
            "The arbitration prep is concentrated in the next three months: legal team work, member preparation for hearings, document compilation. That's a steward-and-officer effort with specific personnel demands. The Library campaign builds toward the Council vote six months out: testimony coordination, op-ed authorship, member outreach in branch-specific neighborhoods. Different timeline, different personnel.\n\n"
            "The two efforts overlap in members' attention bandwidth, not in operational capacity. We'd be asking the membership to care about two things at once, which they're capable of, rather than asking the same five stewards to do two things at once, which they're not.\n\n"
            "I do think you're right about the underlying pattern: the Library workers shouldn't be in defensive posture every budget cycle. Building that into the next contract is the longer-run work. This campaign is the current cycle."),
    Comment('P-L-03', 'local_sam', 'deliberation hour 24',
            "Dana's right that the timelines don't overlap the way I was framing them. The arbitration prep is concentrated in the next three months; the Library campaign builds toward the Council vote in six. Different windows, different capacity demands. Voting yes."),
    Comment('P-L-03', 'local_keisha', 'deliberation hour 26',
            "Brother Cole's right that political capital isn't infinite. He's also right that the Library campaign is winnable on a different timeline than the arbitration; the two fights don't compete for the same capital. Voting yes."),
    Comment('P-L-03', 'local_dana', 'deliberation hour 30',  # Cross-org addendum from Stage 6.5
            "One more piece of why this matters as a Local fight rather than just a library-system fight. Branch hour reductions hit tenants in the affected neighborhoods, not just library workers. The two branches with the deepest evening cuts in the City's proposal are Westgate and South Branch — both serving tenant-majority neighborhoods where library hours are how people without home internet do job applications, access government services, and complete homework with their kids. Defending the aide positions is defending the access those positions provide. Tenants and workers on the same side of this one, which is the kind of alignment the Local should be visible on."),
    Comment('P-L-03', 'local_aisha', 'voting hour 22',
            "Voted yes. Library issues are Local issues. Building on Dana's reply to Brother Cole's concern — the timeline framing is the right one."),

    # P-L-04 (VP RCV election)
    Comment('P-L-04', 'local_marisol', 'voting hour 16',
            "Library aide position protections, branch hour minimums in contract language (not just budget cycle vulnerability), and a Library steward presence on the bargaining team. If we're being honest with each other, those should be non-negotiables, not preferences."),
    Comment('P-L-04', 'local_aisha', 'voting hour 20',
            "On contract preparation: I'd prioritize wage protection through COLA, health insurance cost-sharing structure, and Library workforce protections in that order. Let me check on the Parks-specific issues that have surfaced in pre-contract surveys and report back with specifics."),

    # P-L-05
    Comment('P-L-05', 'local_tony', 'voting hour 8',
            "Math is in the rationale. By my count, $7/week per median member is the price of ten weeks of cover. Voted yes."),
    Comment('P-L-05', 'local_sam', 'voting hour 14',
            "Brother D'Amico has the math. I'll add: we grieved the 2017 contract's strike fund inadequacy after the fact — found ourselves with two weeks of strike pay and management knew it. Reaching the table with nine weeks of cover changes the negotiation."),
    Comment('P-L-05', 'local_frank', 'voting hour 18',
            "We left money on the table last time. We shouldn't have to pay extra now to clean it up. Voting no."),
    Comment('P-L-05', 'local_walt', 'voting hour 22',
            "The strike fund was below two weeks of cover at the '89 contract deadline. We came back to the membership for emergency contributions, got them, but the City had eight weeks to position around our weakness during that window. Negotiated terms reflected that. We've never been below five weeks at a contract deadline since. The 0.75% contribution is the discipline that produced fifteen years of credible negotiating posture."),
    Comment('P-L-05', 'local_keisha', 'voting hour 24',
            "Tony's math is right. The strike fund at $0.5% would cover six weeks of strike pay; at $0.75% it covers nine. Negotiations could go either way, and the difference between six and nine weeks is meaningful."),
    Comment('P-L-05', 'local_dana', 'voting hour 30',
            "Voted yes; nine weeks of strike cover changes what we can credibly walk away from."),
    Comment('P-L-05', 'local_tony', 'voting hour 30',
            "The contribution increase compounds. Starting now versus six months from now is the difference between $292K at deadline and $267K. Six months of $35K accumulates."),
    Comment('P-L-05', 'local_frank', 'voting hour 35',
            "Walt's right about the '89 cycle. The discipline argument has to start somewhere. Changed my vote."),
    Comment('P-L-05', 'local_aisha', 'voting hour 36',
            "The $7/week cost is real, and I want to acknowledge that for members at the lower end of the wage scale it's more meaningful than the median number suggests. Voting yes anyway because the strike fund readiness affects every member's contract outcome, not just the median member's. Brother Hennessy's historical reference about the pre-1990s collapse is the case."),
    Comment('P-L-05', 'local_marisol', 'voting hour 40',
            "Voted yes. Where I'd differ slightly from Sister Robinson's framing: the cost concern matters most for lower-wage members, which is the Library workforce. Library aides are at the bottom of the wage scale and the $7/week is closer to $5/week for them but it's a larger share of their take-home. The strike fund readiness is for them too, though. Voting yes."),

    # P-L-07 (SRR extended-then-closed-early)
    Comment('P-L-07', 'local_sam', 'deliberation hour 6',
            "The contract says what it says, and for three years the 2024 contract has been saying that real wages decline when COLA isn't built in. Brother Boczek and others who voted no on 2024 ratification were right that we left money on the table. The pre-commitment is how we don't do that again.\n\n"
            "I want to be clear about why this matters as a public commitment rather than internal: bargaining teams take pressure. When the City's package looks comprehensive and time is running out, COLA gets traded for things that feel more concrete. Public commitment binds the team to bring those trades back for a vote. That's not weakness — that's the membership doing its job."),
    Comment('P-L-07', 'local_keisha', 'deliberation hour 8',
            "Look — Brother Cole's point about the 2024 contract is the reason this proposal exists. We gave up COLA early last time and the membership felt it in real wages for the entire contract term. I'd rather have this conversation publicly now than internally during negotiations when the bargaining team is making real-time tradeoffs."),
    Comment('P-L-07', 'local_keisha', 'voting hour 12',
            "Voting yes."),
    Comment('P-L-07', 'local_dana', 'voting hour 16',
            "The pre-commitment matters for our long-term capacity to fight, not just for the 2027 contract. When the bargaining team gave up COLA in 2024, what they actually traded was the membership's confidence that hard demands would be brought back for vote. Restoring that confidence is part of what this proposal does. The City's pre-positioning is a real concern; the loss of membership trust in the bargaining process is also a real concern, and the second one compounds over multiple contract cycles. Voted yes."),
    Comment('P-L-07', 'local_tony', 'voting hour 18',
            "Voted yes; the pre-commitment is the same logic as the strike fund — credible positions before the negotiation, not during it."),
    Comment('P-L-07', 'local_walt', 'voting hour 22',
            "I want to add some context to Brother Cole's framing.\n\n"
            "In the '98 contract, the pension formula was the public pre-commitment. The City positioned around it from day one. We held. We won the formula. In '07, the pre-commitment was health insurance cost-sharing structure. The City positioned around it. We held. We won. In '13, the pre-commitment was the no-furlough language. Same pattern.\n\n"
            "In '17, COLA was internal — bargaining team prioritized health insurance instead, which was right at the time but cost us in real wages. In '24, COLA was internal again — same outcome.\n\n"
            "The pattern is consistent enough that it's not a coincidence. Pre-commitment on the priority demand changes the negotiation. I'm voting yes."),
    Comment('P-L-07', 'local_marisol', 'voting hour 30',
            "Pre-commitment binds the bargaining team to bring trades back. For Library workers especially, who've seen their positions traded in past contract rounds, that binding matters. Voted yes."),
    Comment('P-L-07', 'local_frank', 'voting hour 34',  # SRR destabilization
            "The City's going to see this public commitment and bake it in as their floor. We're tying our own hands.\n\n"
            "I voted yes on the 2024 contract and we got screwed — wage increases that didn't cover inflation, health insurance share increases on top. This proposal feels like the same trap from the opposite direction. We commit publicly, the City structures their offer around it, and we end up trading other things to hold the COLA floor that we wouldn't have had to trade if we'd kept the demand internal.\n\n"
            "Voting no until someone explains why this isn't the same pattern."),
    Comment('P-L-07', 'local_keisha', 'voting hour 40',
            "Frank, I want to engage with this seriously because it's the right concern and I owe a real answer.\n\n"
            "Your worry is that public pre-commitment gives the City our floor, which structures their opening offer against us. That's correct as a description of what's going to happen. The question is whether it changes the outcome.\n\n"
            "Three reasons I don't think it does. First, the City already knows COLA is a Local priority — we've raised it in every contract since 2018. Pre-commitment makes it formal, not visible. Second, when this demand was internal in 2024, the bargaining team traded it for other priorities under negotiation pressure. The pre-commitment removes that option. Third, public commitment binds us too — if the City offers something close to our floor, the membership has visibility into whether the bargaining team accepts or pushes harder.\n\n"
            "The 'tying our own hands' framing is the framing I'd worry about if our hands had been free in 2024. They weren't. The bargaining team's options were narrow, and the trades they made cost us real wages for three years.\n\n"
            "I'm voting yes. I take your concern seriously enough that I think the membership should weigh both arguments before voting; that's why this is a proposal and not an officer decision."),
    Comment('P-L-07', 'local_sam', 'voting hour 42',
            "Brother Boczek, your concern is the right concern to raise. I want to push back on the conclusion.\n\n"
            "You're worried the City sees this commitment and bakes it into their floor. They will. The question is whether that's worse than what happens without the commitment.\n\n"
            "Without the commitment: bargaining team has discretion to trade COLA for other priorities under negotiation pressure. We saw what that looked like in 2024. The City offered a wage package that didn't cover inflation, the team accepted to protect health insurance, and the membership ratified at 52% because the alternatives were worse.\n\n"
            "With the commitment: bargaining team can't make that trade without a membership vote. The City still structures their offer around the floor; they just can't move us off it without us seeing the trade.\n\n"
            "The fundamental issue isn't whether the City pre-positions against us. The fundamental issue is whether the bargaining team has cover to hold the line. The pre-commitment is that cover."),
    Comment('P-L-07', 'local_aisha', 'voting hour 48',
            "Brother Boczek's concern is the kind of concern I'd want a Vice President to engage with seriously. I think the pre-commitment is the right call, but I think the worry about ceding negotiating space to the City is reasonable enough that the bargaining team should be transparent during negotiations about what the COLA floor is constraining them from achieving. Voted yes. Building on what Sister Brooks said about cover for the bargaining team — that framing is the resolution for me."),
    Comment('P-L-07', 'local_frank', 'voting hour 50',  # changed-vote rationale (during extension 1)
            "Brother Cole and Sister Brooks both responded in good faith. The pre-commitment isn't free of the trap I was worried about — the City will absolutely position against the floor. But the alternative is what 2024 looked like, where the bargaining team's discretion let them trade COLA without member visibility. I'd rather the trap of 'the City knows our floor' than the trap of 'the membership doesn't know what's being traded.' Changed my vote."),
    Comment('P-L-07', 'local_keisha', 'voting hour 56',
            "The pre-commitment binds the bargaining team to bring back any deal that doesn't meet the COLA floor for a membership vote. It doesn't bind them to walk away; it binds them to consult. If the City offers a package that's below the floor on COLA but exceptional on everything else, the membership decides."),
    Comment('P-L-07', 'local_dana', 'voting hour 60',
            "The floor binds the team to bring any below-floor package back for vote, not to walk away from it. If the City offers below-floor COLA with strong health insurance and pension improvements, membership decides whether to accept."),

    # P-L-08
    Comment('P-L-08', 'local_sam', 'voting hour 6',
            "Voting yes."),
    Comment('P-L-08', 'local_dana', 'voting hour 4',
            "Voted yes; the documentary record is what makes the next round of grievances possible."),

    # P-L-09
    Comment('P-L-09', 'local_tony', 'voting hour 4',
            "Voted yes."),

    # P-L-10
    Comment('P-L-10', 'local_keisha', 'voting hour 6',
            "Karen Davila trained the 2019 cohort; her work was what made the 2020 grievance season as effective as it was."),
    Comment('P-L-10', 'local_sam', 'voting hour 8',
            "Voted yes; the 2020 grievance season is what Karen Davila's training looks like in practice."),
    Comment('P-L-10', 'local_dana', 'voting hour 6',
            "Karen Davila's training is also what made the Library steward position possible to fill effectively two years in."),
    Comment('P-L-10', 'local_tony', 'voting hour 10',
            "$3K for one day of Karen Davila's training is the best return on Local money I've seen in years. Voted yes."),
    Comment('P-L-10', 'local_walt', 'voting hour 4',
            "Karen trained the '09 cohort I came up with — best training event the Local's run in my time here. Voted yes."),
]


# -----------------------------------------------------------------------------
# Notification Feeds (at reset moment)
# -----------------------------------------------------------------------------

NOTIFICATION_FEEDS = [
    NotificationFeed(
        member_user_id='local_keisha',
        events=[
            NotificationEvent('srr_destabilization',
                              related_proposal_id='P-L-07',
                              note='Support on P-L-07 dipped below threshold during stable window; SRR destabilization alert to proposer.'),
            NotificationEvent('srr_extension_granted',
                              related_proposal_id='P-L-07',
                              note='SRR granted extension 1 (24 hours) on P-L-07.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-L-04',
                              note='Halfway-deadline reminder on VP Special Election for delegators who haven\'t yet voted.'),
        ],
    ),
    NotificationFeed(
        member_user_id='local_sam',
        events=[
            NotificationEvent('srr_destabilization',
                              related_proposal_id='P-L-07',
                              note='Support on P-L-07 dipped below threshold.'),
            NotificationEvent('srr_extension_granted',
                              related_proposal_id='P-L-07',
                              note='SRR granted extension 1.'),
            NotificationEvent('delegator_rationale',
                              related_proposal_id='P-L-07',
                              note='A delegator on Grievances posted a vote rationale on P-L-07 explaining their yes vote was driven by Sam\'s contract-citing argument.'),
        ],
    ),
    NotificationFeed(
        member_user_id='local_dana',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-L-04',
                              note='Halfway-deadline reminder on VP Special Election.'),
            NotificationEvent('new_follow',
                              note='A non-quick-login Library member delegating to Dana on Library Issues.'),
        ],
    ),
    NotificationFeed(
        member_user_id='local_tony',
        events=[
            NotificationEvent('srr_extension_granted',
                              related_proposal_id='P-L-07',
                              note='SRR granted extension 1 on P-L-07. (Tony cares for financial-planning reasons.)'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-L-06',
                              note='Halfway-deadline reminder on Trustee Election.'),
        ],
    ),
    NotificationFeed(
        member_user_id='local_aisha',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-L-04',
                              note="Halfway-deadline reminder on her own VP election."),
            NotificationEvent('delegator_rationale',
                              related_proposal_id='P-L-04',
                              note="A non-quick-login Parks member's vote rationale on P-L-04 referencing her bridge-building platform favorably."),
            NotificationEvent('srr_extension_granted',
                              related_proposal_id='P-L-07',
                              note='SRR granted extension 1 on P-L-07.'),
        ],
    ),
    NotificationFeed(
        member_user_id='local_walt',
        events=[
            NotificationEvent('srr_extension_granted',
                              related_proposal_id='P-L-07',
                              note='SRR granted extension 1 on P-L-07. (Walt cares about contract preparation; Low preset still passes this through.)'),
        ],
    ),
    NotificationFeed(
        member_user_id='local_janet',
        events=[],  # 0 unread; Janet is quiet rank-and-file in Local
    ),
]


# -----------------------------------------------------------------------------
# OrgBible assembly
# -----------------------------------------------------------------------------

LOCAL_4021_BIBLE = OrgBible(
    slug='demo-local-4021',
    display_name='AFSCME Local 4021',
    charter=CHARTER,
    tone_notes=TONE_NOTES,
    recent_history=RECENT_HISTORY,
    sub_orgs=['DPW', 'Parks', 'Library'],
    voting_methods_used=['binary', 'approval', 'rcv', 'stv'],
    approval_tie_resolution='broader_approval_base',
    rcv_tie_resolution='earliest_decisive_vote',
    quorum_threshold_default=0.35,
    members=MEMBERS,
    delegate_pages=DELEGATE_PAGES,
    proposals=PROPOSALS,
    drafts=DRAFTS,
    comments=COMMENTS,
    notification_feeds=NOTIFICATION_FEEDS,
)


# =============================================================================
# Integration notes for technical agent
# =============================================================================
"""
PHASE 23 INTEGRATION NOTES — LOCAL 4021 BIBLE:

1. User ID convention:
   - Local users prefixed with `local_` for clarity.
   - Janet Reilly is `local_janet`; her HOA identity is `hoa_janet`. Technical
     agent maps both to a single underlying user account for org-switching.
   - Dana Whitfield is `local_dana`; her Coalition identity is `coalition_dana`.
     Same single-user mapping.

2. SRR proposal — P-L-07:
   - This is the SRR extended-then-closed-early showcase.
   - state_at_reset shows the proposal in extension 1 hour 14 of 24.
   - Trajectory waypoints + events are in `trajectory_waypoints.py` under P_L_07.
   - The chart should clearly show: stable window opening at hour 14,
     destabilization at hour 38 (Frank's comment), extension grant, recovery
     line through extension 1, sliding-window stability check beginning at
     hour 60, reset moment at hour 86, expected close at hour 94.
   - Frank's hour-34 comment (the destabilizing event) and his hour-50
     changed-vote rationale are both in COMMENTS. The comment timestamps and
     trajectory waypoint timestamps align.

3. Frank Boczek's vote-change pattern:
   - P-L-05: voted no at hour 18, changed to yes at hour 35 after Walt's
     historical comment. Comments show both votes; technical agent should
     seed his vote record as the final yes with a change-history entry.
   - P-L-07: voted no during stable window, changed to yes at extension 1
     hour 12 (overall voting hour 50) after Keisha and Sam's responses.
     Same pattern: final yes with change-history entry.
   - This is intentional — Frank is the demo's example of a member who
     responds to substantive arguments in real time.

4. Sub-org-scoped proposals:
   - P-L-03 (Library Branch Hours Defense) is Library sub-org only — only
     Library members vote.
   - P-L-08 (DPW Safety Audit) is DPW sub-org only — only DPW members vote.
   - Other proposals are Local-wide.

5. Trustee Election (P-L-06, STV):
   - Five candidates running for three seats. Per the bible, candidates are
     mostly non-quick-login characters not deeply developed elsewhere. Technical
     agent should seed candidate user accounts (likely 'local_trustee_1' through
     'local_trustee_5' or similar generic IDs) with brief candidate statements
     if Sankey visualization requires them. The bible doesn't specify their
     identities in detail because the proposal is about showcasing STV mechanics,
     not narrative.

6. Janet Reilly in Local 4021:
   - Quiet rank-and-file Parks member. `private` delegate visibility on
     everything. 0 unread notifications at reset.
   - Voting record: centrist within the Local; voted yes on the 2024 contract
     ratification (one of the 52% who supported). Has voted on most major
     Local proposals but rarely commented.
   - The contrast with her HOA persona (High engagement, President role,
     multiple delegate pages) is part of cross-org intersection #2 from the
     narrative_arcs.md.
   - Technical agent should seed her Local voting record explicitly even
     though her Local content is otherwise minimal:
     - P-L-01: YES (Sanitation grievance authorization — broad support, easy yes)
     - P-L-02: YES (solidarity resolution — wide consensus)
     - P-L-03: N/A (Library sub-org only; Janet is Parks)
     - P-L-05: YES (strike fund increase — narrow, but Janet voted with the leadership)
     - P-L-07: YES (COLA pre-commitment — voted with Keisha/Sam framing)
     - P-L-08: N/A (DPW sub-org only)
     - P-L-09: YES (newsletter stipend)
     - P-L-10: YES (steward training)
     - P-L-04: pending (in voting; she'll vote but record TBD by reset; recommend
       seeding as Aisha first-choice — fits the Parks-bridge-building lean)

7. Dana's cross-org comment on P-C-06:
   - The Coalition file (activist_bible.py) contains Dana's cross-org reference
     comment on P-C-06 ("In the Local I steward in, we tried to formalize
     steward training without a budget line item..."). That comment references
     P-L-10 from this file. The two files together complete the cross-org
     intersection #3 documented in narrative_arcs.md.

8. Marisol Vega is non-quick-login but has a candidate statement in P-L-04
   and multiple substantive comments. Technical agent should seed her user
   account with the candidate role for the VP election.

9. Frank Boczek is non-quick-login but his comments on P-L-05 (skeptical-then-
   changed) and especially P-L-07 (the SRR destabilization) are narratively
   load-bearing. Technical agent should seed his user account with full vote
   history including the vote-change patterns noted above.

10. Trajectory data lives in `trajectory_waypoints.py`:
    - This file references proposals by ID; trajectory module has the corresponding
      waypoint and event data for chart rendering.
"""
