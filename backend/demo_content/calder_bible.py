"""Phase 90f — Calder Tool & Machine Works: the weighted-governance demo org.

A 14-person employee-owned precision machine shop, the fourth demo org and the
only weighted one. Its job is to make every corporate-governance feature (88
weighted voting, 90a distribution rules, 90b transfers, 90c per-proposal count
mode, 90d issuance ladder + cap, 90e vote-gated issuance) visible within a couple
of minutes of quick-login browsing.

Structure, characters, weights, and which feature each artifact showcases are
fixed here. Prose (proposal bodies, comments, rationales, position statements)
is written to be functional and in-voice; a content pass may enrich it further,
against the tone notes: plainspoken shop-floor pragmatism, people who measure in
thousandths and argue in dollars, low-drama disagreements, no corporate-speak,
no em dashes, no phase numbers.
"""
from demo_content.schema import (
    OrgBible, Member, TitleSeed, DistributionRuleSeed, ShareEventSeed,
    Proposal, Comment, DelegatePage, TopicVisibility, PositionStatement,
    VoteRationale, FollowSeed, PersonaDelegationSpec,
)


# ---------------------------------------------------------------------------
# Members (14). Weights are canon. ~7,900 of 10,000 shares outstanding.
# ---------------------------------------------------------------------------
MEMBERS = [
    Member("cal_walt", "Walt Calder", quick_login=True, role="Founder (semi-retired)",
           platform_role="member", voting_weight=3000, share_tenure_years=34,
           notification_preset="low"),
    Member("cal_dena", "Dena Okafor", quick_login=True, role="General Manager",
           platform_role="steward", voting_weight=620, share_tenure_years=15,
           notification_preset="high"),
    Member("cal_marcus", "Marcus Reyes", quick_login=True, role="Lead machinist",
           platform_role="member", voting_weight=540, share_tenure_years=20,
           notification_preset="medium"),
    Member("cal_priya", "Priya Raman", quick_login=True, role="Outside investor",
           platform_role="member", voting_weight=1500, share_tenure_years=3,
           notification_preset="medium"),
    Member("cal_tom", "Tom Brzezinski", quick_login=True, role="Machinist",
           platform_role="member", voting_weight=310, share_tenure_years=9,
           notification_preset="medium"),
    Member("cal_jess", "Jess Whitfield", quick_login=True, role="Apprentice (2nd year)",
           platform_role="member", voting_weight=10, share_tenure_years=1.5,
           notification_preset="high"),
    Member("cal_ruth", "Ruth Calder-Nguyen", quick_login=False, role="Office manager",
           platform_role="admin", voting_weight=380, share_tenure_years=12,
           notification_preset="medium"),
    Member("cal_hank", "Hank Dvorak", quick_login=False, role="Retired machinist",
           platform_role="member", voting_weight=460, share_tenure_years=28,
           notification_preset="low"),
    Member("cal_omar", "Omar Haddad", quick_login=False, role="Machinist / programmer",
           platform_role="member", voting_weight=265, share_tenure_years=7,
           notification_preset="medium"),
    Member("cal_sue", "Sue Pelletier", quick_login=False, role="Quality / CMM tech",
           platform_role="moderator", voting_weight=290, share_tenure_years=8,
           notification_preset="medium"),
    Member("cal_gary", "Gary Lindqvist", quick_login=False, role="Maintenance",
           platform_role="member", voting_weight=240, share_tenure_years=6,
           notification_preset="low"),
    Member("cal_kat", "Kat Moreno", quick_login=False, role="Machinist",
           platform_role="member", voting_weight=205, share_tenure_years=4,
           notification_preset="medium"),
    Member("cal_dev", "Dev Patel", quick_login=False, role="Apprentice (1st year)",
           platform_role="member", voting_weight=0, share_tenure_years=0.6,
           notification_preset="high"),
    Member("cal_lorna", "Lorna Fitch", quick_login=False, role="Part-time bookkeeper",
           platform_role="member", voting_weight=80, share_tenure_years=2,
           notification_preset="low"),
]


