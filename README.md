# Liquid Democracy

**A free, open source voting platform for groups that make decisions together.**

🌐 **Live site:** [liquiddemocracy.us](https://www.liquiddemocracy.us/) · [Try the demos](https://www.liquiddemocracy.us/demo)

Liquid Democracy is built for unions, HOAs, tenant associations, student governments, employee-owned companies, and other groups that vote on things. Members can vote directly on a proposal or delegate by topic to someone they trust.

## What is liquid democracy?

Direct democracy asks everyone to vote on everything. Representative democracy hands your decisions to elected representatives. Liquid democracy lets you choose how to participate:

- **Vote directly** on decisions you care about.
- **Delegate by topic.** Someone you trust can handle budget questions while you vote on other topics yourself.
- **Change your mind.** You can change or revoke a delegation. While a proposal accepts votes, an eligible direct vote overrides your delegate for that proposal. Changes do not reopen a finalized result.

## Features

**Voting**
- Yes/no/abstain, approval (including multiple winners), and ranked choice (IRV or STV).
- Budget allocation and budget project voting.
- Experimental single-winner STAR, Score, Ranked Pairs, and Majority Judgment, each an organization opt-in and off by default.
- Configurable quorum, thresholds where applicable, deliberation and voting windows, write-ins, advisory pre-voting, and revision history.
- Optional stable-result requirements that check results over time and can extend voting. This is a closing rule, not a guarantee against strategic behavior.

**Delegation and deliberation**
- Topic-based delegation with configurable consent and fallback policies; organizations can disable delegation by topic.
- Public delegate profiles, position statements, and voting rationales.
- Interactive vote-flow graphs and round-by-round ranked-choice transfer charts.
- Threaded proposal comments and linked [Pol.is](https://pol.is/) conversations. Pol.is hosts the conversation; Liquid Democracy links it to proposals and supports participation through the integration.

**Governance**
- Editable roles and permission matrices, elected offices, fixed terms, and scheduled elections.
- Co-signed petitions, sub-organizations, weighted governance, and multi-admin approval for selected destructive actions.
- Single-steward and admin-council governance modes.
- Independent controls for joining, discovery, and activity visibility.

**Trust and privacy**
- Votes are private from other members by default, with visibility through permitted relationships and public-delegate activity. Operators can access the underlying database; this is not cryptographic secret-ballot anonymity.
- Ballot contents are redacted from ordinary audit responses. Exceptional platform-admin ballot-audit access requires a reason and is logged.
- Optional identity, age, and residency checks through [Didit](https://didit.me/). The platform stores results, derived hashes, provider references, and readable legal-name fields; it does not store raw ID images, selfies, or raw document numbers in its database. Didit processes verification materials under its own retention policy.

Read the hosted service's [Privacy Policy](https://www.liquiddemocracy.us/privacy) and [Security & Trust](https://www.liquiddemocracy.us/security) pages for the boundaries.

## Try it

Explore as fictional members without signing up. The [live demo directory](https://www.liquiddemocracy.us/demo) currently lists **Cedar Hollow HOA** and **Calder Tool & Machine Works**, with different governance setups. Demo content resets daily; the directory shows reset timing.

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL, Alembic.
- **Frontend:** React 19, Vite, Tailwind CSS, D3, Recharts.
- **Hosted service:** Railway, with transactional email via Resend.

## Running it yourself

Start with [DEPLOYMENT.md](DEPLOYMENT.md), [docker-compose.yml](docker-compose.yml), and [.env.example](.env.example). The deployment guide includes historical hosted-service instructions; check configuration against the current Compose file.

For a local installation:

1. Clone this repository and copy `.env.example` to `.env`.
2. Replace the database password and signing-key placeholders. Set `BASE_URL=http://localhost` and `CORS_ORIGINS=["http://localhost"]` for the default frontend port.
3. Configure working email delivery for subsequent account verification and notifications. Compose forwards the listed SMTP settings; optional provider and worker configuration may need additional wiring.
4. Review the resolved configuration locally, then start the services with `docker compose up --build -d`. The frontend uses port 80; the API uses port 8000.

On an empty database, the first registered account is automatically verified and becomes a platform administrator. Secure that first registration before exposing an installation publicly. See the deployment guide for configuration and operational details.

## Piloting

I'm looking for real organizations to pilot the platform. If your group might be interested, email **[z@liquiddemocracy.us](mailto:z@liquiddemocracy.us)** or visit the [live site](https://www.liquiddemocracy.us/).

## License

Licensed under the [MIT License](LICENSE), copyright 2026 Zachary Petertam. You can use, modify, distribute, and sell the software, including modified versions, subject to preserving the required copyright and license notices. Third-party components and externally sourced assets retain their respective terms and notices.
