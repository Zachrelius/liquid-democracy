"""
Cedar Hollow HOA Bible — Demo Content for liquiddemocracy.us

This module contains the full content set for the Cedar Hollow HOA demo
organization. Consumed by the Phase 23 seed pipeline to populate the demo's
state at reset moment.

Companion modules:
- union_bible.py (AFSCME Local 4021)
- activist_bible.py (Westgate Tenants Coalition)
- trajectory_waypoints.py (per-proposal support-trajectory data, shared)

The dataclass shapes below are illustrative. The technical agent should
align field names and types to the actual OrgBible dataclass module
during integration. The content values are the source of truth.
"""

from .schema import (
    Member,
    TopicVisibility,
    PositionStatement,
    VoteRationale,
    DelegatePage,
    Comment,
    Proposal,
    NotificationEvent,
    NotificationFeed,
    OrgBible,
)


# =============================================================================
# Cedar Hollow HOA
# =============================================================================

CHARTER = """\
Cedar Hollow is a 1980s-era subdivision in Millbrook's Riverside neighborhood,
comprising 142 single-family homes and a 28-unit condo cluster (the "Cedar Court"
condos, added in a 1991 expansion). The HOA owns and maintains the community
pool, two small parks, the entrance signage and landscaping, and the shared
private road serving Cedar Court. It collects $480/year in dues from SFH
members and $720/year from condo members (the differential reflects the
condos' use of the private road and their proximity to the pool). The board
has five seats: a President, a Vice President, a Treasurer, a Secretary, and
a Member-at-Large. Elections are annual.\
"""

TONE_NOTES = """\
Earnest with deadpan undertones. People take Cedar Hollow seriously. Procedural
elaborateness about modest stakes is the dominant register. The HOA's stylesheet
is small-town civic — proposals have full preambles, comments cite prior board
minutes, the Secretary's notes are formal. The humor is in the gap between the
formality and what's being formalized. Characters never wink at the reader.\
"""

RECENT_HISTORY = """\
- SFH/Cedar Court dues differential tension simmering ongoing.
- Previous President resigned mid-term ~9 months ago (personal, not controversy).
- Janet Reilly elected to fill out the remaining term; running for full term.
- EV charger installation passed narrowly last year, allocation still contentious.
- Fall 2025 pool repair drained maintenance reserve; central to current budget conversation.\
"""


# -----------------------------------------------------------------------------
# Members
# -----------------------------------------------------------------------------

MEMBERS = [
    Member(user_id='hoa_janet', display_name='Janet Reilly',
           quick_login=True, is_cross_org=True, role='President',
           notification_preset='high', platform_role='admin'),
    Member(user_id='hoa_brenda', display_name='Brenda Okafor',
           quick_login=True, role='Secretary',
           notification_preset='high', platform_role='moderator'),
    Member(user_id='hoa_marcus', display_name='Marcus Pham',
           quick_login=True, is_cross_org=True, role='Member-at-Large',
           notification_preset='medium', platform_role='member'),
    Member(user_id='hoa_don', display_name='Don Iverson',
           quick_login=True, role='Member (former VP)',
           notification_preset='low', platform_role='member'),
    Member(user_id='hoa_linda', display_name='Linda Schaefer',
           quick_login=True, role='Treasurer',
           notification_preset='medium', platform_role='moderator'),
    Member(user_id='hoa_tomas', display_name='Tomás Ortega',
           quick_login=True, role='Member',
           notification_preset='low', platform_role='member'),
    # Non-quick-login named members:
    Member(user_id='hoa_patty', display_name='Patricia "Patty" Voss',
           quick_login=False, role='Member (President candidate)'),
    Member(user_id='hoa_ravi', display_name='Ravi Chandrasekaran',
           quick_login=False, role='Member'),
]


# -----------------------------------------------------------------------------
# Delegate Pages
# -----------------------------------------------------------------------------

