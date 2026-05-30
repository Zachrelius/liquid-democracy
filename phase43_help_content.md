# Phase 43 — Help Content Artifact

**Purpose.** This is the planning-agent-authored copy for the three new "getting started" help pages in Phase 43 (Cluster C). The Code team wires this copy **verbatim** into the new help pages mirroring the existing help-page pattern (`max-w-3xl mx-auto`, `<HelpBackLink />`, h1 + subtitle, white `<section>` cards). The Code team does **not** rewrite or improvise help copy.

**Screenshots.** Each `[SCREENSHOT: …]` marker below describes exactly what to capture and where. The frontend dev captures these against the **Cedar Hollow demo org** during build (sign in as a demo persona — Janet Reilly for steward/admin shots, any member for member shots), crops to the relevant UI, and places them inline where the marker sits. Keep images reasonably sized; no real user data exists but capture demo-only regardless.

**Voice.** Warm, plain, task-oriented, mixed-audience (not admin-biased). Short sentences. Second person ("you"). No jargon without a one-line gloss.

**Routes (for the dev):**
- `/help/getting-started-member` → page 1 below
- `/help/getting-started-steward` → page 2 below
- `/help/getting-started-delegate` → page 3 below

All three are public routes (non-sensitive, useful before sign-in) and are linked from the `/help` hub under a "Getting started" group.

---

# Page 1 — Getting started as a member

**Route:** `/help/getting-started-member`
**Page title (h1):** Getting started as a member
**Subtitle:** You've joined an organization — here's how to take part.

### Section — What this platform is for

Your organization makes decisions here together. Anyone can weigh in on a proposal by voting directly. And for the topics you'd rather not track closely, you can hand your vote to someone you trust — a delegate — who votes on your behalf. You stay in control: you can change or take back a delegation at any time, and you can always step in and vote yourself.

That's the whole idea of liquid democracy: vote directly when you want to, delegate when you don't, on a topic-by-topic basis.

### Section — Find what's being decided

Open the **Proposals** tab to see everything your organization is working on. Each proposal moves through stages, and you can filter by them:

- **Deliberation** — the discussion phase. The proposal is being shaped; you can read it and join the conversation before voting opens.
- **Voting** — voting is open. Cast your vote before the deadline shown on the proposal.
- **Passed / Failed** — decided. You can see the outcome and how the vote went.

Each proposal shows who wrote it, the topics it touches, how many votes have been cast, and how much time is left.

[SCREENSHOT: The Proposals list in Cedar Hollow showing the All/Deliberation/Voting/Passed/Failed filter row and two or three proposal cards with their vote tallies and "time remaining". Capture at /demo-cedar-hollow/proposals.]

### Section — Cast your vote

