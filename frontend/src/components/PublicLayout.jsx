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
            <span className="font-semibold text-[#1B3A5C]">Liquid Democracy</span>
            <span className="text-gray-300">·</span>
            <span className="text-xs">open source</span>
          </div>
          <div className="flex items-center gap-5">
            <a
              href="https://github.com/Zachrelius/liquid-democracy"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-[#2E75B6] hover:underline"
            >
              GitHub
            </a>
            <Link to="/privacy" className="hover:text-[#2E75B6] hover:underline">
              Privacy
            </Link>
            <Link to="/terms" className="hover:text-[#2E75B6] hover:underline">
              Terms
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