# ---------------------------------------------------------------------------
# Titles. Employee is multi-holder (one TitleSeed per holder — the seed loop
# upserts the title row and appends an assignment per entry).
# ---------------------------------------------------------------------------
_EMPLOYEES = ["cal_marcus", "cal_tom", "cal_ruth", "cal_omar", "cal_sue",
              "cal_gary", "cal_kat", "cal_lorna"]

TITLES = [
    TitleSeed("General Manager", bound_role="admin", cardinality_mode="single",
              fill_method="assigned", holder_user_id="cal_dena", display_order=0),
    TitleSeed("Founder", cardinality_mode="single", fill_method="assigned",
              holder_user_id="cal_walt", display_order=1),
    TitleSeed("Investor", cardinality_mode="single", fill_method="assigned",
              holder_user_id="cal_priya", display_order=2),
]
TITLES += [
    TitleSeed("Employee", cardinality_mode="multi", fill_method="assigned",
              holder_user_id=uid, display_order=3)
    for uid in _EMPLOYEES
]
TITLES += [
    TitleSeed("Apprentice", cardinality_mode="multi", fill_method="assigned",
              holder_user_id=uid, display_order=4)
    for uid in ("cal_jess", "cal_dev")
]
TITLES += [
    TitleSeed("Retired", cardinality_mode="multi", fill_method="assigned",
              holder_user_id="cal_hank", display_order=5),
    # Shop Committee — elected, two seats already held (Marcus + Sue).
    TitleSeed("Shop Committee", cardinality_mode="multi", fill_method="elected",
              holder_user_id="cal_marcus", display_order=6),
    TitleSeed("Shop Committee", cardinality_mode="multi", fill_method="elected",
              holder_user_id="cal_sue", display_order=6),
]


# ---------------------------------------------------------------------------
# Distribution rules. Anchors positioned so nothing fires during a demo day.
# ---------------------------------------------------------------------------
DISTRIBUTION_RULES = [
    # 1 — Tenure accrual: each employee accrues on their own share anniversary.
    DistributionRuleSeed(amount=25, interval_months=12, schedule_mode="anniversary",
                         targeting_mode="titles_include", title_names=["Employee"]),
    # 2 — Apprentice vesting: fixed cadence, next occurrence ~40 days out.
    DistributionRuleSeed(amount=5, interval_months=6, schedule_mode="fixed_cadence",
                         targeting_mode="titles_include", title_names=["Apprentice"],
                         anchor_offset_days=40),
]


# ---------------------------------------------------------------------------
# Backdated ledger (last 30 days). Balances reconcile with final weights.
# ---------------------------------------------------------------------------
LEDGER_SEED = [
    # Dena corrected Lorna's balance before the org moved to member-vote mode.
    ShareEventSeed("admin_set", delta=15, days_ago=28, user_id="cal_lorna",
                   actor_user_id="cal_dena", resulting_balance=55),
    # Recent tenure-accrual grants (rule 1) on three employees' anniversaries.
    ShareEventSeed("auto_distribution", delta=25, days_ago=6, user_id="cal_omar",
                   resulting_balance=265, rule_index=0, authorization_ref_kind="rule"),
    ShareEventSeed("auto_distribution", delta=25, days_ago=5, user_id="cal_gary",
                   resulting_balance=240, rule_index=0, authorization_ref_kind="rule"),
    ShareEventSeed("auto_distribution", delta=25, days_ago=4, user_id="cal_lorna",
                   resulting_balance=80, rule_index=0, authorization_ref_kind="rule"),
    # Hank sold Kat some of his shares; they handled it themselves.
    ShareEventSeed("transfer", delta=40, days_ago=12, from_user_id="cal_hank",
                   to_user_id="cal_kat", actor_user_id="cal_hank",
                   resulting_balance=205, from_resulting_balance=460),
]


