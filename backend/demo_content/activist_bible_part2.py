"""
Westgate Tenants Coalition Bible — PART 2 of 3
Remaining delegate pages (Maya, Dana, Will), proposals, drafts.
"""

from .schema import (
    TopicVisibility, PositionStatement, VoteRationale,
    DelegatePage, Proposal,
)


# -----------------------------------------------------------------------------
# Delegate Pages — Part 2 (Maya, Dana, Will)
# -----------------------------------------------------------------------------

DELEGATE_PAGES_PART_2 = [
    DelegatePage(
        member_user_id='coalition_maya',
        page_visibility='public',
        intro=(
            "Coordinating Committee, second year. Outreach working group "
            "lead. Up for re-election in the current cycle.\n\n"
            "Day job: social worker at a nonprofit serving formerly-"
            "incarcerated people in housing transition. The professional work "
            "and the Coalition work overlap a lot — housing access for "
            "people coming out of incarceration is one of the places where "
            "displacement, tenant protection failure, and discriminatory "
            "landlord practices compound.\n\n"
            "`public_accepting` on Tenant Protections and Public Housing. "
            "Both topics involve real tradeoffs and disagreements within the "
            "Coalition; the delegate-page surface is one of the better ways "
            "to show my reasoning to people who might delegate."
        ),
        topics=[
            TopicVisibility('Tenant Protections', 'public_accepting'),
            TopicVisibility('Public Housing', 'public_accepting'),
            # Phase 23.2 C1 — 'Elections' added so the Coordinating
            # Committee election proposal (P-C-03) has a valid topic
            # vocabulary entry. Maya is an incumbent up for re-election,
            # so this fits her surface naturally. Private visibility per
            # dispatch guidance for election topics.
            TopicVisibility('Elections', 'private'),
        ],
        position_statements=[
            PositionStatement(
                topic='Tenant Protections',
                text=(
                    "The strongest version of the Coalition's mission is "
                    "preventing displacement of currently-housed tenants, "
                    "especially those most exposed to displacement risk. That "
                    "mission is upstream of every other housing question.\n\n"
                    "My framework: protections aren't optional add-ons to new "
                    "construction; they're the prerequisite. Source-of-income "
                    "discrimination ordinances, just-cause eviction "
                    "requirements, right-to-counsel, rent stabilization — "
                    "these are the pieces that determine whether new policy "
                    "actually reaches the people the Coalition exists to "
                    "represent.\n\n"
                    "If you delegate to me here, expect votes for proposals "
                    "that build durable tenant protection infrastructure and "
                    "against proposals that treat new construction as a "
                    "substitute for it. I think the qualified-YIMBY position "
                    "underweights the protection side of the equation; I "
                    "respect the people making that case but I'm not going "
                    "to be argued into agreeing with them at the cost of the "
                    "tenants the Coalition's mission is built around."
                ),
            ),
            PositionStatement(
                topic='Public Housing',
                text=(
                    "Public housing is the policy category most clearly absent "
                    "from the current Millbrook housing conversation, and that "
                    "absence isn't accidental — it's the result of decades of "
                    "political work to remove public housing from the menu of "
                    "acceptable options.\n\n"
                    "I want to push back on the framing that treats public "
                    "housing as politically infeasible. Vienna's social "
                    "housing stock, Singapore's HDB system, and the older U.S. "
                    "public housing programs (before the 1990s defunding) "
                    "demonstrate that the political infeasibility is "
                    "contingent, not inherent. The Coalition's job is partly "
                    "to make public housing politically possible again.\n\n"
                    "My votes here: support for proposals that move Council "
                    "toward public-housing-adjacent policy (community land "
                    "trusts, public ownership of acquired distressed "
                    "buildings, expansion of voucher-supported developments). "
                    "Skepticism of proposals that frame new market-rate "
                    "construction as filling the gap public housing should fill."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-C-01', 'no', "The rider is real and unusually strong; that's worth acknowledging. It's not enough to flip the balance for the tenants the Coalition exists to represent. Voted no."),
            VoteRationale('P-C-02', 'yes', "Proposer; yes."),
            VoteRationale('P-C-04', 'yes', "The protocols Member Defense worked out during the extensions address most of my concerns. Voted yes during extension 2."),
            VoteRationale('P-C-05', 'yes', "Right to counsel permanence is foundational. Voted yes."),
            VoteRationale('P-C-06', 'yes', "Dana's proposal is well-scoped. Voted yes."),
            VoteRationale('P-C-07', 'yes', "Voted yes."),
            VoteRationale('P-C-08', 'approval_quarterly_monthly', "Quarterly minimum, monthly preferred. Voted both."),
            VoteRationale('P-C-09', 'yes', "Proposer; yes."),
            VoteRationale('P-C-10', 'yes', "Foundational skill-building. Voted yes."),
            VoteRationale('P-C-11', 'yes', "Formalizes what was worked out during P-C-04. Voted yes."),
        ],
    ),

    DelegatePage(
        member_user_id='coalition_dana',
        page_visibility='public',
        intro=(
            "Member Defense working group. Day job is reference librarian at "
            "the downtown branch — also Library steward in AFSCME Local 4021, "
            "where the labor-tenant solidarity comes up regularly.\n\n"
            "`public_accepting` on Member Defense. The work is the unglamorous "
            "practice of tenant defense: showing up at court dates, helping "
            "tenants document conditions, supporting them through landlord-"
            "tenant proceedings. Not splashy. Foundational."
        ),
        topics=[
            TopicVisibility('Member Defense', 'public_accepting'),
        ],
        position_statements=[
            PositionStatement(
                topic='Member Defense',
                text=(
                    "The Coalition's most consistent capacity gap is the "
                    "unglamorous one. Direct Action campaigns get attention; "
                    "Member Defense work is the day-to-day infrastructure "
                    "that makes everything else possible. A tenant who knows "
                    "the Coalition will show up to their hearing trusts the "
                    "Coalition; a tenant who doesn't know that, doesn't.\n\n"
                    "My framework: capacity over rhetoric. The Coalition's "
                    "effectiveness in this domain depends on having enough "
                    "trained defenders to staff the cases that come in, not "
                    "on having strong positions on tenant defense. We've "
                    "been under-resourced for two years; P-C-06 is the "
                    "proposal to fix that.\n\n"
                    "If you delegate to me here, expect votes for proposals "
                    "that build Member Defense capacity and against proposals "
                    "that treat Member Defense as a fallback option for "
                    "Direct Action campaigns without budgeting for the "
                    "capacity."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-C-01', 'yes', "The leverage argument is the case for me. The implementation fight is where the affordability mandate gets enforced or doesn't. Voted yes."),
            VoteRationale('P-C-02', 'no', "Same as Priya — agree with the goal, disagree about whether this amendment is the way to get it."),
            VoteRationale('P-C-04', 'yes', "The escalation matters for the Riverside Properties pattern. The protocols Maya drafted in extension 1 are the prerequisites. Voted yes after protocols were specified."),
            VoteRationale('P-C-05', 'yes', "The pilot was Member Defense's most concrete impact on Coalition members. Permanence is foundational. Voted yes."),
            VoteRationale('P-C-06', 'yes', "Proposer; yes."),
            VoteRationale('P-C-07', 'yes', "Voted yes."),
            VoteRationale('P-C-08', 'approval_monthly', "Monthly cadence; the working groups need timely updates from CC."),
            VoteRationale('P-C-09', 'yes', "The Westgate component overlaps Member Defense's tenant outreach. Voted yes."),
            VoteRationale('P-C-10', 'yes', "Door-knocking training also builds Member Defense recruitment capacity. Voted yes."),
            VoteRationale('P-C-11', 'yes', "Will's formalization is the right capture of what we worked out during P-C-04. Voted yes."),
        ],
    ),

    # Will Sutherland — page_visibility='private_delegators'
    # Demo's private_delegators showcase. Only approved followers see the draft.
    DelegatePage(
        member_user_id='coalition_will',
        page_visibility='private_delegators',
        intro=(
            "Joined the Coalition fourteen months ago after my own rent went "
            "up 18% on lease renewal. Day job is software engineering at a "
            "small Millbrook firm. Policy working group.\n\n"
            "Putting together this page in draft because I want to figure out "
            "what I'd want to say to anyone who'd consider delegating to me "
            "before going public with the page. Feedback welcome from anyone "
            "who's gotten access to the draft."
        ),
        topics=[
            TopicVisibility('Tenant Tech Issues', 'public'),
        ],
        position_statements=[
            PositionStatement(
                topic='Tenant Tech Issues',
                text=(
                    "The Coalition's organizing infrastructure runs on tools "
                    "that weren't designed for tenant organizing. Most of what "
                    "we do for case management, member contact, and campaign "
                    "coordination is in spreadsheets and group chats, which "
                    "works but has real privacy and durability issues.\n\n"
                    "The proposed specialty: thinking about tenant-protective "
                    "technology — what tools we should adopt, what risks we "
                    "should manage in tools we're using now, what's worth "
                    "building versus adopting from other coalitions.\n\n"
                    "This is a niche topic and I'm not sure whether the "
                    "Coalition needs a delegate here or whether the working "
                    "group level is the right surface for these decisions. "
                    "Part of why this page is in draft."
                ),
            ),
        ],
        vote_rationales=[
            VoteRationale('P-C-04', 'yes', "Initial concern about doxing risk drove the destabilization; the protocols developed during extension 1 addressed it. Voted yes once protocols were specified."),
            VoteRationale('P-C-11', 'yes', "Proposer; yes. The substantive work was the P-C-04 deliberation; this is the formalization."),
            VoteRationale('P-C-01', 'yes', "Voted yes after working through the implementation-leverage argument in the deliberation thread. Came in opposed; the negotiation arithmetic Priya laid out and Marcus's implementation-questions list shifted me. Reservations on the affordability mandate remain."),
            VoteRationale('P-C-02', 'no', "Voted no. Came around to Priya's tactical argument about the committee window having closed."),
            VoteRationale('P-C-05', 'yes', "Voted yes."),
            VoteRationale('P-C-06', 'yes', "Dana's proposal addresses real capacity issues. Voted yes."),
            VoteRationale('P-C-07', 'yes', "Voted yes."),
            VoteRationale('P-C-08', 'approval_monthly', "Approved monthly."),
            VoteRationale('P-C-09', 'yes', "Voted yes."),
            VoteRationale('P-C-10', 'yes', "Voted yes; door-knocking is a skill I'd benefit from training in myself."),
        ],
    ),
]


# -----------------------------------------------------------------------------
# Proposals
# -----------------------------------------------------------------------------

PROPOSALS = [
    Proposal(
        proposal_id='P-C-01',
        title='Coalition Position on Riverside Upzoning Proposal',
        proposer_user_id='coalition_priya',
        voting_method='binary',
        state_at_reset='voting, hour 68 of 96 (closes 28 hours after reset)',
        body=(
            "Proposing that the Coalition formally endorse the Riverside "
            "upzoning proposal that Council will be voting on next month.\n\n"
            "The proposal allows buildings up to six stories in the Riverside "
            "corridor, with a 15% affordability set-aside for new construction "
            "over 20 units, defined as 60% AMI. It also includes a tenant-"
            "protection rider that requires demolition of existing rental "
            "units to be replaced 1:1 with comparable units at the same or "
            "lower rent for existing tenants. The rider was added in committee "
            "after Coalition testimony.\n\n"
            "I think we should endorse for three reasons.\n\n"
            "First, the affordability set-aside is meaningful at the scale "
            "we're discussing. If a third of the projected new units in "
            "Riverside come from upzoned parcels (a reasonable estimate based "
            "on the developer pipeline), 15% of that is roughly 200 "
            "affordability-mandated units over five years. That's small "
            "compared to the need, but it's larger than what we'll get from "
            "any other source in that timeframe.\n\n"
            "Second, the tenant-protection rider is unusually strong. Most "
            "upzoning proposals don't include 1:1 replacement at same-or-"
            "lower rent for existing tenants. The fact that Council added it "
            "in response to our testimony suggests we have more leverage on "
            "this than we sometimes give ourselves credit for.\n\n"
            "Third, the upzoning is going to pass with or without our "
            "endorsement. Council has the votes. Our endorsement either "
            "positions us to push for amendments and implementation "
            "safeguards from a place of having been part of the coalition, "
            "or it doesn't and we're outside the room.\n\n"
            "I want to acknowledge — and not skip past — what I'm not saying. "
            "I'm not saying the affordability set-aside is sufficient. It's "
            "not. I'm not saying new construction will reduce displacement "
            "on its own. It won't. I'm not saying the qualified-YIMBY framing "
            "solves the problem; it doesn't, it just changes which problems "
            "are easiest to act on.\n\n"
            "There's a real tension here between endorsing a flawed proposal "
            "because it's the best version of the proposal we're likely to "
            "get, and refusing to endorse because endorsement implies that "
            "the proposal is the right answer. I think the first reading is "
            "the more useful one for our position, but I understand the "
            "second.\n\n"
            "P-C-02 raised the question of whether we should amend before "
            "endorsing. The members who voted for P-C-02 and against this "
            "proposal aren't wrong — they have a coherent theory of leverage. "
            "I disagree about where the leverage actually is, but I want to "
            "be clear that I'm disagreeing about tactics, not about goals."
        ),
        topics=['Land Use Policy', 'Anti-Displacement', 'Tenant Protections'],
    ),

    Proposal(
        proposal_id='P-C-02',
        title='Amendment: Strengthen Affordability Mandates Before Endorsement',
        proposer_user_id='coalition_maya',
        voting_method='binary',
        state_at_reset='failed, 10 days ago (41-59)',
        body=(
            "Proposing an amendment to the Coalition's position on the "
            "Riverside upzoning: the Coalition's endorsement should be "
            "conditional on Council strengthening the affordability mandate "
            "to 25% AMI-defined affordable units (up from 15%).\n\n"
            "The case: 15% is the developer-acceptable floor, not the "
            "Coalition-acceptable one. Studies from cities with stricter "
            "mandates (Cambridge MA, San Francisco's Eastern Neighborhoods) "
            "show that 20-25% mandates can be absorbed by project economics "
            "with smaller projects and different financing structures.\n\n"
            "The structural argument: Coalition endorsement is leverage. "
            "Conditioning endorsement on stronger mandates uses that "
            "leverage at the moment it has the most weight.\n\n"
            "I want to acknowledge the obvious counter: the amendment window "
            "in committee has closed. The argument is that conditioning "
            "endorsement on a floor amendment is functionally a no-endorsement "
            "vote. I disagree — Council members who supported the rider in "
            "response to our testimony will respond to a Coalition that holds "
            "out for stronger terms. The 15% number isn't physics; it's a "
            "negotiated position, and negotiated positions move when pressure "
            "changes.\n\n"
            "Who's the actual constituency for this proposal as currently "
            "written? Developers, future market-rate tenants, the city's "
            "tax base, Council members wanting credit for responding to the "
            "housing crisis. The Coalition's constituency is the second list: "
            "current tenants in buildings that would be redeveloped, "
            "displaced tenants from adjacent neighborhoods, low-income "
            "households needing actually-affordable housing. The 25% mandate "
            "begins to serve that second list. The 15% mandate doesn't."
        ),
        topics=['Land Use Policy', 'Tenant Protections', 'City Council Engagement'],
    ),

    Proposal(
        proposal_id='P-C-03',
        title='Coordinating Committee Election 2026',
        proposer_user_id='coalition_priya',
        voting_method='stv',
        state_at_reset='voting, hour 54 of 168 (closes 114 hours after reset)',
        body=(
            "Three Coordinating Committee seats up for partial re-election. "
            "Six candidates running. Single Transferable Vote with cascade "
            "for vote transfers.\n\n"
            "Candidates:\n"
            "- Priya Krishnan (incumbent, Policy lead)\n"
            "- Maya Goldberg (incumbent, Outreach lead)\n"
            "- Jordan Park (challenger, YIMBY-leaning)\n"
            "- Elena Vasquez (challenger, YIMBY-leaning)\n"
            "- Sandra Brooks (challenger, anti-development-leaning)\n"
            "- David Onyeka (challenger, anti-development-leaning)\n\n"
            "The third-seat outcome will shift the Coalition's center of "
            "gravity. STV cascade will show transfer patterns reflecting the "
            "YIMBY/anti-development split."
        ),
        topics=['Elections'],
        # Phase 23.2 B3: STV electing 3 CC seats from 6 candidates.
        num_winners=3,
    ),

    Proposal(
        proposal_id='P-C-04',
        title='Riverside Properties Campaign Tactical Escalation',
        proposer_user_id='coalition_hector',
        voting_method='binary',
        state_at_reset='passed, 5 days ago (62-38, after SRR force-close)',
        body=(
            "Proposing escalation of the Riverside Properties campaign from "
            "current pressure tactics to a public name-and-shame campaign "
            "targeting the landlord by name and the specific properties "
            "under his management.\n\n"
            "Background: Riverside Properties manages four large complexes "
            "in Westgate and Riverside, including two buildings where "
            "eviction filings have spiked over the past 18 months. Current "
            "Coalition tactics — tenant organizing in specific buildings, "
            "collective complaint filings — have produced documented wins "
            "(three eviction defenses, two repair-cycle improvements) but "
            "haven't shifted the broader pattern.\n\n"
            "The escalation: a public campaign naming the landlord, naming "
            "the buildings, and publishing the pattern. Coalition resources "
            "for the campaign, Member Defense capacity for tenant support "
            "during the public phase.\n\n"
            "What this isn't: a campaign against individual tenants, "
            "building staff, or anyone not the named principal. The "
            "targeting is specific.\n\n"
            "What it is: putting visible cost on a landlord whose current "
            "calculation treats Coalition pressure as a tolerable cost of "
            "business. Visible cost changes the calculation.\n\n"
            "I'm aware this proposal raises concerns about doxing risk for "
            "tenants in the targeted buildings. Member Defense will need to "
            "specify protocols before the campaign launches. Open to "
            "amendments on that point."
        ),
        topics=['Direct Action', 'Anti-Displacement', 'Member Defense'],
    ),

    Proposal(
        proposal_id='P-C-05',
        title='Right to Counsel Pilot Permanence Strategy',
        proposer_user_id='coalition_priya',
        voting_method='binary',
        state_at_reset='passed, 25 days ago (88-12)',
        body=(
            "Pilot's up for renewal. This directs Policy working group to "
            "draft permanence language and the Council lobbying strategy.\n\n"
            "Three specifics worth your input now: keep 200% FPL coverage "
            "indexed to inflation, extend to administrative proceedings "
            "(voucher and public housing terminations) which the pilot "
            "didn't cover, build in budget mechanism that doesn't require "
            "annual reauthorization.\n\n"
            "The strategic question I want member input on before working "
            "group commits: business-friendly Council members will push "
            "back on cost; progressive Council members will want 300% FPL "
            "coverage that makes the bill harder to pass. We need a "
            "position on each before finance committee meets."
        ),
        topics=['City Council Engagement', 'Member Defense', 'Tenant Protections'],
    ),

    Proposal(
        proposal_id='P-C-06',
        title='Member Defense Working Group Annual Budget Line Item',
        proposer_user_id='coalition_dana',
        voting_method='binary',
        state_at_reset='deliberation, hour 42 of 96 (voting opens 54 hours after reset)',
        body=(
            "Proposing an annual $8K budget line item for Member Defense: "
            "training, materials, and stipends for tenant defenders.\n\n"
            "Background: Member Defense has operated on volunteer effort and "
            "ad hoc fundraising since the working group formed in 2020. The "
            "work has grown — case volume in 2025 was 3x what it was in "
            "2022 — without corresponding capacity investment. The visible "
            "result is delays in responding to cases, occasional dropped "
            "follow-throughs, and stewards who burn out faster than we can "
            "train replacements.\n\n"
            "The $8K breakdown:\n"
            "- Training: $2.5K (two sessions/year, materials and trainer "
            "honoraria)\n"
            "- Materials: $1.5K (printed know-your-rights guides in three "
            "languages, tenant case file folders, postage for required "
            "notice tracking)\n"
            "- Stipends: $4K ($50/case for tenant defenders attending "
            "hearings, capped at $400/defender/year)\n\n"
            "The stipend piece is the most debated. I'll note in advance "
            "that some Coalition members are uncomfortable with the "
            "precedent of paid member work. The argument for stipending "
            "hearing attendance is that it's the most time-intensive and "
            "least flexible work — defenders take time off from paid jobs "
            "to attend hearings, and the current arrangement effectively "
            "limits the work to members who can afford to do it for free.\n\n"
            "In the Local I steward in, we tried to formalize steward "
            "training without a budget line item; the training happened "
            "sporadically and unevenly. Formalizing the budget made it "
            "reliable. The same principle applies here."
        ),
        topics=['Member Defense', 'Anti-Displacement'],
    ),

    Proposal(
        proposal_id='P-C-07',
        title='Coalition Statement on Cuyahoga Tenant Strike Solidarity',
        proposer_user_id='coalition_hector',
        voting_method='binary',
        state_at_reset='passed, 40 days ago (96-4)',
        body=(
            "Proposing a Coalition statement of solidarity with the tenant "
            "strike currently underway at the Cuyahoga Place complex in "
            "Cleveland. Non-binding statement.\n\n"
            "The Cuyahoga strike is a 200-unit rent strike against a "
            "landlord with a similar pattern to Riverside Properties — high "
            "eviction filing rates, deferred maintenance, recent acquisition "
            "by a private equity firm. The strike has been running for six "
            "weeks.\n\n"
            "The case for solidarity: tenant organizing builds capacity "
            "through visible support across cities. Cleveland organizers "
            "have specifically asked for solidarity statements from "
            "Coalitions in other cities. Costs us nothing; signals to "
            "landlords here that the network is real.\n\n"
            "I'm aware some members will argue the Coalition should focus "
            "on local issues. That's a fair preference, but solidarity "
            "statements are low-cost and the relational infrastructure they "
            "build pays back when our own campaigns need outside support."
        ),
        topics=['Direct Action', 'Anti-Displacement'],
    ),

    Proposal(
        proposal_id='P-C-08',
        title='Procedural: Frequency of Coordinating Committee Public Updates',
        proposer_user_id='coalition_maya',
        voting_method='approval',
        state_at_reset='passed, 50 days ago (Quarterly approved)',
        body=(
            "Proposing an approval vote on the frequency of Coordinating "
            "Committee public updates to the broader membership. Four "
            "options:\n\n"
            "- Weekly: maximum transparency, significant CC time investment, "
            "may produce update content thinness\n"
            "- Bi-weekly: high transparency, moderate time investment\n"
            "- Monthly: standard cadence for most coalitions\n"
            "- Quarterly: minimum transparency consistent with the CC's "
            "accountability role\n\n"
            "CC currently publishes ad hoc, which has produced gaps where "
            "members aren't sure what the Committee's been working on. Need "
            "member input on the right cadence."
        ),
        options=['Weekly', 'Bi-weekly', 'Monthly', 'Quarterly'],
        topics=['Tenant Protections'],
    ),

    Proposal(
        proposal_id='P-C-09',
        title='Outreach Working Group: Spring Membership Drive Plan',
        proposer_user_id='coalition_maya',
        voting_method='binary',
        state_at_reset='passed, 16 days ago (74-26)',
        body=(
            "Proposing authorization of a coordinated spring membership "
            "drive across April-May with specific neighborhood and "
            "constituency targets.\n\n"
            "Tactical priorities:\n"
            "- Westgate: focus on the four large rental complexes where "
            "existing Coalition presence is thin. Door-to-door outreach "
            "plus visible Coalition presence at neighborhood events.\n"
            "- Downtown: focus on the recent rent-burdened young "
            "professional demographic. Coalition presence at university-"
            "adjacent events; targeted social media.\n"
            "- Riverside: focus on tenants in buildings affected by the "
            "upzoning, regardless of whether endorsement passes.\n\n"
            "What this drive is and isn't: it's about expanding the "
            "membership's depth (more durable engagement) and breadth "
            "(geographic and demographic), not about hitting a numeric "
            "target."
        ),
        topics=['Anti-Displacement', 'Tenant Protections'],
    ),

    Proposal(
        proposal_id='P-C-10',
        title='Direct Action Working Group: Door-Knocking Training Series',
        proposer_user_id='coalition_hector',
        voting_method='binary',
        state_at_reset='voting, hour 8 of 72',
        body=(
            "Proposing authorization of three door-knocking training "
            "sessions for newer Coalition members.\n\n"
            "Direct action capacity depends on members who can do tenant "
            "outreach effectively. Door-knocking is the foundational "
            "skill — it's how new members get introduced to the work and "
            "how existing campaigns build the contact lists they run on.\n\n"
            "Three sessions: skills basics (conversation flow, refusal "
            "handling), tenant-specific protocols (privacy, documentation, "
            "follow-up), and campaign integration (how outreach feeds "
            "specific campaigns).\n\n"
            "Trainer is Joaquin Reyes from a sister coalition in "
            "Charlotte; experienced organizer, has trained six other "
            "coalitions. $1.5K covers his travel and honorarium."
        ),
        topics=['Direct Action', 'Member Defense'],
    ),

    Proposal(
        proposal_id='P-C-11',
        title='Anti-Doxing Protocols for Tenant Defenders',
        proposer_user_id='coalition_will',
        voting_method='binary',
        state_at_reset='passed, 2 days ago (98-2)',
        body=(
            "Proposing formalization of the tenant-protection protocols "
            "that emerged from P-C-04's extension 1 work. The protocols "
            "Maya drafted during the P-C-04 deliberation are good operating "
            "procedure; this proposal makes them Coalition policy for all "
            "future direct-action campaigns, not just Riverside Properties.\n\n"
            "The protocols (per Maya's P-C-04 extension 1 amendment):\n"
            "1. Tenants in named buildings are not opted into public "
            "participation by default\n"
            "2. Buildings and landlords are named publicly; individuals "
            "only with explicit written consent\n"
            "3. Member Defense handles retaliation response during campaigns\n"
            "4. Campaign committees include a Member Defense representative "
            "with veto power over tenant-identifying materials\n\n"
            "The proposal extends these from P-C-04-specific procedure to "
            "Coalition-wide policy. Any future campaign that involves "
            "naming landlords or properties operates under these protocols.\n\n"
            "This is my first proposal as a Coalition member. I want to "
            "acknowledge that the substantive work was Maya's drafting and "
            "Hector's open response to my hour-38 concern. The formalization "
            "is just the closing piece — making sure we don't have to "
            "rediscover these protocols every time we run a campaign."
        ),
        topics=['Member Defense', 'Direct Action'],
    ),
]


# -----------------------------------------------------------------------------
# Drafts
# -----------------------------------------------------------------------------

DRAFTS = [
    Proposal(
        proposal_id='P-C-NEW-D1',
        title='Tenant Tech Tooling Exploration (Draft)',
        proposer_user_id='coalition_will',
        voting_method='binary',
        state_at_reset='draft (not yet posted for deliberation)',
        body=(
            "Draft proposal for the Policy working group to explore tenant-"
            "protective technology tools.\n\n"
            "The Coalition currently runs case management, member contact, "
            "and campaign coordination through spreadsheets and group chats. "
            "Privacy and durability issues are real but unaddressed.\n\n"
            "The exploration would survey existing tools used by sister "
            "coalitions, identify the highest-risk current practices, and "
            "recommend either adopting an existing tool, building something "
            "custom, or restructuring practices to reduce risk in current "
            "tools.\n\n"
            "Not yet ready to post — still working out scope and trying to "
            "find members who have experience with similar tool surveys at "
            "other coalitions."
        ),
        topics=['Tenant Tech Issues'],
    ),
]
