# Liquid Democracy Project Website — Multi-Agent Build Brief

## Project Purpose

Build a website that explains the liquid democracy concept, showcases the platform being developed, and invites people to get involved. This is a public-facing site, not the platform itself — think of it as the landing page and educational resource that convinces someone the idea is worth exploring.

The website won't be shared publicly until the platform is further along, but building it now serves two purposes: having the explanatory materials ready when needed, and testing the multi-agent workflow for future projects.

---

## Target Audience

Three distinct audiences, in priority order:

1. **Democracy reform advocates** — people already interested in fixing democracy who haven't encountered liquid democracy. They know about RCV, gerrymandering reform, campaign finance issues. They need to understand how liquid democracy is different from and potentially better than what they're already pushing for.

2. **General public / politically engaged citizens** — people frustrated with the current system but not deeply into reform policy. They need a clear, visceral "this is how government could actually work for you" message before any technical details.

3. **Potential contributors** — developers, designers, political scientists, organizers who might want to help build or deploy the platform. They need to see the technical foundation, the open-source approach, and understand where help is needed.

---

## Core Message

**"Make government accountable to you, not the billionaires and corporations."**

The site should make the case that:
- The current system is broken (but don't dwell here — people already feel this)
- Liquid democracy is a specific, concrete fix (not vague idealism)
- It's being built right now, with real software, inspired by real-world precedents
- You can be part of it

The tone should be: **serious but hopeful, direct but not angry, confident but not arrogant.** This is civic infrastructure, not a startup pitch. Avoid Silicon Valley language ("disrupt," "scale," "10x"). Avoid partisan framing — this is about democratic structure, not left vs. right.

---

## Site Structure

### Page 1: Home / Landing Page

**Hero section:**
- Headline that captures the core value proposition in one sentence
- Subheadline that explains liquid democracy in one more sentence
- A compelling visual — potentially an animated delegation graph showing votes flowing through a network, or a simple before/after comparison (current system vs. liquid democracy)
- Primary CTA: "See How It Works" (scrolls to explainer) or "Try the Demo" (links to platform when ready)

**"The Problem" section (brief):**
- 3-4 punchy statistics or statements about why the current system fails to represent people
- Not partisan — focus on structural issues (money in politics, two-party lock-in, low responsiveness to constituent preferences)
- Transition: "What if there was a better way?"

**"How Liquid Democracy Works" section:**
- This is the most important section on the entire site
- Explain the concept in plain language with visual aids
- Suggested structure:
  1. "You vote directly on the issues you care about" — show a person casting a vote on a proposal
  2. "On other issues, you choose someone you trust" — show delegation to a friend or expert
  3. "You can change your mind anytime" — show revocation and redelegation
  4. "Your delegate's votes are transparent" — show a voting record
  5. "It works on every issue, independently" — show topic-specific delegation
- Each point should have a simple illustration or animation
- End with: "That's it. You're always represented, always in control."

**"Real Precedents" section:**
- Brief mentions of Switzerland (direct democracy at scale), Taiwan (digital deliberation), Ireland (citizens' assemblies), Estonia (digital governance)
- Not deep dives — just enough to show this isn't purely theoretical
- "Learn more" links to a dedicated page or the research document

**"The Platform" section:**
- Screenshot or mockup of the actual platform (once Phase 2+ is presentable)
- Key features: topic-based delegation, transparent voting records, citizens' councils, graduated security
- "Open source and community-driven"
- CTA: "Try the Demo" or "View on GitHub"

**"Get Involved" section:**
- For advocates: "Join the movement" — link to reform organizations, mailing list signup
- For developers: "Help build it" — link to GitHub, contributing guide
- For organizations: "Run a pilot" — contact for civic organizations interested in trying the platform

**Footer:**
- Links to all pages
- GitHub link
- "Built with hope for democracy" or similar understated tagline

### Page 2: How It Works (Deep Dive)

A longer-form explainer with more detail than the homepage section:
- What is liquid democracy? (history, theory, comparison to representative and direct democracy)
- How does delegation work? (with diagrams)
- What about security? (graduated security model, honest about tradeoffs)
- What about manipulation? (delegation transparency, public delegate accountability)
- FAQ section addressing common objections:
  - "Won't most people just not participate?" 
  - "Can't this be gamed by influencers?"
  - "Is online voting secure enough?"
  - "How is this different from just having more referendums?"
  - "What about minority rights?"

### Page 3: The Reform Agenda

Connect liquid democracy to the broader reform landscape:
- Court reform and why it matters
- Campaign finance reform
- Citizens' councils
- National Popular Vote
- How liquid democracy fits into and strengthens all of these
- Links to reform organizations people can join now

### Page 4: About / The Project

- What this project is (open-source civic technology)
- Current status (demo, pilot, etc.)
- The team / contributors
- The research behind it (link to the comprehensive research document)
- How to contribute (GitHub, volunteering, funding)
- Contact

---

## Design Direction

**Visual identity:**
- Clean, authoritative, modern civic design
- Think: Brennan Center, Protect Democracy, or well-designed government websites — not tech startup landing pages
- Primary colors: deep navy, white, with a warm accent color (not red or blue to avoid partisan association — consider gold/amber, teal, or warm green)
- Typography: a distinctive but readable serif or semi-serif for headlines (suggesting authority and tradition), paired with a clean sans-serif for body text
- Generous whitespace, clear hierarchy, no clutter

**Visual elements:**
- The delegation graph / network visualization should be the signature visual motif — it's unique to liquid democracy and immediately communicates the concept
- Use simple iconography for the "how it works" section (not stock photos of diverse people smiling)
- Data visualizations where appropriate (the "problem" statistics section)
- Subtle animations on scroll — elements fading in, graphs drawing themselves — but restrained, not flashy

**What to avoid:**
- American flag imagery or overt patriotic styling (limits international applicability and feels partisan)
- Photos of politicians or political events
- Aggressive calls to action or urgency language ("Act NOW before it's too late!")
- Dark patterns, popups, email-gate (requiring email to access content)
- Cookie banners beyond what's legally required (don't track people on a democracy website)

---

## Technical Implementation

- **Static site** — no backend needed. HTML/CSS/JS or a simple framework like Astro, Next.js static export, or even plain HTML with Tailwind.
- **Performance priority** — fast load times, no heavy JavaScript bundles for what's essentially a content site
- **Accessible** — proper heading hierarchy, alt text, keyboard navigation, sufficient color contrast
- **Responsive** — must look good on mobile (many people will share links that are opened on phones)
- **SEO basics** — proper meta tags, Open Graph tags for social sharing, descriptive page titles
- Keep it deployable to any static hosting (GitHub Pages, Netlify, Vercel, Cloudflare Pages)

---

## Agent Roles

### Architect Agent
You own the overall vision, structure, and design decisions. Your responsibilities:
- Review the dev agent's work for design coherence, messaging clarity, and user experience
- Make decisions when the dev agent has questions about layout, content, or visual direction
- Write the actual copy/content for each section (headlines, body text, FAQ answers)
- Ensure the site tells a coherent story from top to bottom
- Flag issues to the dev agent with specific, actionable feedback

Before the dev agent starts building, you should produce:
1. Final copy for the homepage (all sections)
2. Wireframe descriptions or layout direction for each section
3. Color palette, font selections, and any specific design references
4. Content for at least the FAQ section of the How It Works page

### Dev Agent
You build the site based on the architect's direction. Your responsibilities:
- Set up the project (framework, build tools, deployment config)
- Implement the pages with the architect's copy and design direction
- Build any interactive elements (animations, the delegation graph visual, responsive navigation)
- Ensure accessibility and performance standards are met
- Flag technical constraints to the architect if a design request isn't feasible

### Test Agent
You verify the site works correctly across scenarios. Your responsibilities:
- Check all pages load without errors (browser console clean)
- Verify responsive design at key breakpoints (375px mobile, 768px tablet, 1440px desktop)
- Test navigation between all pages
- Verify all links work (no 404s, external links open in new tabs)
- Check accessibility: keyboard navigation through all interactive elements, heading hierarchy, color contrast
- Test performance: page load time, image optimization, no unnecessary large bundles
- Check Open Graph / social sharing meta tags render correctly
- Report issues with screenshots and specific descriptions

---

## Build Order

1. **Architect** produces homepage copy, design direction, and content for key sections
2. **Dev** sets up project and builds homepage
3. **Test** verifies homepage
4. **Architect** reviews and provides feedback
5. **Dev** iterates on feedback
6. **Architect** produces content for inner pages
7. **Dev** builds inner pages
8. **Test** full site test
9. **Architect** final review
10. All agents confirm ready for deployment (but don't deploy yet)

---

## Files and Structure

Keep the website project in a separate directory from the main liquid democracy platform:

```
liquid-democracy-website/
├── src/
│   ├── pages/
│   ├── components/
│   ├── styles/
│   └── assets/
├── public/
├── WEBSITE_PROGRESS.md    (separate from main project's PROGRESS.md)
├── package.json
└── README.md
```

Each agent should update WEBSITE_PROGRESS.md after completing their tasks.