# ---------------------------------------------------------------------------
# Proposals. (The FY-reserve budget proposal from the spec is deferred: the demo
# seed pipeline has no budget plumbing, and adding it is out of proportion to
# this stage. The corporate-governance showcases 90c/90d/90e + weighted RCV are
# all present below.)
# ---------------------------------------------------------------------------
PROPOSALS = [
    # 1 — weighted binary, PASSED. The dividend split.
    Proposal(
        "cal_prop_dividend", "FY26 surplus: 60 percent distribution, 40 percent reserve",
        "cal_dena", "binary", "passed, 10 days ago",
        "We closed FY26 in the black, first real surplus in three years, and it "
        "was not luck. It was aerospace work we chased hard and delivered on time. "
        "This splits the surplus 60/40: sixty percent paid out to shareholders on "
        "their holdings, forty percent into the equipment reserve so the grinder "
        "rebuild does not come out of next year's payroll. It rewards the people "
        "who own this place and still leaves us money to buy iron. A good year "
        "should feel like one on the paycheck and still leave the shop stronger "
        "than it found us.",
        topics=["Finances"],
    ),
    # 2 — ISSUANCE proposal (cap raise), OPEN. Dilution preview + vote-gated 90e.
    Proposal(
        "cal_prop_cap_raise", "Authorize shares for the second-shift financing",
        "cal_dena", "binary", "voting, day 3 of 7",
        "The second-shift plan needs financing, and the bank will not lend against "
        "it unless we have room on the books to issue shares. Right now we are "
        "capped at 10,000 authorized. This raises that ceiling to 12,000. Read it "
        "plainly: it does not issue anyone a single new share today, and nobody's "
        "balance moves when it passes. It only raises the roof so the company can "
        "issue later, and only if the expansion actually goes forward. Here is the "
        "honest part. If we do issue against that new room someday, the pie gets cut "
        "into more slices, and every existing slice, mine and Walt's included, gets "
        "a little thinner. That is dilution, and it is why this is a vote of the "
        "owners and not a form I sign in the office. Weigh it and vote it.",
        topics=["Finances"],
        issuance_payload={"action": "cap_raise", "params": {"authorized_total": 12000}},
    ),
    # 3 — approval, ONE MEMBER ONE VOTE (90c), OPEN. The picnic.
    Proposal(
        "cal_prop_picnic", "Where should we hold the summer shop picnic",
        "cal_sue", "approval", "voting, day 2 of 5",
        "Time to pick a spot for the summer picnic, families welcome as always. "
        "One thing up front: this one is counted one member, one vote. Walt's three "
        "thousand shares and Dev's zero weigh exactly the same here, because shares "
        "do not buy you a better bratwurst. Approve any spots you would be happy "
        "with and we will take the most-liked one.",
        options=["Calder's lake lot", "Riverside Park pavilion", "The brewery taproom",
                 "Shop parking lot cookout"],
        topics=["Culture"],
        count_mode="one_per_member",
    ),
    # 5 — weighted RCV, PASSED. Health plan.
    Proposal(
        "cal_prop_health", "Rank the three health plan options for next year",
        "cal_ruth", "rcv", "passed, 45 days ago",
        "Renewal season. Our broker brought three plans and they are genuinely "
        "different animals, so rank them in the order you prefer instead of picking "
        "just one. The plan that wins becomes ours for next year. Look hard at the "
        "deductible and whether your doctor is still in network before you rank, "
        "because that is where these three split apart. Full numbers on premiums, "
        "deductibles, and networks are in the packet Ruth emailed around.",
        options=["Plan A: higher premium, low deductible",
                 "Plan B: balanced, current network",
                 "Plan C: HSA-eligible, high deductible"],
        topics=["Benefits"],
    ),
    # 6 — weighted binary, IN DELIBERATION. Second shift (ties to prop 2).
    Proposal(
        "cal_prop_second_shift", "Add a second shift starting Q4",
        "cal_dena", "binary", "deliberation",
        "The backlog is past what one shift can hold. We are quoting eight weeks out "
        "on work we used to turn in three, and we have started saying no to jobs we "
        "want. This is the proposal to add a second shift starting in Q4: five more "
        "programmers and machinists, a staggered start so the day crew trains them "
        "on our fixtures, and a real maintenance window carved out overnight so we "
        "are not running the spindles into the ground. The financing question rides "
        "right alongside it, since the bodies and the iron both cost money. Argue it "
        "out here, hard, before it goes to a vote. If it cannot survive this thread "
        "it does not deserve the floor.",
        topics=["Shop operations", "Finances"],
    ),
]

