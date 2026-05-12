"""
Westgate Tenants Coalition Bible — PART 3 of 3
Comments, notification feeds, OrgBible assembly, integration notes.
"""

from .schema import Comment, NotificationEvent, NotificationFeed, OrgBible

# Import data from Parts 1 and 2 for assembly
from .activist_bible_part1 import (
    CHARTER, TONE_NOTES, RECENT_HISTORY, MEMBERS, DELEGATE_PAGES_PART_1,
)
from .activist_bible_part2 import DELEGATE_PAGES_PART_2, PROPOSALS, DRAFTS


# -----------------------------------------------------------------------------
# Comments
# -----------------------------------------------------------------------------

COMMENTS = [
    # P-C-01 — YIMBY arc deliberation thread
    Comment('P-C-01', 'coalition_hector', 'deliberation hour 6',
            "Let's be honest about who benefits here.\n\n"
            "The Riverside upzoning was drafted with input from the regional builders' association. The 15% affordability set-aside is the number builders said they could absorb. The rider exists because of our committee testimony — that's the part of this that's ours, and it's the only part of this that's ours.\n\n"
            "When developers say 'we need supply to flow,' what they mean in practice is they need to demolish currently-affordable rental housing in Riverside and replace it with buildings whose units are more expensive, with 15% of new units affordable at a level the displaced tenants mostly can't afford either.\n\n"
            "This isn't theoretical for the people I live next to. Two of the buildings my neighbors are in are exactly the kind of site that would get redeveloped under this upzoning. The rider gives them right of return at the same rent on paper. Construction takes 24-36 months and most of them won't come back.\n\n"
            "I respect Priya and Marcus's work. We're optimizing for different things. Voting no."),
    Comment('P-C-01', 'coalition_marcus', 'deliberation hour 10',
            "What I'd want to know on this proposal: how is '60% AMI' defined — metro, city, or census tract? Tract-level makes the mandate weaker in Riverside because the median there is higher. The bill says 'the city' without specifying methodology.\n\n"
            "Other open implementation questions the bill is silent on: compliance verification (self-report vs. audit), enforcement when developers fall out of compliance (clawback vs. fines vs. permit restrictions), tenant rent-lock duration during construction (the rider says 'same or lower rent' but no period specified).\n\n"
            "The set-aside percentage matters less than whether the implementation language is strong. Endorsing puts us inside that fight. That's where I'm landing."),
    Comment('P-C-01', 'coalition_maya', 'deliberation hour 14',
            "I want to push back on the framing here, and specifically on the framing that the choice is between 'endorse and influence implementation' and 'don't endorse and lose leverage.'\n\n"
            "Who's the actual constituency for this proposal? Developers wanting to build in Riverside, future market-rate tenants, the city's tax base, Council members who want to be seen responding to the housing crisis without spending political capital on stronger interventions, and roughly 200 mandated-affordable units over five years.\n\n"
            "Who isn't primarily served: current tenants in buildings that would be redeveloped, the broader displacement-affected population in adjacent neighborhoods, the city's existing affordable housing stock that competes with new buildings.\n\n"
            "The qualified-YIMBY argument is that the second list benefits indirectly from supply effects. The evidence on this is more contested than the argument usually acknowledges, and even in favorable readings the benefits propagate slowly and unevenly. People displaced now don't get to wait for filtering effects.\n\n"
            "Coalition's job, as I understand it, is to represent the second list. This proposal primarily serves the first. The amendment was the right move. Voting no on the unamended version."),
    Comment('P-C-01', 'coalition_will', 'deliberation hour 22',
            "Genuine question and apologies if this is the obvious one — why don't we just require 30% affordability and let developers figure out the project economics?\n\n"
            "[Edited at hour 26: Okay, read Priya and Marcus's responses. Affordability mandate is negotiated against pro formas; too high and projects don't get built; ends up at zero affordable units instead of fewer-than-we-wanted-but-some. Got it. Might still vote no for different reasons than two hours ago.]"),
    Comment('P-C-01', 'coalition_marcus', 'deliberation hour 22',
            "Priya covered the arithmetic. The piece her response gestures at: 'demand the outcome' and 'engage at the detail level' are two different theories of how the Coalition has leverage. Demand-the-outcome is cleaner. Engage-at-detail produces more affordable units. Both are defensible. The right-to-counsel pilot worked because we did the second one."),
    Comment('P-C-01', 'coalition_priya', 'deliberation hour 24',
            "Marcus has the negotiation arithmetic. The thing I'd add: 30% pencils out in some markets, just at lower volumes. So the question becomes whether we want more buildings with fewer affordable units each, or fewer buildings with more affordable units each. There's a real answer to that question but it depends on what we think Millbrook needs most. The 15% is where the developer pro formas converge for Millbrook's market. We could push for 18-20% and probably still get built, but the amendment window in committee closed two weeks ago."),
    Comment('P-C-01', 'coalition_jay', 'deliberation hour 36',
            "Coalition member about a year, mostly come to events, don't comment often. Sharing where I landed because I think the path through this might be useful for anyone still working it out.\n\n"
            "Came in opposed. Set-aside felt low. The 'developers benefit either way' framing from Hector and Maya tracked with what I see in my neighborhood. Planning to vote no.\n\n"
            "The thread shifted me. Marcus's implementation-questions list. Priya's response to Will. Reading Marcus's position statement (it's long, worth it). The leverage point — that I've been part of two of the Coalition's implementation fights and inside-the-coalition had way more pull than outside — is what actually moved me.\n\n"
            "Voting yes with reservations. Reservations Hector and Maya raise are real. The implementation argument is, for me, the deciding factor.\n\n"
            "Mentioning this because deliberations should sometimes change people's minds and we rarely say so out loud."),
    Comment('P-C-01', 'coalition_marcus', 'voting hour 36',
            "Hector's right that developers benefit from upzoning. The question is whether developer benefit is the only consequence or whether other consequences also follow. I think other consequences follow when the mandates and protections are real. He thinks the rider is too weak to produce them. We're not disagreeing about whether developers benefit — we're disagreeing about whether the net effect on Millbrook's housing situation is positive. That's a different argument, and it's settleable with implementation data we don't yet have."),
    Comment('P-C-01', 'coalition_maya', 'deliberation hour 48',
            "I want to come back to Priya's earlier point about Council adding the tenant-protection rider in response to our testimony, because I let that go without engaging and I shouldn't have.\n\n"
            "The rider is real. We organized for it; it exists because of that. I framed this proposal as primarily serving developers and left out the rider as a counter-example.\n\n"
            "Revising: the proposal isn't all developer-friendly with an inadequate mandate bolted on. It's a developer-friendly proposal that also contains a tenant-protection rider that exists because of organizing pressure. The question is whether the rider is enough to flip the balance.\n\n"
            "I think it isn't, mostly because enforcement language is weak enough that I expect developer lawyers to work around it. Priya thinks the implementation fight can strengthen it. We disagree about how much enforcement work is realistic in the implementation phase. Knowable in retrospect; not now.\n\n"
            "Staying no. But Priya's right that we built something here. The next year of implementation work matters and I'll be part of it whichever way this vote lands."),
    Comment('P-C-01', 'coalition_dana', 'voting hour 24',
            "Voted yes. The implementation fight is where the actual outcomes for tenants get decided, and being inside the coalition that passed it gives Member Defense more pull during enforcement."),
    Comment('P-C-01', 'coalition_hector', 'voting hour 24',
            "The leverage argument cuts both ways. Being inside the coalition that passed an inadequate proposal is also being inside the coalition that's identified as having supported it. There's a real cost to that identification when the next upzoning comes up and developers cite our endorsement as evidence of Coalition assent."),
    Comment('P-C-01', 'coalition_priya', 'voting hour 48',
            "Hector and Maya and I are going to disagree on this vote. That's fine — the Coalition has held disagreements like this before and we're better for it. Whichever way it lands, the people I work with on the right-to-counsel work, Member Defense, Outreach, Direct Action — those people are still my comrades on Monday. The YIMBY/anti-development split is one decision; the Coalition's work over the next decade is the bigger thing."),

    # P-C-02 — amendment thread
    Comment('P-C-02', 'coalition_hector', 'deliberation hour 4',
            "Maya's right. The 15% number is the developer-acceptable number, not the Coalition-acceptable number. Voting yes on the amendment."),
    Comment('P-C-02', 'coalition_priya', 'deliberation hour 8',
            "Maya's framing on this amendment is internally consistent and I want to address why I'm landing on the other side of it.\n\n"
            "Maya's right that 25% is more defensible policy than 15%. She's also right that Council has historically responded to organized pressure to strengthen affordability requirements. So why am I against?\n\n"
            "Two reasons. First, timing. Council finance committee passed the current language two weeks ago. The full Council vote is in three weeks. The amendment window inside the committee process is closed. The only way to strengthen the mandate now is to introduce a Council floor amendment, which requires a council member to champion it, which we haven't lined up. So in practice, the amendment would mean we don't endorse, the proposal passes anyway, and we're left explaining why we sat it out.\n\n"
            "Second, signal. Conditioning endorsement on a higher number sends a message about the Coalition's posture. We can be the people pushing for stronger affordability inside the coalition that passed the proposal, or we can be the people who held out and then watched it pass without us.\n\n"
            "We have a real choice between two strategies, and I think we're getting drawn into a frame where one is the principled position and the other is the compromised position. They're both principled. They're optimizing for different things."),
    Comment('P-C-02', 'coalition_marcus', 'deliberation hour 12',
            "I want to engage with Maya's amendment carefully because I think she's right about the substance and I'm voting against the amendment anyway, and that's an unusual position that deserves explanation.\n\n"
            "Maya is right that the 15% mandate is inadequate. She's right that 25% is more defensible policy. She's right that there's evidence from other cities that mandates in the 20-25% range get projects built.\n\n"
            "Where I land differently is on the tactical question. The mandate-strengthening fight is going to happen. The question is when and through what channel. The amendment routes it through 'condition the endorsement on it.' I think it should be routed through 'endorse, then organize for amendments to the implementing rules and a stronger mandate in the next upzoning.' The first version puts our leverage at the endorsement moment; the second puts our leverage across the next year of implementation work.\n\n"
            "I'd rather have a year of organizing capacity directed at implementation than a single high-stakes amendment vote. But this is a tactical judgment, not a settled question. If you think the amendment has higher expected value than the implementation organizing, voting for the amendment is reasonable."),
    Comment('P-C-02', 'coalition_jay', 'voting hour 40',
            "I voted yes on the amendment but I want to share why my reasoning doesn't fully track with Priya's tactical case. Even if the amendment fails, I think Coalition votes also function as precedent for future negotiations. Voting no on this amendment establishes the pattern of endorsing imperfect proposals; voting yes establishes the pattern of holding out for better ones. That has costs even when each individual decision looks right.\n\n"
            "Voting yes on the amendment despite Priya's framing because of the precedent question."),
    Comment('P-C-02', 'coalition_priya', 'voting hour 60',
            "The precedent point is fair. I've been treating this as a tactical question about this specific proposal; you're right that it also functions as precedent. That shifts how I think about it without changing my vote — but whichever way this lands, the Coalition should explicitly work out our endorse-vs-amend-before-endorsing criteria. Relitigating from first principles every Council cycle isn't sustainable."),

    # P-C-04 — SRR force-close thread (the biggest in the demo)
    Comment('P-C-04', 'coalition_maya', 'voting hour 6',
            "Voting yes. Hector's right that Riverside Properties calculates Coalition pressure as a cost of business. Visible cost changes the calculation."),
    Comment('P-C-04', 'coalition_will', 'voting hour 38',  # SRR destabilization #1
            "I want to flag something the proposal as currently written doesn't address.\n\n"
            "The name-and-shame campaign involves publishing the landlord's name and the specific buildings. The buildings have tenants. Some of those tenants will be visible by virtue of being current residents of the named buildings, even if their individual names aren't published.\n\n"
            "What's the protocol for protecting tenants who don't want their living situation publicized? What happens if a tenant in one of the named buildings has a reason to keep a low profile — undocumented status, domestic violence situation, employer issues — and being a publicly-known resident of a publicly-named building creates risk for them?\n\n"
            "I'm not opposed to the escalation in principle. I think this concern is significant enough that the proposal needs explicit protocols before launching, and the protocols need Member Defense involvement to specify what happens for tenants who participate publicly versus tenants who don't.\n\n"
            "What if we tried to get the protocols specified during a deliberation extension and then voted on the full package?"),
    Comment('P-C-04', 'coalition_hector', 'voting hour 42',  # opens extension 1
            "Will, this is exactly the kind of concern I should have thought about and didn't fully think through. Let's build in those protections.\n\n"
            "Specifically: tenants in named buildings get to opt in to public participation, not be opted in by default. Public materials reference the buildings and the landlord; individual tenants are named only with explicit consent. Member Defense handles the protocol for tenants who want to participate publicly versus those who don't.\n\n"
            "I'm going to ask Maya and the Member Defense working group to draft amendment language for these protocols before voting continues. The campaign needs the protocols; the protocols need to be in writing."),
    Comment('P-C-04', 'coalition_maya', 'extension 1 hour 8',  # protocol drafting
            "Draft amendment language for the tenant-protection protocols, per Hector's request after Will's hour-38 concern:\n\n"
            "1. Opt-in only. Tenants in named buildings are not opted into public participation by default. Member Defense communicates with tenants in affected buildings; only those who explicitly consent are referenced in public materials.\n\n"
            "2. Building-and-landlord named; individuals named only with explicit consent. Public campaign materials reference Riverside Properties and the specific buildings. Individual tenants are named only with separate written consent.\n\n"
            "3. Member Defense handles all retaliation response during the campaign. Tenants who participate publicly receive priority Member Defense capacity if the landlord retaliates.\n\n"
            "4. Campaign committee includes a Member Defense representative with veto power over public materials that include tenant-identifying information.\n\n"
            "These protocols become the campaign's operating procedure. The Coalition cannot launch the public phase until the protocols are operational."),
    Comment('P-C-04', 'coalition_marcus', 'extension 1 hour 12',
            "Maya's draft protocol language addresses the immediate issue; Hector's question about retaliation response is the next one."),
    Comment('P-C-04', 'coalition_hector', 'extension 1 hour 14',
            "Maya's draft language addresses the opt-in question and the consent protocol. What it doesn't yet address is what happens when a tenant participates publicly and the landlord retaliates. We need Member Defense capacity specifically for retaliation response during the campaign. Dana, can you speak to whether that capacity exists currently or whether we'd need to build it?"),
    Comment('P-C-04', 'coalition_dana', 'extension 1 hour 16',
            "Hector asked whether Member Defense has current capacity for campaign-driven retaliation response. Honest answer: marginal. The proposal P-C-06 (Member Defense budget line) would change that significantly, but it's not yet passed. Current capacity covers the cases coming through normal channels; campaign-driven case spikes would stretch us. The protocols are the right structure; capacity to enforce them is the next question."),
    Comment('P-C-04', 'coalition_will', 'extension 1 hour 20',
            "Maya's draft language addresses the opt-in question and the consent protocol. Hector's question about retaliation response is the right next question. Dana's capacity assessment will tell us whether the protocols are operational."),
    Comment('P-C-04', 'coalition_renee', 'voting hour 92',  # SRR destabilization #2
            "I want to raise something the proposal hasn't addressed.\n\n"
            "The protocols Maya drafted in extension 1 are right. They cover opt-in, consent, retaliation response. What they assume is that Member Defense has the capacity to do the retaliation response work. Dana's been quiet on this question and I think the answer matters.\n\n"
            "When we did the Greenway Apartments campaign in 2019, we built protocols similar to these. The protocols held; the capacity didn't. We had three retaliation incidents in the first month and Member Defense couldn't respond fast enough. Two of the tenants ended up worse off than if they hadn't participated.\n\n"
            "I'm not against the campaign. I'm against launching the campaign with protocols we can't operationalize. Dana, can you speak to current Member Defense capacity for retaliation response under these protocols?"),
    Comment('P-C-04', 'coalition_hector', 'extension 2 hour 4',
            "Renée, your concern is the right concern. The protocols we worked out in extension 1 assume Member Defense capacity that we haven't audited. I'm going to defer to Dana's assessment of current capacity and whether the proposal needs to wait until capacity is built or whether we proceed with the protocols and accept that we'll be capacity-stretched during the campaign.\n\n"
            "What I'll say from my end: deferring the campaign isn't free either. Riverside Properties continues current practices during any delay. Tenants currently in eviction proceedings don't get the support a public campaign would generate."),
    Comment('P-C-04', 'coalition_dana', 'extension 2 hour 6',  # capacity assessment
            "Capacity assessment for the Riverside Properties campaign under the extension 1 protocols:\n\n"
            "We currently have eleven trained Member Defense volunteers. Average ongoing case load: 14 cases at any given time. Campaign-driven case influx estimate, based on similar campaigns in other cities: 6-12 new cases per month for the first three months, then declining.\n\n"
            "Current capacity can absorb 4-6 additional cases/month before delays start. Above that, response time degrades and our follow-through rate drops.\n\n"
            "Three options: (1) delay the campaign until P-C-06 passes and we build capacity to ~16 defenders; (2) launch the campaign and accept degraded response during the first three months; (3) launch with explicit campaign-period prioritization (Riverside cases get capacity first, other cases see longer response times during the campaign window).\n\n"
            "I'm not sure which is right. The Member Defense working group has discussed all three; reasonable members support each."),
    Comment('P-C-04', 'coalition_maya', 'extension 2 hour 8',
            "Renée's concern about Member Defense capacity is the right concern. The protocols I drafted assume capacity that we should audit before committing. Dana's three-option framing is the right structure for thinking about this."),
    Comment('P-C-04', 'coalition_will', 'extension 2 hour 12',
            "Renée's concern is the operationalization issue. The protocols specify what should happen; the capacity to enforce them is a separate question. I think we should pass the proposal with the protocols and treat the capacity audit as the next deliverable, not pre-pass."),
    Comment('P-C-04', 'coalition_marcus', 'extension 2 hour 14',
            "Dana's capacity assessment is the right structure. The proposal should pass with the protocols specified and the capacity build-out as a stated condition."),
    Comment('P-C-04', 'coalition_priya', 'extension 2 hour 18',
            "Voted yes. The protocols and the capacity assessment together address the substantive concerns."),
    Comment('P-C-04', 'coalition_jay', 'extension 2 hour 20',
            "Voting yes during extension 2. The deliberation process did the work it was supposed to do."),
    # Late-engagement destabilization #3 — comes from non-quick-login cluster, represented by a single comment from Renée
    Comment('P-C-04', 'coalition_renee', 'extension 2 hour 22',
            "Coming back to this one more time. Dana's option (1) — delay until P-C-06 passes and we build capacity to 16 defenders — is the option I'd vote for. The other two accept that some tenants get worse outcomes during the campaign's first months. I don't think that's acceptable when delay produces a better outcome for those tenants."),
    Comment('P-C-04', 'coalition_will', 'extension 3 hour 4',
            "I keep wondering why we don't just call the vote — the protocols are stable, the capacity question is real but won't be resolved through more extensions."),
    Comment('P-C-04', 'coalition_hector', 'extension 3 hour 6',
            "I want to engage with the late-engagement concerns because they're surfacing real tradeoffs, but I want to flag that we've now been in extension territory for three cycles, and the substance keeps moving in directions that suggest we should pass with the current protocols and address the new concerns through subsequent proposals rather than continuing to amend this one.\n\n"
            "The protocols are stronger than they were at proposal opening. The amendment process has worked. At some point we either pass or we don't, and indefinite extension serves neither side of the tactical disagreement.\n\n"
            "I'm voting yes on the current language. If the force-close brings us there before stability re-confirms, that's a process outcome I can accept."),
    Comment('P-C-04', 'coalition_hector', 'post-close',
            "Will, the protocol language you've drafted into P-C-11 is the right formalization. Voted yes."),

    # P-C-05
    Comment('P-C-05', 'coalition_maya', 'deliberation hour 4',
            "Right to counsel is the most consequential tenant infrastructure win the Coalition has had. Voted yes."),
    Comment('P-C-05', 'coalition_marcus', 'deliberation hour 8',
            "The lobbying strategy question is the substantive one; the proposal directs the working group to develop it, which is right."),

    # P-C-06 (deliberation at reset; key Dana cross-org comment and supporting comments visible)
    Comment('P-C-06', 'coalition_dana', 'deliberation hour 6',  # CROSS-ORG INTERSECTION #3
            "In the Local I steward in, we tried to formalize steward training without a budget line item. The training happened sporadically and unevenly, depending on which steward had bandwidth to organize it that quarter. Formalizing the budget — the Local approved a $3K annual training authorization in 2024 — made the training reliable. Same skill set teaching steward and defender work; same structural issue when the work isn't budgeted.\n\n"
            "The principle: capacity that depends on volunteer enthusiasm is capacity that fluctuates with volunteer enthusiasm. Capacity that's budgeted is reliable."),
    Comment('P-C-06', 'coalition_will', 'deliberation hour 8',
            "Dana's capacity assessment during P-C-04 was the visible case for this proposal. Voting yes."),
    Comment('P-C-06', 'coalition_marcus', 'deliberation hour 12',
            "Dana's analogy to the Local's steward training experience is structurally apt. Voting yes."),
    Comment('P-C-06', 'coalition_hector', 'deliberation hour 20',
            "Dana's proposal addresses the capacity question that surfaced during P-C-04's extensions. Voted yes."),
    Comment('P-C-06', 'coalition_priya', 'deliberation hour 24',
            "Dana's cross-org reference to the Local's steward training is the right kind of structural argument — formalize the budget, the work becomes reliable."),
    Comment('P-C-06', 'coalition_renee', 'deliberation hour 24',
            "The capacity gap I flagged during P-C-04 is the case for this proposal. Voted yes."),
    Comment('P-C-06', 'coalition_maya', 'deliberation hour 30',
            "Dana's proposal is sharper than I expected. The Member Defense capacity issue surfaced visibly during P-C-04's extensions; formalizing the budget line addresses it. Voting yes."),
    Comment('P-C-06', 'coalition_dana', 'deliberation hour 36',
            "The suggestion of starting smaller and scaling has merit, but the $8K figure is already calibrated to current case volume rather than aspirational expansion. A smaller pilot would mean we're under-resourcing the work we're already doing. Voting yes on the proposed amount."),

    # P-C-07
    Comment('P-C-07', 'coalition_hector', 'deliberation hour 6',
            "Solidarity statements aren't strategy; they're relational infrastructure. The Cuyahoga organizers will be relational infrastructure for us when we need them."),

    # P-C-08
    Comment('P-C-08', 'coalition_maya', 'deliberation hour 2',
            "The ad hoc cadence has produced predictable gaps. Member input on the right alternative."),
    Comment('P-C-08', 'coalition_priya', 'voting hour 6',
            "Quarterly minimum with bandwidth-permitting monthly is the right structure."),

    # P-C-09
    Comment('P-C-09', 'coalition_maya', 'deliberation hour 4',
            "The Riverside outreach component is the most time-sensitive; the upzoning conversation will surface housing questions for tenants in the affected buildings regardless of how P-C-01 resolves."),
    Comment('P-C-09', 'coalition_priya', 'deliberation hour 8',
            "The Riverside outreach component is the most time-sensitive. Voted yes."),

    # P-C-10
    Comment('P-C-10', 'coalition_hector', 'deliberation hour 4',
            "Joaquin Reyes trained the Charlotte coalition through their successful 2023 rent stabilization campaign. The training is foundational; the cost is low."),

    # P-C-11
    Comment('P-C-11', 'coalition_will', 'deliberation hour 1',
            "Proposing formalization of the protocols that came out of P-C-04. Substantive work was Maya's drafting and Hector's open response; this is closing the loop so future campaigns don't rediscover them."),
    Comment('P-C-11', 'coalition_will', 'voting hour 2',
            "Voted yes on my own proposal. The substantive work was the P-C-04 deliberation; this is the formalization."),
    Comment('P-C-11', 'coalition_dana', 'voting hour 4',
            "Will's protocols address everything Member Defense flagged during P-C-04. Voted yes."),
    Comment('P-C-11', 'coalition_maya', 'voting hour 4',
            "Voted yes. Will's protocol formalization is the right way to capture what we worked out during P-C-04's extensions."),
]


