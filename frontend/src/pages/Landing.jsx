import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';

export default function Landing() {
  return (
    <PublicLayout>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-white via-[#F8F9FA] to-[#EEF3F9] pointer-events-none" />
        <div className="relative max-w-5xl mx-auto px-6 pt-20 pb-16 sm:pt-28 sm:pb-24 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-gray-200 text-xs text-[var(--brand-accent)] font-medium shadow-sm mb-6">
            Open source · Pilot stage
          </div>
          <h1 className="text-4xl sm:text-6xl font-semibold text-[var(--brand-primary)] tracking-tight">
            Liquid Democracy
          </h1>
          <p className="mt-5 text-lg sm:text-xl text-[#2C3E50] max-w-2xl mx-auto leading-relaxed">
            Vote directly or delegate to people you trust, on every issue,
            any time. An open platform for liquid democracy.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              to="/demo"
              className="inline-flex items-center justify-center px-6 py-3 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] transition-colors shadow-sm w-full sm:w-auto"
            >
              Try the Demo
            </Link>
            <Link
              to="/about"
              className="inline-flex items-center justify-center px-6 py-3 bg-white text-[var(--brand-primary)] text-sm font-medium rounded-lg border border-gray-300 hover:border-[var(--brand-accent)] hover:text-[var(--brand-accent)] transition-colors w-full sm:w-auto"
            >
              About the Project
            </Link>
            <Link
              to="/login"
              className="inline-flex items-center justify-center px-6 py-3 text-[var(--brand-accent)] text-sm font-medium rounded-lg hover:underline w-full sm:w-auto"
            >
              Sign In
            </Link>
          </div>
        </div>
      </section>

      {/* Distinctives */}
      <section className="max-w-6xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Distinctive
            title="Topic-based delegation."
            body="Delegate your vote on healthcare to a doctor, economy to an economist, and vote directly on everything else."
          />
          <Distinctive
            title="Instant revocability."
            body="Change or revoke a delegation at any time, for any reason, without explanation."
          />
          <Distinctive
            title="Transparent accountability."
            body="Public delegates have public voting records; trust is earned, not assumed."
          />
          <Distinctive
            title="Multiple voting methods."
            body="Binary, approval, and ranked-choice voting — the method fits the decision."
          />
        </div>
      </section>
    </PublicLayout>
  );
}

function Distinctive({ title, body }) {
  return (
    <div className="p-6 bg-white rounded-xl border border-gray-200 shadow-sm hover:border-[var(--brand-accent)] transition-colors">
      <h3 className="text-base font-semibold text-[var(--brand-primary)] mb-2">{title}</h3>
      <p className="text-sm text-[#2C3E50] leading-relaxed">{body}</p>
    </div>
  );
}
