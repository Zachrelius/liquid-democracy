import { useId, useState } from 'react';
import { proposalBodyHtml, splitProposalLegalText } from '../utils/proposalBody';

const BODY_CLASSES = [
  'prose max-w-none text-[#2C3E50] text-sm leading-relaxed',
  '[&_p]:my-3 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0',
  '[&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold',
  '[&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:text-lg [&_h2]:font-semibold',
  '[&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-semibold',
  '[&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6 [&_li]:my-1',
  '[&_a]:text-[var(--brand-accent)] [&_a]:underline [&_a]:underline-offset-2',
].join(' ');

function MarkdownBody({ text, id }) {
  if (!text) return null;
  return (
    <div
      id={id}
      className={BODY_CLASSES}
      dangerouslySetInnerHTML={{ __html: proposalBodyHtml(text) }}
    />
  );
}

export default function ProposalBody({ body }) {
  const [expanded, setExpanded] = useState(false);
  const disclosureId = useId();
  const { hasLegalText, preamble, legalText } = splitProposalLegalText(body);

  if (!hasLegalText) return <MarkdownBody text={body} />;

  return (
    <section className="space-y-4">
      <MarkdownBody text={preamble} />
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={disclosureId}
        onClick={() => setExpanded(value => !value)}
        className="inline-flex min-h-11 items-center rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-accent)] focus-visible:ring-offset-2 print:hidden"
      >
        {expanded ? 'Hide full legal text' : 'Show full legal text'}
      </button>
      {expanded && <MarkdownBody id={disclosureId} text={legalText} />}
    </section>
  );
}