# -----------------------------------------------------------------------------
# Notification Feeds (at reset moment)
# -----------------------------------------------------------------------------

NOTIFICATION_FEEDS = [
    NotificationFeed(
        member_user_id='coalition_priya',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-01',
                              note='Halfway-deadline reminder firing for several of her delegators on Land Use Policy who haven\'t yet voted.'),
            NotificationEvent('delegator_rationale',
                              related_proposal_id='P-C-01',
                              note='A non-quick-login delegator on Land Use Policy posted a vote rationale supporting Priya\'s position with caveats.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-03',
                              note='Halfway-deadline reminder on Coordinating Committee Election (Priya is incumbent running).'),
            NotificationEvent('new_comments',
                              related_proposal_id='P-C-06',
                              note='New comments accumulating on Member Defense budget proposal she\'s following but not central to.'),
        ],
    ),
    NotificationFeed(
        member_user_id='coalition_hector',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-01',
                              note='Halfway-deadline reminder for several delegators on Direct Action / Anti-Displacement who haven\'t yet voted.'),
            NotificationEvent('delegator_rationale',
                              related_proposal_id='P-C-04',
                              note='A delegator on Direct Action posted a vote rationale referencing the doxing-protocol amendments approvingly.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-03',
                              note='Halfway-deadline reminder on Coordinating Committee Election.'),
            NotificationEvent('new_follow',
                              note='A new follow on his Anti-Displacement delegate page.'),
        ],
    ),
    NotificationFeed(
        member_user_id='coalition_marcus',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-01',
                              note='Halfway-deadline reminder for several of his Land Use Policy delegators who haven\'t voted.'),
            NotificationEvent('delegator_rationale',
                              related_proposal_id='P-C-01',
                              note='A non-quick-login delegator on Land Use Policy posted a vote rationale explicitly saying their delegation to Marcus is "earning out" because of his nuanced position statement.'),
        ],
    ),
    NotificationFeed(
        member_user_id='coalition_maya',
        events=[
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-01',
                              note='Halfway-deadline reminder for delegators on Tenant Protections.'),
            NotificationEvent('delegator_vote_change',
                              related_proposal_id='P-C-01',
                              note='One of her delegators on Tenant Protections changed their vote on P-C-01 from no to abstain — wavering delegator signal.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-03',
                              note='Halfway-deadline reminder on Coordinating Committee Election (Maya is incumbent running).'),
            NotificationEvent('new_follow',
                              note='A new follow on her Public Housing delegate page.'),
        ],
    ),
    NotificationFeed(
        member_user_id='coalition_dana',
        events=[
            NotificationEvent('author_comment',
                              related_proposal_id='P-C-06',
                              note='A new comment from a non-quick-login member arguing for a larger line item — author-comment event on her own proposal in deliberation.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-01',
                              note='Halfway-deadline reminder for delegators on Member Defense.'),
        ],
    ),
    NotificationFeed(
        member_user_id='coalition_will',
        events=[
            NotificationEvent('follower_feedback',
                              note='A non-quick-login member with approved follow on his draft Tenant Tech Issues page posted feedback on the draft — follower-feedback event on the private_delegators surface.'),
            NotificationEvent('halfway_deadline',
                              related_proposal_id='P-C-01',
                              note='Halfway-deadline reminder (he hasn\'t voted yet).'),
        ],
    ),
]


