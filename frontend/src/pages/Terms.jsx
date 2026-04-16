export default function Terms() {
  return (
    <div className="min-h-screen bg-[#F8F9FA]">
      <div className="max-w-3xl mx-auto px-4 py-12">
        <h1 className="text-3xl font-bold text-[#1B3A5C] mb-8">Terms of Service</h1>

        <div className="prose prose-sm max-w-none text-[#2C3E50] space-y-6">
          <p className="text-gray-500 text-sm">
            Last updated: April 2026. This is a template for self-hosted instances. Organization administrators should customize these terms to reflect their specific needs.
          </p>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">What This Platform Is</h2>
            <p>
              Liquid Democracy is an open-source tool for organizational decision-making. It allows members of an organization to vote directly on proposals or delegate their voting power to trusted individuals on specific topics. It is designed for internal governance of clubs, associations, and civic organizations.
            </p>
            <p>
              This platform is <strong>not</strong> a legally binding election system. Decisions made through this platform carry the authority that your organization chooses to grant them.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">User Responsibilities</h2>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Accurate identity:</strong> Use your real identity as recognized by your organization. Do not create multiple accounts.</li>
              <li><strong>No manipulation:</strong> Do not attempt to manipulate votes through technical means, coercion, or vote-buying.</li>
              <li><strong>Respect:</strong> Treat other members with respect in all interactions on the platform.</li>
              <li><strong>Security:</strong> Keep your account credentials secure. Do not share your password or allow others to vote on your behalf outside the delegation system.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Organization Admin Responsibilities</h2>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Fair governance:</strong> Administer the platform fairly and transparently.</li>
              <li><strong>Member rights:</strong> Respect members' right to vote, delegate, and change their delegations at any time.</li>
              <li><strong>Data stewardship:</strong> Handle member data responsibly in accordance with the Privacy Policy.</li>
              <li><strong>Clear communication:</strong> Ensure proposals are clearly written and that members have adequate time to deliberate and vote.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Platform Availability</h2>
            <p>
              This platform is provided on a best-effort basis. For self-hosted instances, availability depends on the hosting organization's infrastructure. There is no uptime guarantee. We recommend organizations maintain regular database backups.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Open Source License</h2>
            <p>
              This software is released under the MIT License. You are free to use, modify, and distribute it. The source code is available on GitHub.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-[#1B3A5C] mt-8 mb-3">Changes to These Terms</h2>
            <p>
              Organization administrators may update these terms at any time. Members will be notified of significant changes.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
