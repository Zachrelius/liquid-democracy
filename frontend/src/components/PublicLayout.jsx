import { Link } from 'react-router-dom';

/**
 * Minimal chrome for unauthenticated public pages (Landing, About, Demo).
 * No nav, no email verification banner — just the page content and a
 * small shared footer.
 */
export default function PublicLayout({ children }) {
  return (
    <div className="min-h-screen flex flex-col bg-[#F8F9FA]">
      <div className="flex-1">{children}</div>
      <footer className="border-t border-gray-200 bg-white">
        <div className="max-w-6xl mx-auto px-6 py-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm text-gray-500">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[var(--brand-primary)]">Liquid Democracy</span>
            <span className="text-gray-300">·</span>
            <span className="text-xs">open source</span>
          </div>
          <div className="flex items-center gap-5">
            <a
              href="https://github.com/Zachrelius/liquid-democracy"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-[var(--brand-accent)] hover:underline"
            >
              GitHub
            </a>
            {/* Phase 43 Cluster H — surface Help in the only public chrome. */}
            <Link to="/help" className="hover:text-[var(--brand-accent)] hover:underline">
              Help
            </Link>
            <Link to="/why" className="hover:text-[var(--brand-accent)] hover:underline">
              Why
            </Link>
            <Link to="/security" className="hover:text-[var(--brand-accent)] hover:underline">
              Security & Trust
            </Link>
            <Link to="/privacy" className="hover:text-[var(--brand-accent)] hover:underline">
              Privacy
            </Link>
            <Link to="/terms" className="hover:text-[var(--brand-accent)] hover:underline">
              Terms
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
