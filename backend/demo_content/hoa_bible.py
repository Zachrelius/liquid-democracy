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
    # Phase 29 C2 — Cedar Hollow showcase expansion: 13 additional named
    # delegates with public pages. Goal is a dense, varied delegation
    # graph rather than just a handful of council-adjacent personas.
    # All quick_login=False; portraits supplied by Z (see C6).
    Member(user_id='hoa_helen', display_name='Helen Krause',
           quick_login=False, role='Member (retired teacher)'),
    Member(user_id='hoa_frank', display_name='Frank Trembath',
           quick_login=False, role='Member (retired plumber)'),
    Member(user_id='hoa_diane', display_name='Diane Petruzzi',
           quick_login=False, role='Member (insurance adjuster)'),
    Member(user_id='hoa_wally', display_name='Walter "Wally" Bromley',
           quick_login=False, role='Member (former county clerk)'),
    Member(user_id='hoa_karen', display_name='Karen Mihalek',
           quick_login=False, role='Member (retired RN, Cedar Court)'),
    Member(user_id='hoa_ron', display_name='Ron Dziedzic',
           quick_login=False, role='Member (auto shop owner)'),
    Member(user_id='hoa_marisol', display_name='Marisol Henneman',
           quick_login=False, role='Member (elementary school principal)'),
    Member(user_id='hoa_ed', display_name='Edgar "Ed" Pawlowski',
           quick_login=False, role='Member (retired Navy supply officer)'),
    Member(user_id='hoa_bev', display_name='Beverly "Bev" Lindstrom',
           quick_login=False, role='Member (real estate agent)'),
    Member(user_id='hoa_carl', display_name='Carl Sundstrom',
           quick_login=False, role='Member (water utility engineer)'),
    Member(user_id='hoa_yolanda', display_name='Yolanda Beasley',
           quick_login=False, role='Member (daycare director, Cedar Court)'),
    Member(user_id='hoa_maureen', display_name='Maureen Czajka',
           quick_login=False, role='Member (reference librarian)'),
    Member(user_id='hoa_hank', display_name='Hank Renfro',
           quick_login=False, role='Member (roofing contractor)'),
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

    # =========================================================================
    # Phase 29 C2 — showcase expansion: 13 additional public delegates.
    # Voice: earnest with deadpan undertones, like the existing five.
    # Authoring goal: distinct angle per delegate so the topic-relevance
    # delegation graph reads as varied rather than concentrated. Each
    # page covers a primary topic (public_accepting) + 0-2 secondaries
    # (public), plus 3-5 vote rationales from P-H-01 through P-H-09.
    # =========================================================================

    DelegatePage(
        member_user_id='hoa_helen',
        page_visibility='public',
        intro=(
            "Thirty-eight years teaching fifth grade at Millbrook Elementary, "
            "retired since 2019. Twenty-six years in Cedar Hollow. Most of what "
            "I know about HOAs I learned from showing up.\n\n"
            "If you delegate to me on Pool & Recreation, expect a community-"
            "center frame rather than an amenity frame. Three generations of "
            "Cedar Hollow kids learned to swim at this pool. That doesn't "
            "settle every operational question but it does shape mine."
        ),
        topics=[
            TopicVisibility('Pool & Recreation', 'public_accepting'),
            TopicVisibility('Long-Term Planning', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Pool & Recreation',
                text=(
                    "The pool is the only place in Cedar Hollow where the whole "
                    "neighborhood physically gathers. Pool decisions are also "
                    "social-fabric decisions, whether the budget paperwork says "
                    "so or not.\n\n"
                    "That doesn't translate to 'spend any amount.' It does mean "
                    "I'll vote against operational decisions that quietly degrade "
                    "the pool's role as a gathering place — hours that exclude "
                    "working families, fee structures that price out the Cedar "
                    "Court households, that sort of thing. Reserve health "
                    "matters too. I try to keep both in view."
                ),
            ),
            PositionStatement(
                topic='Long-Term Planning',
                text=(
                    "Public only because I'd rather you read what I write and "
                    "decide on your own. I don't have a strong frame for capital "
                    "sequencing — Linda and Frank do."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Voting yes. Small adjustment, mostly painless, and Linda has the math right."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Approved the deferred-maintenance items. Items 7-8 are amenity expansion and don't belong this cycle, even from a community-center frame."),
            VoteRationale('P-H-04', 'approval_B_C_D',
                          "Evening extension matters most for the working families on Cedar Court. Weekend-only is a sensible compromise for the budget side. Conservative option stays on the table."),
            VoteRationale('P-H-09', 'yes',
                          "Voting yes. The floats are not a serious problem but the absence of governing language is. Better to write it down."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_frank',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 1998. Retired plumber, thirty-one-year career, "
            "mostly commercial work in the Millbrook corridor. I know what "
            "deferred maintenance looks like from underneath.\n\n"
            "If you delegate to me on Long-Term Planning or Budget, expect "
            "votes anchored to the actual condition of physical things. The "
            "clubhouse roof is older than three of the existing board members. "
            "That's not an opinion, it's a fact, and the budget should reflect "
            "it."
        ),
        topics=[
            TopicVisibility('Long-Term Planning', 'public_accepting'),
            TopicVisibility('Budget', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Long-Term Planning',
                text=(
                    "Capital infrastructure in a 170-household HOA fails on a "
                    "20-30 year cycle. Pool liner: 18 years. Clubhouse roof: "
                    "21 years. Asphalt: 12-15 years on the high-traffic "
                    "sections. We're inside the failure window on at least "
                    "three of those.\n\n"
                    "Long-term planning means sequencing replacements before "
                    "they fail catastrophically. The fall 2025 pool repair is "
                    "the exact pattern we get when we don't. I'll vote for "
                    "spending that addresses sequencing and against spending "
                    "that doesn't."
                ),
            ),
            PositionStatement(
                topic='Budget',
                text=(
                    "Public, not accepting. Linda is the right person to "
                    "delegate Budget to. My role is to keep the physical-"
                    "infrastructure picture visible when Budget decisions get "
                    "made."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Yes. The reserve needs to come up; the fee adjustment is one way to do it."),
            VoteRationale('P-H-02', 'yes',
                          "Voting yes. Linda's numbers are right and the deferred-maintenance backlog is real. The slow rebuild leaves us inside the failure window for another two years. Worth the assessment to get out from under it."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Items 1-6 are real backlog. The Cedar Court fence (item 4) should have been done five years ago."),
            VoteRationale('P-H-04', 'approval_B_C',
                          "Conservative on this one. Pool deck and filter system can't take expanded hours without maintenance budget I don't see coming."),
            VoteRationale('P-H-08', 'approval_B_C',
                          "Vendor B has the track record. Vendor C as backup if the board can document the cost difference is worth the risk."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_diane',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 2011. Day job: claims adjuster at a regional "
            "insurance carrier. I read documents for a living and I notice "
            "when language doesn't say what it appears to say.\n\n"
            "If you delegate to me on Budget, expect a risk-and-exposure lens "
            "rather than a moral one. Cedar Hollow's insurance posture is "
            "tighter than people think; some of the proposals that look like "
            "amenity questions are actually liability questions."
        ),
        topics=[
            TopicVisibility('Budget', 'public_accepting'),
            TopicVisibility('Bylaws & Procedure', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Budget',
                text=(
                    "The reserve isn't just a maintenance fund. It's also "
                    "what stands between the HOA and a special assessment "
                    "the next time something fails. Insurance covers the "
                    "high-tail events; the reserve covers everything else. "
                    "Reserve thinness is risk exposure, not just inconvenience.\n\n"
                    "I'll vote for measured fee adjustments and against new "
                    "spending that isn't either life-safety or reserve-"
                    "rebuilding. I'm aligned with Linda on most votes and "
                    "Janet on most votes; if those two diverge I tend toward "
                    "whichever path preserves more flexibility."
                ),
            ),
            PositionStatement(
                topic='Bylaws & Procedure',
                text=(
                    "Public only because the right person to delegate to is "
                    "Brenda. I read the bylaws closely but she reads them "
                    "professionally."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Voting yes. Modest fee adjustment, no real exposure, math works."),
            VoteRationale('P-H-02', 'yes',
                          "Voting yes against my instincts. A $300 assessment costs less than the exposure of staying under-reserved. The slow rebuild is a comfortable answer that doesn't actually rebuild the reserve fast enough."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Items 1-3 are life-safety, hence required regardless. Items 4-6 are reserve-protective in the medium term. 7-8 increase exposure without offsetting maintenance."),
            VoteRationale('P-H-06', 'yes',
                          "A study is informational. I want the dues-differential question studied. I want the answer to be made deliberately rather than drifted into."),
            VoteRationale('P-H-08', 'approval_B',
                          "Vendor B. The cheaper options carry coverage gaps I'd rather not learn about during the season."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_wally',
        page_visibility='public',
        intro=(
            "Forty-six years in Cedar Hollow. Retired from the county clerk's "
            "office in 2014. I have read Cedar Hollow's bylaws cover to cover "
            "more times than is healthy for anyone.\n\n"
            "If you delegate to me on Bylaws & Procedure, you'll see a strict-"
            "constructionist read. The bylaws are not a vibe. They say things "
            "in particular ways for particular reasons; we ignore those "
            "reasons at our cost."
        ),
        topics=[
            TopicVisibility('Bylaws & Procedure', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Bylaws & Procedure',
                text=(
                    "A small community governance document is more "
                    "interpretive than a corporate bylaw and less interpretive "
                    "than a constitution. The right register is somewhere in "
                    "between, and Cedar Hollow has historically settled it on "
                    "the loose side.\n\n"
                    "I'll vote with Brenda when she sees a procedural problem "
                    "and against amendments that solve problems Cedar Hollow "
                    "hasn't actually had. I diverge from Brenda about once a "
                    "year and usually on whether a given question is procedural "
                    "or substantive."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-05', 'yes',
                          "Voting yes. Brenda's cleanups are accurate and overdue. Low-stakes housekeeping, do it now or do it later."),
            VoteRationale('P-H-06', 'no',
                          "Voting no with Don. A study commissioned by the board is not a neutral information-gathering exercise; it's the front end of an amendment process. The dues structure is in the bylaws and the bylaws are the bylaws."),
            VoteRationale('P-H-09', 'yes',
                          "Yes. The bylaws should say what the practice already is. Better to write it down before someone's $90 float ends up in the dumpster and we have to litigate it."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_karen',
        page_visibility='public',
        intro=(
            "Cedar Court resident, twelve years. Retired RN; thirty-two-year "
            "career in pediatrics at Millbrook Memorial. I delegate-vote in "
            "Cedar Court Issues because I live the dues-differential question "
            "every quarter and I'd rather speak about it directly than have "
            "the question abstracted by people who don't.\n\n"
            "Aligned with Marcus on most Cedar Court positions but with a "
            "sharper edge on the dues question specifically. I will not "
            "pretend it's resolved when it isn't."
        ),
        topics=[
            TopicVisibility('Cedar Court Issues', 'public_accepting'),
            TopicVisibility('Budget', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Cedar Court Issues',
                text=(
                    "Cedar Court was annexed in 1991 with a dues differential "
                    "that was explained at the time as transitional. It is now "
                    "thirty-four years old and structural rather than "
                    "transitional. We pay the same dues as single-family "
                    "households for unit values that are 30-40% lower. The "
                    "math on that has been wrong since the Clinton "
                    "administration.\n\n"
                    "I'll vote for the dues-differential study, for "
                    "infrastructure spending that addresses Cedar Court items "
                    "(the fence, the lot resurfacing), and against framing "
                    "this as Cedar Court vs. SFH when the underlying question "
                    "is whether the bylaws were ever consistent with their own "
                    "stated intent."
                ),
            ),
            PositionStatement(
                topic='Budget',
                text=(
                    "Public, not accepting. Linda is the right Budget delegate. "
                    "I keep my voice on Cedar Court Issues so the dues "
                    "question stays visible."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Voting yes; the adjustment is uniform across unit types so it doesn't worsen the differential."),
            VoteRationale('P-H-02', 'no',
                          "Voting no. A $300 flat assessment widens the Cedar Court / SFH gap by another fixed amount on already-mismatched valuations. The slow rebuild is more equitable even if it's slower."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Item 4 — Cedar Court fence — has been deferred long enough. Items 1-3 are life-safety. 5-6 are sensible."),
            VoteRationale('P-H-06', 'yes',
                          "Yes. The study is the entry point to a question that's been waiting thirty-four years. A study is not an amendment; Brenda is right on that."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_ron',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 2007. Own and operate Dziedzic Auto on Route 9. "
            "I run a small business with a tight margin, which has taught me "
            "the difference between operational decisions and one-time spending "
            "decisions. Most of what I vote on is the difference between those "
            "two.\n\n"
            "If you delegate to me on Budget, expect a small-business operating "
            "frame: every recurring obligation is a permanent obligation, "
            "every special assessment is a temporary one, and the board should "
            "be honest about which is which."
        ),
        topics=[
            TopicVisibility('Budget', 'public_accepting'),
            TopicVisibility('Pool & Recreation', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Budget',
                text=(
                    "Operational vs. capital matters. Operational lives in the "
                    "monthly dues forever; capital is paid for once. Cedar "
                    "Hollow's recurring spending has crept up while the reserve "
                    "fell. That isn't a math problem, it's a discipline "
                    "problem.\n\n"
                    "I'll vote for fee adjustments that are clearly tied to "
                    "either reserve rebuild or backlog completion. I'll vote "
                    "against operational expansions dressed up as one-time "
                    "spending. Some overlap with Linda; sharper edge on what "
                    "counts as recurring."
                ),
            ),
            PositionStatement(
                topic='Pool & Recreation',
                text=(
                    "Public, not accepting. The pool is a fixed asset with a "
                    "known operating profile. I vote it from the budget side."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Yes. Recurring fee adjustment with a recurring purpose — that's the right shape."),
            VoteRationale('P-H-02', 'no',
                          "Voting no. The slow rebuild is the discipline answer. A special assessment papers over a recurring discipline problem with a one-time payment, which is the pattern we keep falling into."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Items 1-6. Standard backlog work. 7-8 are amenity expansion sold as maintenance and I'm not buying it."),
            VoteRationale('P-H-08', 'approval_C',
                          "Vendor C. Vendor B's renewal pricing has crept above market; Vendor C's references are solid. Vendor A and D are too unknown for a multi-year contract."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_marisol',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 2014. Principal at Millbrook Elementary since "
            "2018. Two kids in the district. I came to the HOA from the "
            "school side, which means I think about how decisions affect "
            "households with children, and how the decisions get communicated.\n\n"
            "If you delegate to me on Pool & Recreation, you'll see a family-"
            "access lens. If you delegate on Long-Term Planning, you'll see a "
            "communications lens — half the conflicts I watch on the board are "
            "communications problems that turn into substantive ones."
        ),
        topics=[
            TopicVisibility('Pool & Recreation', 'public_accepting'),
            TopicVisibility('Long-Term Planning', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Pool & Recreation',
                text=(
                    "Two-thirds of Cedar Hollow households have children "
                    "under 18 or grandchildren who visit weekly. Pool "
                    "decisions land disproportionately on those households. "
                    "Hours, fees, and access policies all read as small "
                    "operational choices and play out as social ones.\n\n"
                    "I'll vote for hours that include working families, for "
                    "fee structures that don't squeeze the Cedar Court "
                    "households, and against operational changes that "
                    "concentrate access among households that already have "
                    "the most flexibility."
                ),
            ),
            PositionStatement(
                topic='Long-Term Planning',
                text=(
                    "Public, not accepting. Linda and Frank carry this topic "
                    "well. My job is to flag when long-term decisions need "
                    "earlier or clearer communication to the membership."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Yes. Modest, manageable, and the math is transparent."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Items 1-6. Item 4 in particular — Cedar Court has waited too long for that fence."),
            VoteRationale('P-H-04', 'approval_C_D',
                          "Evening and weekend options. Both expand access for households whose schedules don't accommodate midday pool time."),
            VoteRationale('P-H-09', 'yes',
                          "Yes. Tagged-vs-untagged is a clean rule and the community has been litigating it informally for years. Brenda's preamble is heroic; the rule is right."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_ed',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 1996. Retired Navy supply officer, 1972-1994. "
            "Most of what I know about process I learned moving cargo through "
            "ports for two decades.\n\n"
            "If you delegate to me on Bylaws & Procedure or Long-Term "
            "Planning, expect votes anchored to clarity and sequencing. The "
            "HOA has historically run on goodwill and informal practice, "
            "which works until it doesn't. Writing things down is not "
            "bureaucracy; it's how a small organization stays the same "
            "organization through generational turnover."
        ),
        topics=[
            TopicVisibility('Bylaws & Procedure', 'public_accepting'),
            TopicVisibility('Long-Term Planning', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Bylaws & Procedure',
                text=(
                    "Brenda has the legal-administrative read. Wally has the "
                    "strict-constructionist read. I have neither. What I "
                    "carry is the operational read: does this procedure work "
                    "when the people running it are tired, distracted, or "
                    "new? If it doesn't, it's not really a procedure, it's a "
                    "set of habits in formal clothing.\n\n"
                    "I'll vote for amendments that close procedural holes "
                    "and against amendments that add formality without "
                    "closing a hole. Aligned with Brenda 80% of the time; "
                    "the divergence is on when 'rare amendment' becomes "
                    "'should-have-amended-already.'"
                ),
            ),
            PositionStatement(
                topic='Long-Term Planning',
                text=(
                    "Public, not accepting. My frame on long-term planning "
                    "is sequencing-and-supply-chain, which is partial. Frank "
                    "and Linda carry the more complete picture."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-05', 'yes',
                          "Yes. Procedural cleanup, exactly the kind of writing-down that prevents next year's argument."),
            VoteRationale('P-H-06', 'yes',
                          "Yes. A study addressing a question the bylaws don't currently address well is the right sequencing. Don's procedural concern is reasonable but reads to me as deflection."),
            VoteRationale('P-H-09', 'yes',
                          "Yes. The float-storage problem is small but the lack of governing language is the kind of gap that grows."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_bev',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 2003. Real estate agent at Henneman & "
            "Lindstrom (Millbrook). My practice is mostly the school district, "
            "so I know Cedar Hollow's reputation in the local market in some "
            "detail.\n\n"
            "If you delegate to me on Long-Term Planning, expect votes "
            "informed by market signal — what kinds of HOAs hold value, what "
            "kinds drift. Cedar Hollow is currently in the middle of the "
            "Millbrook-area HOA market and could move either direction over "
            "the next decade. The Long-Term Planning choices matter for that."
        ),
        topics=[
            TopicVisibility('Long-Term Planning', 'public_accepting'),
            TopicVisibility('Cedar Court Issues', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Long-Term Planning',
                text=(
                    "HOAs that maintain reserve discipline, complete deferred "
                    "maintenance on visible schedule, and avoid the cycle of "
                    "amenity-expansion-then-special-assessment hold value 8-12% "
                    "better than HOAs that don't. That's the kind of number "
                    "agents quote in coffee.\n\n"
                    "Cedar Hollow has historically been a maintenance-discipline "
                    "HOA. The drift since 2016 hasn't been catastrophic but it's "
                    "visible from outside. I'll vote for spending that addresses "
                    "the maintenance picture and against decisions that make "
                    "Cedar Hollow look like an HOA that doesn't know its own "
                    "balance sheet."
                ),
            ),
            PositionStatement(
                topic='Cedar Court Issues',
                text=(
                    "Public, not accepting. Cedar Court issues are material to "
                    "long-term planning — the dues differential affects how "
                    "the entire HOA is read in the local market — but Karen "
                    "and Marcus are the right delegates for the topic itself."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Yes. Visible from outside as a board doing the math correctly. Worth doing for that reason alone."),
            VoteRationale('P-H-02', 'yes',
                          "Voting yes with regret. The faster rebuild reads better to a buyer than the slow one, even though the membership won't go for it."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Items 1-6 are visible maintenance. 7-8 are visible amenity expansion at the wrong moment in the budget cycle."),
            VoteRationale('P-H-06', 'yes',
                          "Yes. The dues question is going to surface eventually; better to surface it through a study commissioned by the board than through a unit-value reassessment."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_carl',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 2010. Engineer at Millbrook Regional Water "
            "Authority — twenty-two-year career, mostly distribution-side. "
            "I am a pool skeptic in the technical-asset sense. The pool is "
            "a high-maintenance fixed asset attached to a small reserve, "
            "and that ratio has me uneasy.\n\n"
            "I am not a pool skeptic in the social sense — Helen has a fair "
            "point about gathering. If you delegate to me on Pool & "
            "Recreation, expect a votes-from-the-engineering-side reading."
        ),
        topics=[
            TopicVisibility('Pool & Recreation', 'public_accepting'),
            TopicVisibility('Budget', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Pool & Recreation',
                text=(
                    "The pool's annual operating cost is ~$11K. Its "
                    "replacement cost on a 25-year cycle, discounted "
                    "appropriately, is another ~$3-4K/year equivalent. The "
                    "HOA's reserve target should reflect both numbers.\n\n"
                    "Operating decisions that increase wear (extended hours, "
                    "higher chemical demand, expanded equipment) shorten "
                    "replacement cycle. Operating decisions that improve "
                    "access without increasing wear are mostly free. I sort "
                    "the proposals along that axis and vote accordingly."
                ),
            ),
            PositionStatement(
                topic='Budget',
                text=(
                    "Public, not accepting. Linda and Frank are the right "
                    "Budget delegates. I keep my voice on Pool & Recreation "
                    "because that's the topic where my engineering frame "
                    "translates."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Yes. The pool fee component covers a real operating cost."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Items 1-6 are correct prioritization. Pool deck (item 5) is at end of life — voting yes on that one with some emphasis."),
            VoteRationale('P-H-04', 'approval_B_C',
                          "Conservative on hours. The filter system at Cedar Hollow is sized for current demand with little headroom; expanded hours need a chemical-demand calc the board hasn't shown me."),
            VoteRationale('P-H-09', 'yes',
                          "Yes. Operationally it changes nothing; procedurally it closes a small hole. Cost-free, vote yes."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_yolanda',
        page_visibility='public',
        intro=(
            "Cedar Court resident, eight years. I run Beasley Day Care out of "
            "the unit. Six kids most days, eight on Fridays. The Cedar Court "
            "side of Cedar Hollow shows up in my living room every weekday.\n\n"
            "I vote on Cedar Court Issues from the working-family side and on "
            "Pool & Recreation from the kids-need-water-in-July side. Aligned "
            "with Karen on most votes; sharper edge on access-and-affordability "
            "specifically."
        ),
        topics=[
            TopicVisibility('Cedar Court Issues', 'public_accepting'),
            TopicVisibility('Pool & Recreation', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Cedar Court Issues',
                text=(
                    "Cedar Court households are disproportionately working "
                    "families. The dues differential and the deferred-"
                    "maintenance pattern both land hardest on the households "
                    "with the tightest margins, which are the households "
                    "least able to push back through board representation. "
                    "That pattern needs explicit voice.\n\n"
                    "I'll vote for infrastructure spending that addresses "
                    "Cedar Court items, against assessments that widen the "
                    "differential, and for the dues study Tomás proposed."
                ),
            ),
            PositionStatement(
                topic='Pool & Recreation',
                text=(
                    "Public, not accepting. Helen and Marisol carry this "
                    "well. My voice on the pool stays focused on whether "
                    "fees and access make sense for households with kids on "
                    "the working-family side of the dues gap."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Yes. Uniform adjustment, hits everyone proportionally."),
            VoteRationale('P-H-02', 'no',
                          "No. $300 flat is two weeks of groceries on the Cedar Court side and an inconvenience on the SFH side. Voting it down."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Item 4 — Cedar Court fence — has waited eleven years. Items 1-3 are life-safety. 5-6 are sensible."),
            VoteRationale('P-H-04', 'approval_C_D',
                          "Evening and weekend hours. Working families don't show up at 11am on a Tuesday."),
            VoteRationale('P-H-06', 'yes',
                          "Yes. The dues structure has been waiting for this study since before my kids were born."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_maureen',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 2008. Reference librarian at Millbrook "
            "Public Library, third floor. I keep the institutional memory "
            "of HOAs longer than the HOAs do — three of my regular patrons "
            "are former Cedar Hollow board members and the Cedar Hollow "
            "archive that exists is largely on a shelf I look after.\n\n"
            "If you delegate to me on Bylaws & Procedure, you'll see votes "
            "informed by what Cedar Hollow has actually done historically, "
            "not what we say we've done."
        ),
        topics=[
            TopicVisibility('Bylaws & Procedure', 'public_accepting'),
            TopicVisibility('Elections', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Bylaws & Procedure',
                text=(
                    "The bylaws have been amended seventeen times since "
                    "1987. I have copies of all seventeen amendments and "
                    "all seventeen sets of meeting minutes that produced "
                    "them. About half landed in response to a specific "
                    "operational problem; about half landed in response to "
                    "a procedural one. Cedar Hollow is best when those two "
                    "kinds of amendments are kept distinct.\n\n"
                    "I'll vote for amendments that show clear operational "
                    "or procedural cause and against amendments that bundle "
                    "the two. Aligned with Brenda and Wally on most votes; "
                    "diverge mainly when there's a historical pattern they "
                    "haven't seen and I have."
                ),
            ),
            PositionStatement(
                topic='Elections',
                text=(
                    "Public, not accepting. Cedar Hollow election procedure "
                    "is documented in the bylaws and the Secretary runs it. "
                    "My voice is informational — when something in current "
                    "procedure matches or doesn't match historical practice, "
                    "I flag it."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-05', 'yes',
                          "Yes. The cross-reference errors Brenda is fixing are real and originated in the 2019 amendments, which were rushed. Standard cleanup."),
            VoteRationale('P-H-06', 'yes',
                          "Yes. The dues-differential question was last formally examined in 1994 (annual report; I have the copy). Thirty-one years is long enough."),
            VoteRationale('P-H-09', 'yes',
                          "Yes. The float-storage protocol Brenda is codifying matches what Cedar Hollow has been doing since 2003. Writing it down is overdue."),
        ],
    ),

    DelegatePage(
        member_user_id='hoa_hank',
        page_visibility='public',
        intro=(
            "Cedar Hollow since 2015. Owner of Renfro Roofing — small firm, "
            "six employees, twenty-mile service area. I have personally "
            "looked at the clubhouse roof and the pool equipment shed.\n\n"
            "If you delegate to me on Budget, expect contractor's-eye votes. "
            "Deferred maintenance compounds faster than people realize, and "
            "I have run the rebid numbers on enough underbid jobs to know "
            "what the spread looks like."
        ),
        topics=[
            TopicVisibility('Budget', 'public_accepting'),
            TopicVisibility('Long-Term Planning', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Budget',
                text=(
                    "Cedar Hollow's deferred-maintenance backlog has the "
                    "shape of a problem I've seen at thirty client sites. "
                    "Items 1-6 of P-H-03 are reasonable line items at "
                    "reasonable prices. Items 7-8 are amenity expansion "
                    "that doesn't belong in the same vote.\n\n"
                    "I'll vote for fee adjustments and assessments that "
                    "fund backlog. I'll vote against amenity items in "
                    "maintenance-shaped votes, which is a pattern boards "
                    "fall into when they want amenity items to pass on "
                    "maintenance momentum. Aligned with Linda; sharper on "
                    "the framing question specifically."
                ),
            ),
            PositionStatement(
                topic='Long-Term Planning',
                text=(
                    "Public, not accepting. Frank is the right Long-Term "
                    "Planning delegate. My voice on Budget already covers "
                    "the maintenance-sequencing question from a different "
                    "angle."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-H-01', 'yes',
                          "Yes. Modest, well-framed."),
            VoteRationale('P-H-02', 'yes',
                          "Yes. The slow rebuild lets the backlog compound; I've seen what compound deferred maintenance looks like and would rather pay $300 now."),
            VoteRationale('P-H-03', 'approval_1_2_3_4_5_6',
                          "Items 1-6, no further. The pool deck (5) and clubhouse roof (6) are at the point where another year of deferral means a larger contract next year."),
            VoteRationale('P-H-08', 'approval_B_C',
                          "Vendor B has the references. Vendor C is the responsible second choice. The cheaper options are cheap for reasons."),
        ],
    ),
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
    # Phase 29 C5: muted cedar-green for the showcase org. Routed into
    # Organization.settings['branding']['primary_color'] by the seed
    # pipeline; BrandingThemeApplier consumes from there.
    brand_color='#3B5A3B',
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