DRAFTS = [
    Proposal(
        "cal_draft_apprentice_conversion",
        "Formalize apprentice to employee share conversion at journeyman",
        "cal_dena", "binary", "draft",
        "Draft: when an apprentice tests out to journeyman, they convert to the "
        "Employee class and start accruing on the tenure rule from their conversion "
        "date, same as everybody else earned it. Right now we do this on a handshake "
        "and a nod, which was fine when it was Marcus deciding, but it should not "
        "hang on any one person remembering to be fair. This writes it down so the "
        "next apprentice knows exactly what journeyman gets them. Still working the "
        "starting-share numbers with Ruth before it goes up.",
        topics=["Benefits", "Shop operations"],
    ),
]


# ---------------------------------------------------------------------------
# Comments (the live debate). Concise + in-voice.
# ---------------------------------------------------------------------------
COMMENTS = [
    Comment("cal_prop_dividend", "cal_priya", "voting hour 6",
            "For. A shop that pays its owners is a shop people stay at, and turnover "
            "on a floor like this costs more than any dividend. Forty percent into "
            "the reserve still covers the grinder rebuild with room to spare. Pay "
            "out and keep your people."),
    Comment("cal_prop_dividend", "cal_walt", "voting hour 20",
            "For. We spent three lean years clawing this back from nothing, most of "
            "us taking short paychecks to do it. The books finally say yes. Pay the "
            "people who stayed."),
    Comment("cal_prop_dividend", "cal_tom", "voting hour 30",
            "Against, and I will say why so nobody thinks I am being sour. Sixty "
            "percent out the door is a good year talking, and good years do not send "
            "us a schedule. The five-axis we actually need runs north of two hundred "
            "grand, and I would rather carry the reserve heavier now than finance "
            "that machine at the bank's rate later. Pay out, but pay out less."),
    Comment("cal_prop_cap_raise", "cal_priya", "voting hour 10",
            "Strongly for. You cannot finance an expansion against a ceiling you set "
            "back when this place was half its size. I have sat on the other side of "
            "these tables, and no bank writes the check until the headroom is there "
            "on paper. Raising the authorization is not issuing shares and it is not "
            "diluting anyone today. It is leaving the door open so we can walk "
            "through it when the shift is ready."),
    Comment("cal_prop_cap_raise", "cal_hank", "voting hour 18",
            "Skeptical, and I have earned the right to be. Twenty-eight years I bled "
            "for these shares, and every one you authorize is one that can water mine "
            "down later. I am not against the second shift. I might even vote for it. "
            "But show me the actual financing, the rate, the terms, the payback, "
            "before you ask me to make room for shares nobody has priced yet. Order "
            "matters."),
    Comment("cal_prop_cap_raise", "cal_jess", "voting hour 26",
            "Honest question from the apprentice bench, and sorry if it is a dumb "
            "one. I hold ten shares. When you all talk about the cap and dilution, "
            "what does raising it from ten to twelve thousand actually do to those "
            "of us who barely hold anything yet? Am I losing something I do not even "
            "understand I have?"),
    Comment("cal_prop_cap_raise", "cal_marcus", "voting hour 30",
            "Not a dumb question at all, Jess, it is the right one. Raising the cap "
            "does nothing to your ten shares today. You still own ten, and your vote "
            "here counts the same as anyone's. All it does is let the company issue "
            "more shares later. If it does that, the whole pie gets cut into more "
            "pieces, so everyone's slice gets a hair smaller, mine and Walt's right "
            "along with yours. Nobody is singling out the apprentices. And here is "
            "the flip side worth knowing: those new shares are what fund the shift "
            "that gives you a journeyman spot to grow into. That trade is exactly "
            "why this is a vote of the owners and not a form Dena signs in the "
            "office. You get a real say. Use it."),
    Comment("cal_prop_picnic", "cal_walt", "voting hour 8",
            "The lake lot has real shade, a dock the kids love, and I own it, so it "
            "costs the shop nothing. That is my pitch and I will leave it there. My "
            "three thousand shares do not buy a better bratwurst than Dev's zero on "
            "this one, one vote each, and that is how it ought to be. Pick what you "
            "like."),
    Comment("cal_prop_second_shift", "cal_marcus", "deliberation hour 20",
            "If we do this, the overnight maintenance window is the whole game, and "
            "I mean that. Run the spindles sixteen hours a day with no honest service "
            "gap and we will eat bearings and ways inside a year, and a rebuilt "
            "spindle costs more than the shift saves. I want maintenance blocked out "
            "on the schedule in ink, not penciled in as whenever-we-can, before I "
            "vote yes."),
    Comment("cal_prop_second_shift", "cal_tom", "deliberation hour 40",
            "And I want to know where the five bodies come from. Good machinists are "
            "not sitting at the union hall waiting on us, and we are already short a "
            "programmer on days. Five more, trained on our fixtures, is a year of "
            "work by itself. Add the iron and the overnight crew and this ties "
            "straight to the financing vote. You cannot argue one without the "
            "other."),
]