Open any proposal that's in **Voting**. Depending on how the proposal is set up, you'll choose **Approve**, **Reject**, or **Abstain** (some proposals offer more options, like approval or ranked-choice — the proposal will show you what's available). Pick your choice and select **Submit Vote**.

Changed your mind? As long as voting is still open, you can select **Change Vote** and update it.

[SCREENSHOT: A single proposal detail in the Voting stage showing the Approve / Reject / Abstain buttons and the Submit Vote button. Capture at a /demo-cedar-hollow proposal that is in Voting.]

### Section — Join the discussion

Proposals have a comment section. Before voting opens — and while it's open — you can post your thoughts, ask questions, and read what your neighbors or colleagues are saying. Good decisions usually start with good discussion, so this is where a lot of the real work happens.

### Section — Delegate your vote (optional)

You won't have an opinion on everything, and that's fine. Open **Delegates** to browse the people in your organization accepting delegations — each one shows a short bio, the topics they cover, and how many people already delegate to them. Then open **My Delegations**, find a topic, and select **Set Delegate** to choose who votes for you on it. You can pick a different delegate for each topic, and optionally a default delegate for topics you haven't assigned.

Two things worth knowing:

- **It's per topic.** You might delegate "Budget" to one person and vote on everything else yourself.
- **You're always in control.** Your delegate's vote applies until you change or revoke it — and if you vote directly on a specific proposal, your direct vote overrides the delegation just for that one.

[SCREENSHOT: The Browse Delegates page in Cedar Hollow showing a couple of delegate cards (bio, topic tags, delegator count, View Profile). Capture at /demo-cedar-hollow/delegates.]

### Section — Stay in the loop

The bell icon in the top bar shows your **Notifications** — new proposals, approaching deadlines, and activity that involves you. You can tune what you're notified about in your account settings.

### Section — Where to go next

- Curious how the different voting methods work? See [Voting methods](/help/voting-methods).
- Want to understand delegates more deeply before you delegate? See [Public delegates](/help/public-delegates).
- Thinking about representing others yourself? See [Getting started as a delegate](/help/getting-started-delegate).

---

# Page 2 — Getting started as a steward

**Route:** `/help/getting-started-steward`
**Page title (h1):** Getting started as a steward
**Subtitle:** You've created an organization — here's how to set it up.

### Section — Welcome — you're the steward

You just created an organization, which makes you its first administrator (its "steward"). Right now it's an empty space. This page walks you through the handful of steps that turn it into a place your members can actually deliberate and decide. You don't have to do all of it at once — set up the essentials, invite a few people, and grow from there.

Everything below lives under the **Admin** menu in the top bar.

[SCREENSHOT: The Admin dropdown menu open, showing Org Settings, Permissions, Members, Proposals, Topics, etc. Capture as Janet Reilly at /demo-cedar-hollow with the Admin menu open.]

### Section — Step 1: Set up your organization

Open **Admin → Org Settings**. Give your organization a clear description so members and prospective members know what it's for. This is also where you control your **join policy** — whether people join by invitation only, by requesting approval, or freely — and other organization-wide settings.

### Section — Step 2: Create your topics

Open **Admin → Topics**. Topics are the subject areas your organization makes decisions about — things like Budget, Governance, or Events. They do two important jobs: they organize your proposals, and they're the unit people delegate on (a member can delegate "Budget" to one person and vote on everything else themselves).

Start with a small, clear set of topics that match how your group actually thinks about its decisions. You can always add or adjust them later. (We deliberately don't pre-fill topics for you — the right set depends on your organization, and a short, accurate list beats a long, generic one.)

### Section — Step 3: Invite your members

Open **Admin → Members** to invite people in, and **Admin → Permissions** to decide who can do what — for example, who else can administer the organization, who can create proposals, and who reviews delegate applications. Most organizations start with a small set of administrators and open proposal-creation to members; you can tighten or loosen this as you learn what works.

### Section — Step 4: Post your first proposal

A proposal is any decision you want the group to weigh in on. Select **Create proposal** (on the Proposals page or under **Admin → Proposals**), describe what's being decided, attach the relevant topic, and choose how it should be voted on. A good first proposal is something real but low-stakes — it gives everyone a chance to learn the flow before anything important is on the line.

### Section — Step 5 (optional): Set up delegates

Part of what makes this platform different is that members can delegate their vote, by topic, to people they trust. If your organization wants public delegates — members who openly represent others on certain topics — you'll review their applications under **Admin → Delegate Applications**. You can point prospective delegates to [Getting started as a delegate](/help/getting-started-delegate).

### Section — A note on growing into it

The **Admin** menu has more than these five steps — Analytics, Polises (group-opinion discussions), Sub-Organizations, and more. You don't need any of it on day one. Set up topics, invite a few people, run one real decision, and let the rest follow as your organization finds its rhythm.

### Section — Where to go next

- [Organizations](/help/organizations) — how organizations and membership work.
- [Role permissions](/help/role-permissions) — the permission system in detail.
- [Voting methods](/help/voting-methods) — choosing the right method for a decision.

---

# Page 3 — Getting started as a delegate

**Route:** `/help/getting-started-delegate`
**Page title (h1):** Getting started as a delegate
**Subtitle:** People can hand you their vote on the topics you know best — here's how to represent them well.

### Section — What it means to be a delegate

A delegate is a member who other members trust to vote on their behalf, topic by topic. If you're knowledgeable or engaged on, say, Budget or infrastructure questions, neighbors or colleagues can delegate those topics to you — your vote then counts for them until they change their mind. It's a real responsibility, and the platform is built so that it's earned through transparency, not just assigned.

You manage all of this from **My Delegate Page** (in the menu under your name, top right).

[SCREENSHOT: The "My Delegate Page" editing view for a delegate, showing the intro/profile area and the per-topic sections. Capture as Janet Reilly at /demo-cedar-hollow/delegate-profile.]

### Section — Step 1: Write your introduction

On your delegate page, start with a short introduction — who you are and how you approach decisions in this organization. This is the first thing a prospective delegator reads, so be honest and specific. "Cedar Court resident, structural engineer, I read every proposal carefully" tells people far more than "experienced and trustworthy."

### Section — Step 2: Choose your topics and set their visibility

You decide which topics you represent, and how visible each one is. Each topic has four visibility settings:

- **Private (only me)** — only you can see your activity on this topic. Use this while you're preparing.
- **Visible to my approved followers in this org** — a middle step: people who already follow you can see it, but it isn't public yet.
- **Public — transparent only** — your voting record on this topic is visible to everyone, but you're not accepting new delegations. Transparency without obligation.
- **Public — accepting delegation** — your record is visible *and* you're open to representing others on this topic.

You can be accepting delegation on Budget while keeping another topic private. Moving a topic to **Public — accepting delegation** uses the **Submit for approval** button and goes through your organization's approval gate, if one is configured (administrators review delegate applications).

### Section — Step 3: Add a position statement

For each topic you represent, you can write a position statement — a short summary of where you stand and how you'll weigh decisions. This helps people decide whether to delegate to you, and it holds you accountable to what you said. Treat it like a small platform you're running on.

### Section — Step 4: Explain your votes

This is what makes delegation trustworthy. For your votes on public topics, you can attach a **rationale** — a brief note on why you voted the way you did. Your delegators (and anyone viewing your page) can see it. You don't have to explain every vote, but the more you do, the more your record reads as "here's someone who thinks carefully," which is exactly what earns delegations.

### Section — Step 5: Represent well, and keep it current

Once you're public and accepting, members can delegate their topics to you from your profile, and you'll start voting on their behalf. A few habits that matter:

- **Vote consistently** with the positions you published.
- **Keep explaining** the consequential votes.
- **Remember they can leave.** Delegators can change or revoke at any time, and they can always override you by voting directly. Your influence lasts exactly as long as their trust does.

### Section — Where to go next

- [Public delegates](/help/public-delegates) — the full picture of how public delegate pages, visibility, and approval work.
- [Getting started as a member](/help/getting-started-member) — the basics, if you also want a refresher on voting and delegating.