# -----------------------------------------------------------------------------
# OrgBible assembly
# -----------------------------------------------------------------------------

DELEGATE_PAGES = DELEGATE_PAGES_PART_1 + DELEGATE_PAGES_PART_2

COALITION_BIBLE = OrgBible(
    slug='westgate-tenants',
    display_name='Westgate Tenants Coalition',
    charter=CHARTER,
    tone_notes=TONE_NOTES,
    recent_history=RECENT_HISTORY,
    sub_orgs=['Policy', 'Outreach', 'Direct Action', 'Member Defense'],
    voting_methods_used=['binary', 'approval', 'rcv', 'stv'],
    approval_tie_resolution='expand_winners',
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
PHASE 23 INTEGRATION NOTES — COALITION BIBLE:

1. User ID convention:
   - Coalition users prefixed with `coalition_` for clarity.
   - Marcus Pham: `coalition_marcus` here, `hoa_marcus` in hoa_bible.
   - Dana Whitfield: `coalition_dana` here, `local_dana` in union_bible.
   - Technical agent maps each cross-org pair to a single underlying user account
     for org-switching with different per-org delegate identity content.

2. SRR force-close exemplar — P-C-04:
   - This is the SRR force-close showcase. Load-bearing for the demo.
   - state_at_reset: 'passed, 5 days ago (62-38, after SRR force-close)'.
   - Trajectory waypoints + events in trajectory_waypoints.py under P_C_04.
   - Comment thread spans deliberation hour 1 through extension 3 hour 6 with
     post-close follow-up. Three destabilization events from comment activity:
       * Will's voting hour 38 (doxing concern)
       * Renée's voting hour 92 (capacity concern)
       * Late-engagement cluster at ~hour 114 (represented by Renée's extension 2 hour 22)
     Each destabilization triggered an extension grant; budget exhausted after
     extension 3; force-close fired at extension 3 end.

3. Private_delegators showcase — Will Sutherland:
   - Will's delegate page has page_visibility='private_delegators'.
   - Page is visible only to approved followers (a small allowlist managed by Will).
   - External viewers (and Coalition members who aren't on the allowlist) get 404.
   - Technical agent should seed a follower list of ~3-5 non-quick-login members
     who have approved access.

4. Cross-org intersection #3 (Dana labor-tenant solidarity):
   - Dana's P-C-06 deliberation hour 6 comment explicitly references the Local's
     steward training experience and the P-L-10 training authorization that
     formalized it. The Local's `union_bible.py` contains the matching P-L-10
     proposal and Dana's P-L-03 cross-org tenant-impact comment (from Stage 6.5).
   - The two comments together complete the bidirectional cross-org showcase.

5. STV election (P-C-03):
   - Six candidates: Priya, Maya (incumbents), plus four non-quick-login
     candidates: Jordan Park, Elena Vasquez (YIMBY-leaning), Sandra Brooks,
     David Onyeka (anti-development-leaning).
   - Technical agent should seed the four non-quick-login candidates with
     brief candidate statements if Sankey visualization requires them.
   - Third-seat contention between Jordan Park and Sandra Brooks reflects the
     YIMBY/anti-development split. Per trajectory_waypoints.py P_C_03, the
     cascade should display this contention through transfer patterns.

6. Renée Castille and Jay Okonkwo (non-quick-login load-bearing):
   - Renée's hour-92 capacity concern on P-C-04 is the SRR destabilization #2;
     her hour-22 extension 2 comment is the late-engagement destabilization #3
     proxy.
   - Jay's hour-36 mind-change comment on P-C-01 demonstrates real-time
     deliberation impact; his hour-40 P-C-02 precedent comment is the trigger
     for Priya's hour-60 partial concession.
   - Both should be seeded as full user accounts with vote history and these
     specific comments. Their content is in the COMMENTS list above.

7. Approval tie resolution:
   - Coalition uses `expand_winners` for approval tie resolution (different from
     HOA and Local's `broader_approval_base`).
   - This is a deliberate choice per the bible — the Coalition's working-group
     culture favors inclusive resolution over narrow-pickwise tie breaks.

8. Trajectory data lives in `trajectory_waypoints.py`:
   - This file references proposals by ID; trajectory module has the
     corresponding waypoint and event data for chart rendering.

9. The activist_bible.py module is composed of three parts:
   - activist_bible_part1.py: imports, charter, members, first 3 delegate pages
   - activist_bible_part2.py: remaining 3 delegate pages, proposals, drafts
   - activist_bible_part3.py: comments, notification feeds, OrgBible assembly
   The technical agent can concatenate into a single activist_bible.py or
   import COALITION_BIBLE from part 3 (which imports from parts 1 and 2).
"""
