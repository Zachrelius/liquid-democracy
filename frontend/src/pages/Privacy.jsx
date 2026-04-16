export default function Privacy() {
  return (
    <div className="min-h-screen bg-[#F8F9FA]">
      <div className="max-w-3xl mx-auto px-4 py-12">
        <h1 className="text-3xl font-bold text-[#1B3A5C] mb-8">Privacy Policy</h1>

        <div className="prose prose-sm max-w-none text-[#2C3E50] space-y-6">
          <p className="text-gray-500 text-sm">
            Last updated: April 2026. This is a template policy for self-hosted instances. Organization administrators should customize this to reflect their specific practices.
          </p>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">What Data We Collect</h2>
            <p>When you create an account and use this platform, we collect:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Account information:</strong> username, display name, email address, and a securely hashed password.</li>
              <li><strong>Votes:</strong> your vote on each proposal (yes, no, or abstain), whether you voted directly or via delegation.</li>
              <li><strong>Delegations:</strong> who you delegate to and on which topics.</li>
              <li><strong>Audit logs:</strong> a record of actions you take (voting, delegating, changing settings) for transparency and accountability.</li>
              <li><strong>Technical data:</strong> IP addresses in server logs for security purposes.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">How Data Is Stored</h2>
            <ul className="list-disc pl-6 space-y-1">
              <li>All data is stored in a PostgreSQL database managed by your organization.</li>
              <li>Passwords are hashed using bcrypt and are never stored in plain text.</li>
              <li>Data in transit is encrypted via HTTPS.</li>
              <li>The platform is self-hosted -- your data stays on infrastructure controlled by your organization.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Who Can See Your Data</h2>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Your votes</strong> are private by default. Only approved followers and public delegate topics make votes visible.</li>
              <li><strong>Your delegations</strong> are visible to your delegates (they can see that you delegate to them).</li>
              <li><strong>Public delegates</strong> have their votes visible on topics where they registered as a public delegate.</li>
              <li><strong>Organization admins</strong> can view aggregate analytics and audit logs, but cannot see individual votes unless they have a follow relationship with you.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Data Retention</h2>
            <p>
              Your data is retained for as long as your account is active. Audit logs are retained indefinitely for organizational transparency. Closed proposals and their vote records are kept as a permanent record of decisions.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Data Export</h2>
            <p>
              You can request a copy of all data associated with your account by contacting your organization administrator. We support data portability.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Account Deletion</h2>
            <p>
              You can request deletion of your account and associated data by contacting your organization administrator. Upon deletion, your personal information is removed, though anonymized vote records may be retained for the integrity of past decisions.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Third-Party Sharing</h2>
            <p>
              We do not share your data with any third parties. There are no analytics trackers, advertising networks, or data brokers. This platform is entirely self-hosted and self-contained.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Contact</h2>
            <p>
              For privacy questions or data requests, contact your organization administrator.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