DELEGATE_PAGES = [
    DelegatePage(
        member_user_id='hoa_janet',
        page_visibility='public',
        intro=(
            "Cedar Hollow resident for 16 years, current President (filling out "
            "unexpired term, running for full one). Day job is groundskeeper at "
            "the City Parks Department.\n\n"
            "If you delegate to me on Budget, you'll see fiscal moderation aimed "
            "at the deferred maintenance backlog. On Pool & Recreation I'm "
            "transparent but not accepting new delegations — workload as "
            "President is high enough that I'd rather you vote your own "
            "conscience there."
        ),
        topics=[
            TopicVisibility('Budget', 'public_accepting'),
            TopicVisibility('Pool & Recreation', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Budget',
                text=(
                    "Reserve is thin after the fall pool repair. Priority for the "
                    "next 18 months is rebuilding it through existing dues and "
                    "the small fee adjustments we passed, not through special "
                    "assessments or deferred maintenance. I'll vote against new "
                    "spending that doesn't address backlog and for modest fee "
                    "changes that build the reserve back."
                ),
            ),
            PositionStatement(
                topic='Pool & Recreation',
                text=(
                    "Transparent but not accepting new delegations. Pool access "
                    "and reasonable operating hours matter; preserving the reserve "
                    "matters more right now. Expect me to vote with the maintenance "
                    "discipline rather than the amenity-expansion side when those "
                    "conflict."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Proposing, voting yes. Modest, overdue, and the alternative is letting the reserve drift further."),
            VoteRationale('P-H-02', 'yes',
                          "Voting yes knowing it'll fail. The slow rebuild is the answer the membership is going to choose; I want my support on record for the faster path."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Approved the deferred-maintenance items that align with reserve health and life-safety. Items 7 and 8 are amenity expansions that don't belong in this cycle."),
            VoteRationale('P-H-04', 'approval_B_C_D',
                          "Voted for the modest evening extension (C), kept the conservative option (B) on the table, and supported the weekend-only extension (D). Approval cap on E because the morning extension doesn't have demonstrated demand."),
            VoteRationale('P-H-06', 'yes',
                          "A study is informational, not a bylaw amendment — Marcus is correct on the procedural point. Voted yes; the dues differential question is worth examining even if the bylaws are the bylaws."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_brenda',
        page_visibility='public',
        intro=(
            "Secretary, third term. Twenty-two years in Cedar Hollow, mostly "
            "behind the scenes. Career was in legal administration, which mostly "
            "translates here to noticing when we're about to amend something we "
            "didn't mean to amend.\n\n"
            "If you delegate to me on Bylaws & Procedure: I read the governing "
            "documents so you don't have to, and I vote to preserve procedural "
            "integrity even when it's inconvenient."
        ),
        topics=[
            TopicVisibility('Bylaws & Procedure', 'public_accepting'),
            # Phase 23.2 C1 — 'Elections' added so election proposals
            # (P-H-07) have a valid topic vocabulary entry. Private
            # visibility per dispatch guidance for election topics.
            TopicVisibility('Elections', 'private'),
        ],
        position_statements=[
            PositionStatement(
                topic='Bylaws & Procedure',
                text=(
                    "Two principles. First: the bylaws are how a small organization "
                    "stays a single organization across changes in membership and "
                    "board composition. Strict interpretation matters more in a "
                    "170-household HOA than in a corporation with a general "
                    "counsel. Second: amend rarely, and only after the operational "
                    "case is clear. I'll vote against bylaw changes that solve "
                    "problems we haven't actually had.\n\n"
                    "If a delegator on this topic finds my voting record drifting "
                    "toward looser interpretation, pull the delegation — that "
                    "would be drift, not refinement."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes', "Voting yes. Modest, the math is right, and Linda's reserve framing is correct."),
            VoteRationale('P-H-02', 'no', "Voting no with regret. Janet and Linda's case is right on the substance; I just don't think the membership is going to accept a $300 assessment this year and forcing the issue costs more than waiting."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6', "Voted with Linda's framing — life-safety items first, deferred-maintenance backlog second, amenity expansion later."),
            VoteRationale('P-H-04', 'approval_B_C', "Voted for the modest evening extension and the conservative option. Approval cap on D and E pending demand data."),
            VoteRationale('P-H-05', 'yes', "Proposing, voting yes. (Expecting low participation; that's a separate problem.)"),
            VoteRationale('P-H-06', 'yes', "Procedurally clean — a study is informational, not a bylaw amendment."),
            VoteRationale('P-H-09', 'yes', "Proposing, voting yes."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_marcus',
        page_visibility='public',
        intro=(
            "Member-at-Large, first term. Cedar Court resident — moved in four "
            "years ago. Day job: planner at a regional planning agency (not the "
            "City of Millbrook). Most of what I work on professionally is "
            "unrelated to HOA matters, but the long-horizon habit transfers.\n\n"
            "`public_accepting` on Cedar Court Issues. Transparent only on "
            "Long-Term Planning — the board workload is enough that I'd rather "
            "you vote your own conscience there."
        ),
        topics=[
            TopicVisibility('Cedar Court Issues', 'public_accepting'),
            TopicVisibility('Long-Term Planning', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Cedar Court Issues',
                text=(
                    "Cedar Court joined Cedar Hollow in 1991. Some of the "
                    "structural questions from that period still aren't fully "
                    "resolved — the dues differential being the most discussed.\n\n"
                    "My approach: advocate for Cedar Court positions without "
                    "framing every disagreement as Cedar Court vs. SFH. Most "
                    "issues that look factional aren't. Issues that are genuinely "
                    "structural deserve to be raised explicitly; the rest should "
                    "be resolved on their merits.\n\n"
                    "If you delegate here, expect me to support Cedar Court "
                    "interests on questions where they're materially affected and "
                    "to vote with the broader membership otherwise."
                ),
            ),
            PositionStatement(
                topic='Long-Term Planning',
                text=(
                    "Planning background: I think in 10-20 year horizons. Care "
                    "about decisions that compound over time — deferred "
                    "maintenance discipline, reserve health, infrastructure "
                    "sequencing. Less interested in single-year operational "
                    "decisions.\n\n"
                    "Transparent only because the board workload is high enough "
                    "that I'd rather not hold delegations on a topic where my "
                    "votes can drift toward 'interesting to think about' rather "
                    "than 'necessary to decide.'"
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes', "Yes. Modest fee adjustment, overdue."),
            VoteRationale('P-H-02', 'no', "The slow rebuild has merit even though Janet and Linda's case for faster is well-made. $300 hits Cedar Court households harder relative to unit value than SFH households, and I want to be careful about supporting assessments that compound the dues-differential question."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6', "Items 1-3 are life-safety. Item 4 is the Cedar Court fence — overdue, regardless of unit type. Items 5-6 are sensible. 7-8 aren't this cycle."),
            VoteRationale('P-H-04', 'approval_C_D', "Evening extension and weekend-only — those map to actual demonstrated demand."),
            VoteRationale('P-H-06', 'yes', "Tomás is right that the dues differential is worth examining. Brenda is right that a study isn't a bylaw amendment. Don is right that the bylaws are the bylaws. All three things can be true; this proposal works inside the procedural envelope."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_don',
        page_visibility='public',
        intro=(
            "Thirty-one years in Cedar Hollow. Former Vice President, 2017-2019. "
            "No current board position. I vote, I comment, I push back on board "
            "decisions I think are wrong.\n\n"
            "Transparent only on Budget — my voting record is public so anyone "
            "curious can see it. I don't accept new delegations. If you find "
            "yourself wanting to delegate to me, my honest preference is that "
            "you read what I write, decide whether you agree, and vote your own "
            "conscience. That's worth more to this HOA than another vote in my "
            "column."
        ),
        topics=[
            TopicVisibility('Budget', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Budget',
                text=(
                    "The fundamental issue with the HOA's budget is not the pool "
                    "repair, not the deferred-maintenance backlog, not even the "
                    "reserve thinness. It's the pattern of treating reserve "
                    "discipline as something the board attends to between "
                    "special assessments, rather than as the budget's central "
                    "organizing principle.\n\n"
                    "I've been here long enough to remember when the reserve was "
                    "managed properly. We have not managed it properly since "
                    "approximately 2016. The current board is no worse than the "
                    "previous three, but no better either. Voting against new "
                    "spending that doesn't address backlog. Voting against "
                    "special assessments that paper over the underlying "
                    "discipline problem.\n\n"
                    "I'm transparent and not accepting because I don't want to "
                    "be responsible for other people's votes. I'd rather you "
                    "read my reasoning, disagree with it if you do, and vote your "
                    "own way. That's how this place works at its best."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'no', "Voting no. The fee adjustment is fine in isolation but the framing is wrong — small adjustments aren't a substitute for reserve discipline, and treating them as part of a 'rebuild plan' papers over the underlying issue."),
            VoteRationale('P-H-02', 'yes', "Voting yes. Linda's case is correct: deferred reserve-building compounds. Janet's right that the slow rebuild is what the membership will choose; I'm voting with the proposal anyway because the slow rebuild leaves us exposed."),
            VoteRationale('P-H-03', 'approval_1_2_3', "Life-safety items only. Items 4-8 are deferred-maintenance the board should be sequencing in the operating budget, not approving via special vote."),
            VoteRationale('P-H-04', 'approval_B', "Conservative hours. The HOA owns the pool; expanding access expands maintenance demand. Reserve doesn't support that right now."),
            VoteRationale('P-H-06', 'no', "The dues structure is in the bylaws. A 'study' that produces 'recommendations' is a slow-motion amendment process. Voting no."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_linda',
        page_visibility='public',
        intro=(
            "Treasurer, second term. Day job is CFO at a manufacturing firm in "
            "Millbrook; same skill set, smaller scale.\n\n"
            "If you delegate to me on Budget, expect votes anchored to reserve "
            "health and the deferred maintenance backlog. I won't support "
            "spending that doesn't carry a credible source of funds. Won't "
            "oppose spending that does."
        ),
        topics=[
            TopicVisibility('Budget', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Budget',
                text=(
                    "Current reserve: ~$28K. Target reserve for an HOA our size: "
                    "~$45K. Deferred maintenance backlog with credible cost "
                    "estimates: $62K across items 1-6 of P-H-03. Annual dues "
                    "income net of routine operating costs: ~$11K available for "
                    "reserve or backlog.\n\n"
                    "The math doesn't permit both full backlog completion and "
                    "reserve rebuild on this timeline without a special "
                    "assessment or fee adjustments. I'll vote for measured fee "
                    "adjustments and against amenity expansion until the gap "
                    "closes."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes', "Math is right. Voting yes."),
            VoteRationale('P-H-02', 'yes', "Proposer; voting yes."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6', "Items 1-6 fit; 7-8 don't this cycle."),
            VoteRationale('P-H-04', 'approval_B_C', "Conservative options. Expansion requires demonstrated maintenance impact."),
            VoteRationale('P-H-06', 'no', "Don's procedural argument is the right call. Studies on bylaw-defined questions are how amendments get back-doored."),
        ],
    ),

    # Tomás has page_visibility='private' — no delegate page rendered.
    # Voting record is private; he hasn't engaged with delegation system.
]


# -----------------------------------------------------------------------------
# Proposals
# -----------------------------------------------------------------------------

PROPOSALS = [
    Proposal(
        proposal_id='P-H-01',
        title='Pool Fee Structure 2026',
        proposer_user_id='hoa_janet',
        voting_method='binary',
        state_at_reset='passed, 14 days ago (58-42)',
        body=(
            "The board has reviewed the current non-resident guest fee structure "
            "and is proposing an increase from $5 to $7 per guest visit.\n\n"
            "Three reasons. First, the $5 fee was set in 2018 and hasn't been "
            "adjusted since; the new figure is closer to comparable HOA pool fees "
            "across Millbrook. Second, after the fall pool repair, the maintenance "
            "reserve is below where we need it for normal turnover; modest fee "
            "increases help rebuild without a special assessment. Third, "
            "non-resident guest use has grown — fee adjustment also smooths "
            "peak demand.\n\n"
            "To be clear: this is a modest change, not a fix for the reserve. "
            "We'll need other measures as well. I want member input on which."
        ),
        topics=['Budget', 'Pool & Recreation'],
    ),

    Proposal(
        proposal_id='P-H-02',
        title='Special Assessment to Rebuild Pool Reserve',
        proposer_user_id='hoa_linda',
        voting_method='binary',
        state_at_reset='failed, 7 days ago (38-62)',
        body=(
            "Proposing a $300/household one-time special assessment to restore "
            "the maintenance reserve.\n\n"
            "The numbers:\n"
            "- Current reserve: $28K. Pre-repair level: $45K. Gap: $17K.\n"
            "- 170 households × $300 = $51K gross; net after collection costs "
            "~$48K.\n"
            "- Closes the gap and provides a margin for the next unexpected "
            "expense.\n\n"
            "Without this assessment, the alternative path is rebuilding the "
            "reserve via existing dues plus the modest fee adjustments. That "
            "path is roughly $11K/year toward the gap, meaning ~18 months to "
            "close it assuming no further unexpected expenses. The probability "
            "of zero unexpected expenses in any 18-month window on infrastructure "
            "this age is low.\n\n"
            "I'd rather pay $300 once than absorb a larger emergency assessment "
            "in 14 months. The membership may reasonably disagree about that "
            "tradeoff."
        ),
        topics=['Budget', 'Pool & Recreation'],
    ),

    Proposal(
        proposal_id='P-H-03',
        title='Deferred Maintenance Priority List 2026',
        proposer_user_id='hoa_linda',
        voting_method='approval',
        state_at_reset='passed, 21 days ago (top 4 items approved)',
        body=(
            "Eight items on the deferred maintenance backlog with documented "
            "cost estimates:\n\n"
            "1. Pool pump replacement ($14K) — life-safety, item nearing end of "
            "service life\n"
            "2. Entrance signage repair ($3K) — visibility / safety\n"
            "3. Parking lot resurfacing ($28K) — accumulated damage from fall "
            "pool repair access\n"
            "4. Cedar Court fence replacement ($8K) — three years overdue, "
            "structural\n"
            "5. Playground equipment refresh ($6K) — safety\n"
            "6. Trail maintenance, north path ($3K) — drainage\n"
            "7. Tennis court resurfacing ($12K) — cosmetic, use is low\n"
            "8. Clubhouse landscaping upgrade ($4K) — aesthetic\n\n"
            "Approval vote: members select which items to fund this cycle. Items "
            "1-6 fit within the operating budget plus modest carryover. Items "
            "7-8 would require additional revenue."
        ),
        options=[
            'Pool pump replacement ($14K) — life-safety',
            'Entrance signage repair ($3K) — visibility/safety',
            'Parking lot resurfacing ($28K) — accumulated damage',
            'Cedar Court fence replacement ($8K) — structural, 3yr overdue',
            'Playground equipment refresh ($6K) — safety',
            'Trail maintenance, north path ($3K) — drainage',
            'Tennis court resurfacing ($12K) — cosmetic',
            'Clubhouse landscaping upgrade ($4K) — aesthetic',
        ],
        topics=['Budget', 'Long-Term Planning', 'Cedar Court Issues'],
    ),

    Proposal(
        proposal_id='P-H-04',
        title='Pool Operating Hours Proposal',
        proposer_user_id='hoa_tomas',
        voting_method='approval',
        state_at_reset='passed, 4 days ago',
        body=(
            "Proposing five options for the pool's evening operating hours. "
            "Approval vote — pick any subset you'd support.\n\n"
            "Current hours: 7 AM-7 PM Memorial Day through Labor Day. The "
            "options:\n\n"
            "- **A.** Keep current hours (7 AM-7 PM).\n"
            "- **B.** Modest weekday evening extension to 8 PM.\n"
            "- **C.** Modest weekday evening extension to 8:30 PM (the option "
            "I'd vote for).\n"
            "- **D.** Weekend-only extension to 8:30 PM, weekdays unchanged.\n"
            "- **E.** Morning extension to 6 AM weekdays.\n\n"
            "Background: y'all may have noticed the pool gets crowded between "
            "5:30-7 PM on weekdays — that's when people get home from work and "
            "want time before sundown. The early-morning option (E) is something "
            "I floated because a couple of residents asked about lap swimming "
            "before work, but I don't have a strong demand signal on it.\n\n"
            "If multiple options pass, we go with whichever combination got the "
            "broadest approval base."
        ),
        options=[
            'A: Keep current hours (7am-7pm)',
            'B: Extend weekdays to 8pm',
            'C: Extend weekdays to 8:30pm',
            'D: Weekends only to 8:30pm',
            'E: Add 6am weekday morning hour',
        ],
        topics=['Pool & Recreation'],
    ),

    Proposal(
        proposal_id='P-H-05',
        title='Cedar Hollow Newsletter Frequency Change',
        proposer_user_id='hoa_brenda',
        voting_method='binary',
        state_at_reset='failed quorum, 30 days ago',
        body=(
            "Current newsletter is monthly. Proposing bimonthly going forward.\n\n"
            "Three reasons. Production effort: the newsletter eats roughly 8 "
            "hours of volunteer time per month, and our editor (Ravi) has been "
            "stretched thin since taking on the schedule alone in 2024. Content "
            "thinness: most months we're publishing 600-word issues because "
            "there isn't more to report; bimonthly would give us 1200-word issues "
            "with actual substance. Cost: printing and distribution drop by "
            "half.\n\n"
            "I want to be clear this is mostly a quality-of-life adjustment for "
            "the volunteer editor, not a financial decision. If the membership "
            "wants monthly newsletters enough to support them, we'll keep doing "
            "them — but I'd ask people to consider whether they actually read "
            "the monthly issues all the way through."
        ),
        topics=['Bylaws & Procedure'],
    ),

    Proposal(
        proposal_id='P-H-06',
        title='Cedar Court Dues Differential Study',
        proposer_user_id='hoa_tomas',
        voting_method='binary',
        state_at_reset='passed, 2 days ago (54-46) [SRR clean-close]',
        body=(
            "Proposing a study of whether the SFH-vs-condo dues differential "
            "reflects actual cost allocations.\n\n"
            "Background: SFH households pay $480/year; condo households pay "
            "$720/year. The $240 differential was set in the 1991 amendment "
            "when Cedar Court joined, intended to cover the condos' use of the "
            "private road and proximity to pool maintenance.\n\n"
            "Genuine question I want answered: does $240/year still reflect the "
            "actual cost differential? Property values have shifted, road "
            "maintenance costs have changed, pool maintenance has changed. "
            "We've never re-examined the number.\n\n"
            "The study would be informational only. Findings get reported to "
            "the membership. Any recommendation that involves changing the "
            "dues structure itself would still need to go through the Article 7 "
            "bylaw amendment procedure.\n\n"
            "Just to make sure I understand — this isn't a backdoor to "
            "amendment. It's information that lets the membership decide "
            "whether to raise an amendment proposal at all."
        ),
        topics=['Cedar Court Issues', 'Bylaws & Procedure', 'Budget'],
    ),

    Proposal(
        proposal_id='P-H-07',
        title='Annual President Election 2026',
        proposer_user_id='hoa_brenda',  # election proposals are typically posted by Secretary
        voting_method='rcv',
        state_at_reset='deliberation, hour 36 of 168 (voting opens 132 hours after reset)',
        body=(
            "Annual President election. Three candidates running. RCV: rank as "
            "many candidates as you have preferences for; leave others unranked.\n\n"
            "Voting opens 132 hours after this proposal closes deliberation. "
            "Candidate statements posted by candidates; member Q&A welcome "
            "through voting close."
        ),
        candidate_statements={
            'hoa_janet': (
                "I've been President for nine months, filling out the previous "
                "term. Running for a full term.\n\n"
                "What I've done since taking the role: kept the board functional "
                "through the pool repair, brought the Pool Fee structure up for "
                "a vote that actually passed (narrowly), and gotten the deferred-"
                "maintenance priority list moving for the first time in three "
                "years. Things I haven't done well: the Cedar Court/SFH tensions "
                "are still simmering, and I should have communicated better "
                "during the fall pool repair.\n\n"
                "What I'd prioritize in a full term: finishing the reserve "
                "rebuild without a second special assessment, completing the "
                "deferred maintenance items 1-6 we approved, and getting the "
                "dues differential study through to a real recommendation. I "
                "think the HOA functions best when the board does the operational "
                "work competently and the membership decides the contested "
                "questions — not the other way around.\n\n"
                "To be clear: I'm not going to be a transformational President. "
                "I want to be a competent one."
            ),
            'hoa_don': (
                "I served as Vice President from 2017 to 2019. I'm running because "
                "Mrs. Reilly's tenure, while competent in the operational sense, "
                "hasn't engaged with the deeper budget question that produced the "
                "reserve crisis in the first place. The pool repair revealed a "
                "problem that had been building for at least eight years.\n\n"
                "What I'd do: stop treating reserve discipline as something the "
                "board addresses between crises. Build reserve management into "
                "the operating budget as the central organizing principle, not "
                "the residual after amenity spending. Stop authorizing special "
                "spending votes that should be operational decisions.\n\n"
                "What I'd accept differs from Mrs. Reilly only in degree, not "
                "direction. The slow reserve rebuild she's pursuing is correct "
                "as far as it goes; my disagreement is that 'as far as it goes' "
                "doesn't go far enough.\n\n"
                "I'm running with no expectation of winning. I'd rather lose "
                "with the budget question raised properly than win by softening "
                "it. If Mrs. Voss's candidacy serves to keep the question on the "
                "table even if neither of us wins, that's a productive outcome.\n\n"
                "I'll note: if elected, my first act would be establishing a "
                "standing budget committee with rotating membership independent "
                "of the board. The reserve management problem is structural, "
                "not personal — putting it on one President to fix is exactly "
                "the pattern that produced the current situation."
            ),
            'hoa_patty': (
                "Forty-one years in Cedar Hollow. Two adult children raised here. "
                "Three pool replacements, four roof generations on the clubhouse, "
                "six Presidents.\n\n"
                "Running because the budget questions Don has been raising are "
                "real, and because I think they need to be raised by more than "
                "one voice on the ballot. I largely agree with Don's analysis. "
                "I'd add: the reserve discipline question isn't separable from "
                "the question of what this HOA is for. We've drifted from being "
                "a small-scale governance structure for shared infrastructure "
                "into being a quasi-amenity-management organization. I think "
                "the drift produced the reserve problem.\n\n"
                "What I'd do: bring spending discipline back to the operating "
                "budget. Stop authorizing amenity-driven special spending votes. "
                "Establish a budget committee structure of the kind Don's "
                "proposed.\n\n"
                "Speaking as someone who's seen this neighborhood through three "
                "pool replacements: the patterns repeat. We over-extend on "
                "amenities during good years and under-rebuild reserves between "
                "crises. The current cycle is the third one I've watched, and "
                "the previous two ended with assessments much larger than the "
                "$300 we just declined.\n\n"
                "I don't expect to win against Mrs. Reilly. I think she's been "
                "competent in the operational role. I think the budget question "
                "needs to be on the ballot, not just on the floor."
            ),
        },
        topics=['Elections', 'Bylaws & Procedure'],
    ),

    Proposal(
        proposal_id='P-H-08',
        title='Landscaping Vendor Selection',
        proposer_user_id='hoa_janet',
        voting_method='approval',
        state_at_reset='voting, hour 18 of 72',
        body=(
            "The board's three-year contract with Vendor B (current landscaper) "
            "expires at end of season. Soliciting member input on renewal vs. "
            "switching.\n\n"
            "Four options:\n\n"
            "- **Vendor A:** $9K/year, new entrant to Millbrook market, no local "
            "references.\n"
            "- **Vendor B:** $14K/year, current vendor, three-year track record "
            "at Cedar Hollow, all references positive.\n"
            "- **Vendor C:** $11K/year, established Millbrook vendor, no Cedar "
            "Hollow history but referenced by two nearby HOAs.\n"
            "- **Vendor D:** $7K/year, owner-operator, smaller crew, references "
            "mixed.\n\n"
            "Routine procurement decision. Approve any subset of vendors you'd "
            "accept; the board will select the highest-approved option that "
            "meets contract requirements."
        ),
        options=[
            'Vendor A - $9K/yr, new entrant, no local refs',
            'Vendor B - $14K/yr, current vendor, 3yr track record',
            'Vendor C - $11K/yr, established Millbrook, no Cedar Hollow history',
            'Vendor D - $7K/yr, owner-operator, mixed references',
        ],
        topics=['Budget'],
    ),

    Proposal(
        proposal_id='P-H-09',
        title='Pool Float Storage Bylaw Amendment',
        proposer_user_id='hoa_brenda',
        voting_method='binary',
        state_at_reset='passed, 35 days ago (89-11)',
        body=(
            "Proposing a bylaw amendment to formally govern storage of personal "
            "pool floats in the pool deck box.\n\n"
            "Background: the pool deck box is owned by the HOA but has been used "
            "as community float storage for at least the last decade through "
            "informal practice. We've had three incidents in the past 18 months "
            "where personal floats were damaged, mistaken for community property, "
            "or thrown out during routine cleanup. Each incident produced a "
            "small but real procedural question with no governing language to "
            "resolve it.\n\n"
            "The amendment establishes: floats stored in the deck box are "
            "subject to community-property handling unless tagged with a current "
            "resident name and unit number; tagged floats remain personal "
            "property; untagged floats over 30 days old may be disposed of after "
            "one written notice to the resident list. Standard bylaw language "
            "for similar shared-storage situations.\n\n"
            "(I'm aware this is a substantial preamble for a question about pool "
            "floats. The bylaws don't currently address shared-storage protocols "
            "at all, and getting it on the books now means we don't have to "
            "litigate it again next summer.)"
        ),
        topics=['Bylaws & Procedure', 'Pool & Recreation'],
    ),
]


# -----------------------------------------------------------------------------
# Drafts (proposals in draft state at reset)
# -----------------------------------------------------------------------------

DRAFTS = [
    Proposal(
        proposal_id='P-H-NEW-D1',
        title='Bylaw Cleanup (Draft)',
        proposer_user_id='hoa_brenda',
        voting_method='binary',
        state_at_reset='draft (not yet posted for deliberation)',
        body=(
            "Draft proposal cleaning up several procedural cross-references in "
            "the bylaws that were created during the 2019 amendments and never "
            "reconciled. Specifically: three sections reference 'Section 4.2(b)' "
            "which doesn't exist (the actual provision is at Section 4.3(b)), "
            "one section references a quorum threshold that was changed in 2021 "
            "but the cross-reference wasn't updated, and one section contains "
            "a sentence that was meant to be struck during the 2019 amendments "
            "but wasn't.\n\n"
            "Non-substantive cleanup. Will post after the President election "
            "concludes — don't want it competing with that for member attention."
        ),
        topics=['Bylaws & Procedure'],
    ),
]


# -----------------------------------------------------------------------------
# Comments
# -----------------------------------------------------------------------------

COMMENTS = [
    # P-H-01
    Comment('P-H-01', 'hoa_marcus', 'voting hour 6',
            "Yes from me. Reserve health matters and the fee adjustment is small."),
    Comment('P-H-01', 'hoa_tomas', 'voting hour 10',
            "Voting yes; the math tracks."),
    Comment('P-H-01', 'hoa_brenda', 'voting hour 12',
            "Per the November 2024 minutes (item 4), the last fee adjustment of any kind was 2018. The $5 figure has been in place six years."),
    Comment('P-H-01', 'hoa_janet', 'voting hour 18',
            "Don's right that the reserve drift goes back further than this fee structure. The fee increase isn't a fix; it's one part of a slower rebuild. I don't disagree with him on the diagnosis — I disagree that we should wait on small adjustments while we figure out the bigger one."),
    Comment('P-H-01', 'hoa_don', 'voting hour 24',
            "I've been here long enough to remember when the pool reserve was managed properly. The fundamental issue is not the $5 vs. $7 fee. The fundamental issue is that the reserve has been treated as a residual rather than a primary obligation for at least eight years now.\n\n"
            "Voting no on this fee adjustment is not a vote against the fee. It's a vote against accepting that small adjustments are an adequate response to the underlying problem.\n\n"
            "Mr. Pham and Mrs. Reilly are both correct that the adjustment is small and overdue. I'd ask them whether they think small and overdue adjustments add up to a rebuilt reserve. I don't."),
    Comment('P-H-01', 'hoa_patty', 'voting hour 30',
            "Voting no. Speaking as someone who's been through this cycle before, modest adjustments after the fact aren't the answer."),

    # P-H-02
    Comment('P-H-02', 'hoa_janet', 'voting hour 4',
            "Voting yes on my own proposal isn't surprising. I want to flag for the record that I expect this to fail."),
    Comment('P-H-02', 'hoa_patty', 'voting hour 12',
            "Voted yes. Mrs. Schaefer's math is right."),
    Comment('P-H-02', 'hoa_don', 'voting hour 18',
            "Voting yes. Mrs. Schaefer is correct; the slow rebuild leaves us exposed."),
    Comment('P-H-02', 'hoa_linda', 'voting hour 20',
            "Reserve at $28K, target $45K, gap $17K. The $300 assessment closes the gap and gives $4K margin. The slow rebuild path covers the gap in ~18 months assuming no further unexpected expenses."),
    Comment('P-H-02', 'hoa_brenda', 'voting hour 30',
            "I appreciate Don's point about board planning patterns; that's a real conversation worth having. It's separate from whether we pass this specific assessment, which is the question on the ballot."),

    # P-H-03
    Comment('P-H-03', 'hoa_linda', 'voting hour 4',
            "- Items 1-3: life-safety. Approve.\n- Item 4: structural, overdue. Approve.\n- Items 5-6: safety and drainage. Approve.\n- Items 7-8: cosmetic/aesthetic. Defer."),
    Comment('P-H-03', 'hoa_janet', 'voting hour 6',
            "Items 1-3 are life-safety, item 4 is the Cedar Court fence which is overdue, items 5-6 are the right call for this cycle."),
    Comment('P-H-03', 'hoa_marcus', 'voting hour 8',
            "Item 4 — Cedar Court fence — has been on the deferred list for three years. Approving it this cycle is overdue regardless of where you live in the neighborhood."),

    # P-H-04
    Comment('P-H-04', 'hoa_tomas', 'voting hour 16',
            "Just to make sure I understand — if B, C, and D all pass, we'd go with whichever option got the broadest approval base, right? That's the tie-break rule? Want to make sure I'm reading the bylaws right on this one."),
    Comment('P-H-04', 'hoa_brenda', 'voting hour 14',
            "Tomás, the evening extension proposal is well-drafted — the option structure made the approval vote work cleanly."),
    Comment('P-H-04', 'hoa_linda', 'voting hour 22',
            "Expanded hours mean more maintenance hours; current budget doesn't support it."),
    Comment('P-H-04', 'hoa_tomas', 'voting hour 40',
            "Thanks Brenda, that's exactly what I needed."),

    # P-H-06 (SRR clean-close)
    Comment('P-H-06', 'hoa_don', 'voting hour 2',
            "The dues structure was set in the 1991 bylaw amendment establishing Cedar Court's membership terms. It has been the dues structure for thirty-three years. A 'study' is the procedural mechanism by which boards put bylaw questions on the table without invoking the bylaw amendment procedure. I have seen this pattern in 2009 (parking allocation), in 2014 (pool access), and in 2019 (landscaping responsibility). Each time, the study became the predicate for an amendment vote that should have been raised directly.\n\n"
            "Voting no. Not against the substantive question — that question can be raised through Article 7 anytime the membership wants to raise it. Voting no against the procedural shortcut."),
    Comment('P-H-06', 'hoa_marcus', 'voting hour 4',
            "Don, I want to engage with your procedural objection because it's worth taking seriously. You're right that the dues structure is in the bylaws and can't be relitigated annually. What I'd push back on is the equivalence between a study and an amendment. A study collects information; an amendment changes governing language. The board has standing to authorize the first without invoking the procedure for the second. Brenda's comment lays out the distinction more precisely than I can.\n\n"
            "I also want to be clear that the study isn't a backdoor to a bylaw change. If the study concludes the differential should be adjusted, that conclusion would still need to go through the Article 7 amendment procedure. The membership decides; the study informs."),
    Comment('P-H-06', 'hoa_janet', 'voting hour 8',
            "Don, the study doesn't amend the bylaws. Brenda's comment lays out the procedural distinction. The board can authorize informational work without revisiting the dues structure itself."),
    Comment('P-H-06', 'hoa_brenda', 'voting hour 10',
            "Just to clarify the procedural distinction since it's come up: a study authorized by board action is informational. A change to the dues structure would be a bylaw amendment requiring the procedure in Article 7. The current proposal is the former, not the latter. Both Don and Marcus are correct about different things — Don that the dues structure can't be litigated annually without a bylaw amendment, Marcus that a study doesn't constitute one."),
    Comment('P-H-06', 'hoa_tomas', 'voting hour 10',
            "Mr. Iverson, I hear the procedural concern and I want to make sure my proposal isn't actually doing what you're worried about. The study produces a report. The board doesn't act on the report unless the membership votes to. If the membership doesn't vote to, the report sits in the archives. That's not a back door — that's just information. But I'd genuinely want to know if there's a procedural specific I'm missing."),
    Comment('P-H-06', 'hoa_janet', 'voting hour 24',
            "Voting yes. The differential reflects real cost allocation, and I expect the study to confirm most of it. I'd rather have the numbers than the perception."),
    Comment('P-H-06', 'hoa_ravi', 'voting hour 36',
            "Voting yes. I'm SFH but I delegate to Marcus on Cedar Court Issues because his judgment on those questions is better than mine — that's the whole point of delegating on topics where I don't have the background. A study seems like a reasonable next step."),

    # P-H-07 (election deliberation)
    Comment('P-H-07', 'hoa_brenda', 'deliberation hour 6',
            "Voting opens in 132 hours. Candidate statements should be posted by then; member Q&A welcome through voting close. RCV mechanics: rank as many candidates as you have preferences for, leave others unranked."),
    Comment('P-H-07', 'hoa_don', 'deliberation hour 12',
            "Mrs. Okafor, the procedural reminder is appreciated. I'd add that the candidate statements posted to date — including mine — have not yet engaged seriously with the reserve management question that I take to be the central issue. I'll address it in my own statement."),
    Comment('P-H-07', 'hoa_janet', 'deliberation hour 24',
            "What I'd do differently: schedule a Cedar Court resident meeting at least quarterly and publish the agenda in advance. We've been ad-hoc and it shows."),
    Comment('P-H-07', 'hoa_marcus', 'deliberation hour 40',
            "Question to all three candidates: how would you handle the dues differential study (P-H-06) as President if it concludes the differential should be adjusted? Specifically, would you bring the bylaw amendment for a vote, recommend against the study's findings, or table it?"),
    Comment('P-H-07', 'hoa_janet', 'deliberation hour 48',
            "Marcus asked how I'd handle the dues differential study as President if I'm elected. The board's job is to receive the study, make sure it gets to the membership in full, and call a vote on whatever recommendations come out of it — not pre-judge them. If the study concludes the differential is wrong, I'll bring the bylaw amendment for a vote. If it concludes the differential is right, same. The board doesn't get to choose which findings to act on."),
    Comment('P-H-07', 'hoa_patty', 'deliberation hour 50',
            "I want to be honest that Cedar Court communications haven't been a focus for me historically. If elected I'd commit to the quarterly meetings Mr. Ortega suggested, and to publishing agendas in advance."),
    Comment('P-H-07', 'hoa_tomas', 'deliberation hour 60',
            "Genuine question for all three candidates: would you commit to quarterly Cedar Court resident meetings published in advance? It's a small thing but the gap has felt real."),
    Comment('P-H-07', 'hoa_janet', 'deliberation hour 90',
            "Reserve rebuild is the priority. Specific number: get back to ~$45K from the current ~$28K within 14 months without a second special assessment. That requires the existing dues plus the fee adjustments we passed plus no new amenity spending."),
    Comment('P-H-07', 'hoa_don', 'deliberation hour 96',
            "Mr. Pham, I want to acknowledge that Mrs. Reilly's answer to your hour-40 question is the correct one. The board's job is to receive the study, bring whatever it produces to a vote, and not pre-judge. I disagreed with the proposal to authorize the study; I don't disagree with how she'd handle it if the membership passed it. That's a meaningful distinction."),
    Comment('P-H-07', 'hoa_marcus', 'deliberation hour 96',
            "Don, fair point that bylaws are bylaws. I'd note that Janet's response to my hour-40 question matches your framing — receive the study, bring whatever recommendations come out to a vote, no pre-judgment by the board."),
    Comment('P-H-07', 'hoa_brenda', 'deliberation hour 130',
            "Voting opens at 9 AM tomorrow. Rankings can be revised until voting closes."),

    # P-H-08
    Comment('P-H-08', 'hoa_don', 'voting hour 6',
            "Vendor B; the alternatives don't justify the switching cost."),
    Comment('P-H-08', 'hoa_linda', 'voting hour 8',
            "Vendor B: $14K/year, three-year track record here. Vendor C: $11K/year, no local references. The $3K savings doesn't justify the unknown."),
    Comment('P-H-08', 'hoa_marcus', 'voting hour 12',
            "Vendor B has the track record; voting for B."),

    # P-H-09
    Comment('P-H-09', 'hoa_brenda', 'voting hour 8',
            "(I'm aware the preamble is longer than the amendment. The bylaws do require this kind of operational language to be formal even when the underlying matter is informal.)"),
    Comment('P-H-09', 'hoa_tomas', 'voting hour 4',
            "y'all this is a great proposal. Voting yes. (And reading the preamble carefully because that's what Brenda would want.)"),
    Comment('P-H-09', 'hoa_ravi', 'voting hour 6',
            "Voting yes. The bylaws should cover this."),
]


# -----------------------------------------------------------------------------
# Notification Feeds (at reset moment)
# -----------------------------------------------------------------------------

NOTIFICATION_FEEDS = [
    NotificationFeed(
        member_user_id='hoa_janet',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-H-08',
                              note='Halfway-deadline reminder on Landscaping Vendor Selection (Janet is proposer; reminder fires even though she has voted).'),
            NotificationEvent('new_follow',
                              note="A non-quick-login delegator's new follow on Janet's Budget delegate page."),
        ],
    ),
    NotificationFeed(
        member_user_id='hoa_brenda',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-H-08',
                              note='Halfway-deadline reminder on Landscaping Vendor Selection.'),
            NotificationEvent('delegator_rationale',
                              related_proposal_id='P-H-07',
                              note='A delegator on Bylaws & Procedure topic posted a vote rationale on P-H-07 disagreeing with her implied position.'),
            NotificationEvent('new_follow_on_draft',
                              note='A new follow request on her draft bylaw cleanup proposal (P-H-NEW-D1).'),
        ],
    ),
    NotificationFeed(
        member_user_id='hoa_marcus',
        events=[
            NotificationEvent('new_follow',
                              note='A new delegator on his Cedar Court Issues topic — Ravi Chandrasekaran.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-H-08',
                              note='Halfway-deadline reminder on Landscaping Vendor Selection.'),
        ],
    ),
    NotificationFeed(
        member_user_id='hoa_don',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-H-08',
                              note="Halfway-deadline reminder on Landscaping Vendor Selection. (Don has Low preset; doesn't get notified about most other things.)"),
        ],
    ),
    NotificationFeed(
        member_user_id='hoa_linda',
        events=[
            NotificationEvent('delegator_vote_change',
                              related_proposal_id='P-H-08',
                              note='A delegator on Budget topic changed their vote on P-H-08 from Vendor C to Vendor B.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-H-08',
                              note='Halfway-deadline reminder on Landscaping Vendor Selection.'),
        ],
    ),
    NotificationFeed(
        member_user_id='hoa_tomas',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-H-08',
                              note='Halfway-deadline reminder on Landscaping Vendor Selection.'),
        ],
    ),
]


# -----------------------------------------------------------------------------
# OrgBible assembly
# -----------------------------------------------------------------------------

HOA_BIBLE = OrgBible(
    slug='demo-cedar-hollow',
    display_name='Cedar Hollow HOA',
    charter=CHARTER,
    tone_notes=TONE_NOTES,
    recent_history=RECENT_HISTORY,
    sub_orgs=[],
    voting_methods_used=['binary', 'approval', 'rcv'],
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
PHASE 23 INTEGRATION NOTES — HOA BIBLE:

1. User ID convention:
   - HOA users prefixed with `hoa_` for clarity.
   - Cross-org users (Marcus, Janet) appear with separate user IDs per org;
     the technical agent should map these to single underlying user accounts
     during seeding so org-switching shows the same person with different
     org-specific identity content (per Phase 19 per-org delegate identity).

2. Approval / RCV / STV vote rationale encoding:
   - Used `approval_X_Y_Z` for "approved options X, Y, Z" (e.g., `approval_1_2_3_4_5_6` for items 1-6).
   - Used `rcv_X_Y_Z` for "ranked X first, Y second, Z third" when applicable.
   - Technical agent should normalize to whatever the production schema uses.

3. Trajectory data lives in `trajectory_waypoints.py`:
   - This file references proposals by ID; trajectory module has the corresponding
     waypoint and event data for chart rendering.

4. Comments are not exhaustive:
   - Comments in this module are the production set per the comment plan v2.
   - The bible specifies ~250-400 total comments across all three orgs; the HOA's
     share is the substantive ones above plus minimal procedural comments the
     technical agent can generate (e.g., simple "voting yes" comments from
     non-named members can be filler-generated; named-character comments are
     in this file as the source of truth).

5. Notification preset to notification volume mapping (from Phase 21 spec):
   - High: notified on most events affecting their delegates and proposals
   - Medium: notified on substantive events only
   - Low: notified on hard-deadline events and own-proposal events only
   The events listed in NOTIFICATION_FEEDS above are the events that pass
   through each member's preset filter.

6. Position statement and vote rationale rendering:
   - All text fields are markdown-compatible. The technical agent should
     preserve formatting (paragraphs, bold, lists) when rendering to the UI.

7. Patty Voss (non-quick-login) appears in the President election (P-H-07) as
   a candidate. Her candidate statement is in P-H-07's `candidate_statements`
   dict. Her vote rationales and comments on other proposals are in
   COMMENTS list (currently sparse — she comments mainly on P-H-01 voting hour 30
   and P-H-07 deliberation hour 50). The technical agent should ensure her
   user account is seeded with the candidate role for the election.

8. Janet Reilly's HOA presence is contrasted with her Local 4021 presence
   (per cross-org intersection #2). In the Local, she's a quiet rank-and-file
   member with `private` delegate status and 0 notifications at reset. The
   technical agent needs to ensure her Local 4021 voting record is seeded
   (centrist-within-Local pattern; voted yes on 2024 contract ratification)
   even though her Local content is otherwise minimal.

9. Cross-org references in comments:
   - Marcus's references to his planning work are local to HOA.
   - Marcus does NOT mention his Coalition role in HOA content (asymmetric
     acknowledgment is intentional per the Stage 6 consistency sweep finding).
"""