# ---------------------------------------------------------------------------
# Delegate pages (drive the seeded votes via vote_rationales).
# ---------------------------------------------------------------------------
DELEGATE_PAGES = [
    DelegatePage(
        "cal_marcus", intro=(
            "Twenty years on these machines, most of them right here. I chair the "
            "shop committee, and the way I see delegation is simple: I try to vote "
            "the way the floor would if every one of us had time to sit down and "
            "read every packet cover to cover. Most of you do not, and that is fine, "
            "that is what the day job is for. If you follow me, that is the whole "
            "deal. I do the homework so your shares still get a considered vote."),
        topics=[TopicVisibility("Equipment", "public_accepting"),
                TopicVisibility("Shop operations", "public_accepting"),
                TopicVisibility("Finances", "public")],
        position_statements=[
            PositionStatement("Equipment", "Buy quality iron once and maintain it "
                              "religiously. A machine you baby for twenty years is cheaper than "
                              "two you run into the ground. I will never vote to skip a service "
                              "window to squeeze out a few more parts."),
            PositionStatement("Finances", "Pay the owners, they earned it. But never let the "
                              "reserve get so thin that a broken spindle turns into a bank loan. "
                              "Generous and solvent are not enemies if you plan for both."),
        ],
        vote_rationales=[
            VoteRationale("cal_prop_dividend", "yes",
                          "Sixty forty is a fair split in a year this good. Reserve still covers "
                          "the grinder. Pay the people."),
            VoteRationale("cal_prop_cap_raise", "yes",
                          "Some future dilution is a fair price for the room to grow. I have read "
                          "the shift plan and I trust it. Yes."),
            VoteRationale("cal_prop_health", "rcv_2_1_3",
                          "Plan B first: it keeps the network the guys already use and the premium "
                          "is livable. Plan A second, C third."),
        ],
    ),
    DelegatePage(
        "cal_dena", intro=(
            "General manager, fifteen years. I am the one who runs the numbers and "
            "brings the hard proposals to the floor, which means I am also the one "
            "who catches heat when they are unpopular. Fine, that is the job. When "
            "you follow me you are getting a vote that puts the shop staying solvent "
            "first and the people getting paid a very close second. Those two only "
            "conflict a few times a year, and when they do I will tell you plainly "
            "which way I went and why."),
        topics=[TopicVisibility("Finances", "public"),
                TopicVisibility("Shop operations", "public"),
                TopicVisibility("Benefits", "public")],
        position_statements=[
            PositionStatement("Finances", "Solvency first, then generosity, in that order "
                              "every time. A shop that misses payroll once cannot reward anyone "
                              "twice. Keep enough dry powder that a bad quarter is an "
                              "inconvenience, not a crisis."),
            PositionStatement("Benefits", "Good benefits are cheaper than replacing the people "
                              "who leave for them. Keep the plan folks actually use, not the one "
                              "that looks cheapest on my spreadsheet."),
        ],
        vote_rationales=[
            VoteRationale("cal_prop_dividend", "yes",
                          "The books can carry it and the people earned it. I checked twice. Yes."),
            VoteRationale("cal_prop_cap_raise", "yes",
                          "The bank will not lend without the headroom, and the shift dies without "
                          "the loan. This is the responsible move even if it is not the comfortable "
                          "one."),
            VoteRationale("cal_prop_health", "rcv_2_3_1",
                          "Plan B first for continuity, nobody has to change doctors. Plan C second "
                          "for the folks who want to save into an HSA."),
        ],
    ),
    DelegatePage(
        "cal_walt", page_visibility="followers_only", intro=(
            "I started this shop in a two-bay garage in 1992 with one manual lathe "
            "and a line of credit I should not have gotten. Eight years back I sold "
            "the majority to the people who actually run it, which was the best "
            "decision I ever made. I come in Tuesdays, drink the bad coffee, and "
            "kibitz. I still hold the biggest single block of shares, and I try hard "
            "to use it lightly. The floor knows this place better than I do now, and "
            "my job is to stay out of the way more than I get in it."),
        topics=[TopicVisibility("Finances", "followers_only"),
                TopicVisibility("Culture", "followers_only")],
        vote_rationales=[
            VoteRationale("cal_prop_dividend", "yes",
                          "Pay the people. We built this back together and they should feel it in "
                          "the paycheck."),
            VoteRationale("cal_prop_picnic", "approval_1",
                          "The lake lot. Shade, a dock, and it costs the shop nothing since I own "
                          "it."),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Additional direct-voter rationales (votes only; no public delegate page).
# Attached via lightweight delegate pages that are effectively private.
# ---------------------------------------------------------------------------
DELEGATE_PAGES += [
    DelegatePage("cal_priya", intro="Outside investor. I put capital in during the 2023 "
                 "expansion because I liked what I saw on the floor, not to run it. I "
                 "vote the finances myself, where I actually know something, and defer "
                 "to Walt on how the shop runs day to day, where he knows more than I "
                 "ever will.",
                 topics=[TopicVisibility("Finances", "private")],
                 vote_rationales=[
                     VoteRationale("cal_prop_dividend", "yes",
                                   "Owners should be paid when the shop earns it. It earned it."),
                     VoteRationale("cal_prop_cap_raise", "yes",
                                   "You cannot finance growth against a ceiling you set three years and "
                                   "a lot of revenue ago."),
                     VoteRationale("cal_prop_picnic", "approval_2_3",
                                   "Riverside or the taproom, either works for me. I will bring the good "
                                   "beer."),
                 ]),
    DelegatePage("cal_tom", intro="Machinist, nine years. I want the five-axis in this "
                 "building more than I want just about anything, and the only way we "
                 "buy it without a loan is a reserve I guard like a hawk. That is my "
                 "whole politics around here: save now so we own our tools free and "
                 "clear later.",
                 topics=[TopicVisibility("Equipment", "private")],
                 vote_rationales=[
                     VoteRationale("cal_prop_dividend", "no",
                                   "Too much out the door in one year. Carry the reserve heavier and "
                                   "put us closer to that five-axis."),
                     VoteRationale("cal_prop_health", "rcv_3_2_1",
                                   "Plan C first. The HSA lets me sock away pretax and I am healthy "
                                   "enough to bet on it."),
                     VoteRationale("cal_prop_picnic", "approval_4",
                                   "Parking lot cookout. We have got the space, the grills, and it costs "
                                   "nobody a dime."),
                 ]),
    DelegatePage("cal_hank", intro="Retired off the floor after twenty-eight years, "
                 "kept every share I earned. I still read the finance proposals close, "
                 "because it is my nest egg now, not just a paycheck.",
                 topics=[TopicVisibility("Finances", "private")],
                 vote_rationales=[
                     VoteRationale("cal_prop_dividend", "yes",
                                   "Pay out. I put in my years and I would like to see them."),
                     VoteRationale("cal_prop_cap_raise", "no",
                                   "Not until somebody shows me the actual financing. Dilution is real "
                                   "money out of my retirement, and I will not vote for it blind."),
                 ]),
    DelegatePage("cal_sue", intro="Quality and the CMM, eight years. I sit on the shop "
                 "committee with Marcus. If it leaves this building with our name on "
                 "it, it went past me first.",
                 topics=[TopicVisibility("Shop operations", "private")],
                 vote_rationales=[
                     VoteRationale("cal_prop_health", "rcv_1_2_3",
                                   "Plan A first. With a kid in braces, a low deductible is worth the "
                                   "higher premium every time."),
                     VoteRationale("cal_prop_picnic", "approval_2",
                                   "Riverside. Real room for the families and a playground for the "
                                   "little ones."),
                 ]),
]


# ---------------------------------------------------------------------------
# Follows + persona delegations.
# ---------------------------------------------------------------------------
FOLLOWS = [
    FollowSeed("cal_jess", "cal_marcus", "approved", "delegation_allowed"),
    FollowSeed("cal_dev", "cal_marcus", "approved", "delegation_allowed"),
    FollowSeed("cal_priya", "cal_walt", "approved", "delegation_allowed"),
    FollowSeed("cal_lorna", "cal_ruth", "approved", "delegation_allowed"),
    FollowSeed("cal_gary", "cal_tom", "approved", "delegation_allowed"),
]

PERSONA_DELEGATIONS = [
    # Jess (10 shares) rides Marcus on Equipment + Finances (strict precedence) —
    # quick-login as Jess shows a small vote riding a trusted senior machinist,
    # and Marcus's resolved influence on the dividend vote exceeds his own 540.
    PersonaDelegationSpec("cal_jess", "strict_precedence",
                          delegations=[("Equipment", "cal_marcus"), ("Finances", "cal_marcus")],
                          topic_precedence=["Finances", "Equipment"]),
    # Priya delegates shop operations to Walt, votes finances directly.
    PersonaDelegationSpec("cal_priya", "relevance_weighted",
                          delegations=[("Shop operations", "cal_walt")],
                          topic_precedence=["Shop operations"]),
]


CALDER_BIBLE = OrgBible(
    slug="calder-tool",
    display_name="Calder Tool & Machine Works",
    charter=(
        "A precision machine shop, employee owned since Walt sold the majority to "
        "the people who run the machines. We hold tolerances to a thousandth of an "
        "inch and we settle our arguments in dollars, out loud, in the open. Shares "
        "accrue with tenure, so the longer you stay and the harder you work, the "
        "more of this place is yours. The share register is open to every owner: "
        "anybody can see who holds what and how it got that way. Weighted votes for "
        "money decisions, one member one vote when it is about the people, and every "
        "cap raise argued on the floor before a single share moves."),
    tone_notes=(
        "Plainspoken shop-floor pragmatism. People who measure in thousandths and "
        "argue in dollars, and who would rather say a hard thing straight than "
        "dress it up. Genuine but low-drama disagreements: spend now versus save "
        "for the machine, the old guard who bled for their shares versus the "
        "apprentices just starting to earn theirs. Everybody trusts everybody to be "
        "arguing in good faith, even at their loudest. No corporate-speak, ever."),
    recent_history=(
        "Closed FY26 with the first real surplus in three years, off aerospace work "
        "the crew chased hard and delivered clean. The backlog is now past what one "
        "shift can turn, so a second-shift expansion is on the table, and riding "
        "with it the financing that raised the question of authorizing more shares. "
        "Walt sold most of the shop to its workers eight years ago; the dividend, "
        "the cap, and the shift are the biggest owner decisions since."),
    brand_color="#2F4A3E",
    voting_methods_used=["binary", "approval", "rcv"],
    quorum_threshold_default=0.35,
    elections_enabled=True,
    filler_count=0,  # the 14 named owners are the whole weighted cast
    weighted_config={
        "enabled": True,
        "unit_label": "shares",
        "show_event_parties": True,
        "transfers_enabled": True,
        "issuance_mode": "member_vote",
        "authorized_total": 10000,
        "allow_per_member_proposals": True,
    },
    members=MEMBERS,
    titles=TITLES,
    distribution_rules=DISTRIBUTION_RULES,
    ledger_seed=LEDGER_SEED,
    proposals=PROPOSALS,
    drafts=DRAFTS,
    comments=COMMENTS,
    delegate_pages=DELEGATE_PAGES,
    follows=FOLLOWS,
    persona_delegations=PERSONA_DELEGATIONS,
)
