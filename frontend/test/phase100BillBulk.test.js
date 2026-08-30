import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import renderMarkdown, {
  safeMarkdownLinkDestination,
} from '../src/utils/renderMarkdown.js';
import {
  proposalBodyHtml,
  splitProposalLegalText,
} from '../src/utils/proposalBody.js';
import {
  aggregateBulkAdvanceResponses,
  bulkAdvanceSummaryMessage,
  chunkProposalIds,
  visibleDraftProposalIds,
} from '../src/utils/bulkDeliberation.js';

function source(relativePath) {
  return readFileSync(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');
}

test('explicit HTTP(S) Markdown links render safely with new-tab isolation', () => {
  const bill = renderMarkdown(
    '[Bill page](https://malegislature.gov/Bills/194/S3029)',
  );
  const pdf = renderMarkdown(
    '[Official PDF](https://malegislature.gov/Bills/194/S3029.pdf)',
  );
  const http = renderMarkdown('[Archive](http://example.test/archive)');

  for (const rendered of [bill, pdf, http]) {
    assert.match(rendered, /target="_blank"/);
    assert.match(rendered, /rel="noopener noreferrer"/);
  }
  assert.match(bill, /href="https:\/\/malegislature\.gov\/Bills\/194\/S3029"/);
  assert.match(pdf, /S3029\.pdf/);
  assert.match(http, /href="http:\/\/example\.test\/archive"/);
});

test('link labels are escaped and cannot break surrounding markup', () => {
  const rendered = renderMarkdown(
    '[<Official & "reviewed">](https://example.test/source)',
  );
  assert.match(rendered, />&lt;Official &amp; "reviewed"&gt;<\/a>/);
  assert.doesNotMatch(rendered, /<Official/);
});

test('unsafe, relative, protocol-relative, malformed, and breakout links stay text', () => {
  const cases = [
    '[bad](javascript:alert)',
    '[bad](data:text/html,test)',
    '[bad](/relative)',
    '[bad](//example.test/path)',
    '[bad](https://example.test/" onmouseover="alert(1))',
    '[bad](https://example.test/(nested))',
    '[bad](https://example.test/unclosed',
    '[bad https://example.test)',
  ];
  for (const markdown of cases) {
    const rendered = renderMarkdown(markdown);
    assert.doesNotMatch(rendered, /<a\b/, markdown);
    assert.doesNotMatch(rendered, /<a[^>]+onmouseover=/, markdown);
  }
  assert.equal(safeMarkdownLinkDestination('javascript:alert(1)'), null);
  assert.equal(safeMarkdownLinkDestination('https://example.test/" bad'), null);
});

test('existing headings, emphasis, code, lists, and paragraphs remain supported', () => {
  const rendered = renderMarkdown(
    '# Heading\n\n**bold** *italic* `code`\n\n- one\n- two',
  );
  assert.match(rendered, /<h1>Heading<\/h1>/);
  assert.match(rendered, /<strong>bold<\/strong>/);
  assert.match(rendered, /<em>italic<\/em>/);
  assert.match(rendered, /<code>code<\/code>/);
  assert.match(rendered, /<ul><li>one<\/li>\n<li>two<\/li><\/ul>/);
  assert.match(rendered, /<\/p><p>/);
});

test('proposal legal text splits only at the first exact heading line', () => {
  const body = [
    '## Plain-language summary',
    '',
    'Short summary.',
    '',
    '  ## Full legal text  ',
    '',
    'Section 1.',
    '',
    '## Full legal text',
    'Second marker stays inside.',
  ].join('\n');
  const split = splitProposalLegalText(body);
  assert.equal(split.hasLegalText, true);
  assert.match(split.preamble, /Short summary\.$/);
  assert.match(split.legalText, /^## Full legal text/);
  assert.match(split.legalText, /Second marker stays inside\./);

  assert.equal(
    splitProposalLegalText('Text mentioning ## Full legal text inline').hasLegalText,
    false,
  );
  assert.equal(
    splitProposalLegalText('## Full Legal Text\nWrong capitalization').hasLegalText,
    false,
  );
});

test('overflow-only legal section still splits and ordinary bodies render in full', () => {
  const overflow = splitProposalLegalText(
    'Summary\n\n## Full legal text\n\nFull text was unavailable.',
  );
  assert.equal(overflow.hasLegalText, true);
  assert.match(overflow.legalText, /Full text was unavailable/);

  const ordinary = 'An ordinary proposal with **bold** text.';
  assert.deepEqual(splitProposalLegalText(ordinary), {
    hasLegalText: false,
    preamble: ordinary,
    legalText: '',
  });
  assert.match(proposalBodyHtml(ordinary), /^<p>An ordinary proposal/);
  assert.doesNotMatch(proposalBodyHtml('## Heading\n\nText'), /<p><h2>/);
  assert.equal(
    proposalBodyHtml('## Heading\nText without a blank line'),
    '<h2>Heading</h2><p>Text without a blank line</p>',
  );
});

test('501 selected IDs become exactly two deterministic bounded calls', () => {
  const ids = Array.from({ length: 501 }, (_, index) =>
    `00000000-0000-4000-8000-${String(500 - index).padStart(12, '0')}`,
  );
  const chunks = chunkProposalIds(ids);
  assert.equal(chunks.length, 2);
  assert.equal(chunks[0].length, 500);
  assert.equal(chunks[1].length, 1);
  assert.deepEqual(chunks.flat(), [...ids].sort((a, b) => a.localeCompare(b)));
  assert.deepEqual(chunkProposalIds([ids[0], ids[0]]), [[ids[0]]]);
});

test('draft visibility and aggregate result copy are stable', () => {
  assert.deepEqual(
    visibleDraftProposalIds([
      { id: 'draft-1', status: 'draft' },
      { id: 'vote-1', status: 'voting' },
      { id: 'draft-2', status: 'draft' },
    ]),
    ['draft-1', 'draft-2'],
  );
  const summary = aggregateBulkAdvanceResponses([
    {
      advanced: 487,
      already_in_deliberation: 8,
      ineligible_status: 3,
      not_found: 2,
      results: [{ proposal_id: 'a', result: 'advanced' }],
    },
  ]);
  assert.equal(summary.advanced, 487);
  assert.equal(summary.alreadyInDeliberation, 8);
  assert.equal(summary.couldNotAdvance, 5);
  assert.equal(
    bulkAdvanceSummaryMessage(summary),
    '487 advanced; 8 were already in deliberation; 5 could not be advanced.',
  );
});

test('proposal detail and management source preserve disclosure and bulk UX contracts', () => {
  const detail = source('pages/ProposalDetail.jsx');
  const body = source('components/ProposalBody.jsx');
  const management = source('pages/admin/ProposalManagement.jsx');

  assert.match(detail, /<ProposalBody body=\{proposal\.body\} \/>/);
  assert.doesNotMatch(detail, /renderMarkdown\(proposal\.body\)/);
  assert.match(body, /Show full legal text/);
  assert.match(body, /Hide full legal text/);
  assert.match(body, /aria-expanded=\{expanded\}/);
  assert.match(body, /aria-controls=\{disclosureId\}/);

  assert.match(management, /p\.status === 'draft'/);
  assert.match(management, /canAdvancePhase/);
  assert.match(management, /Select all loaded eligible proposals/);
  assert.match(management, /aria-expanded=\{expandedId === p\.id\}/);
  assert.match(management, /chunkProposalIds\(snapshot\)/);
  assert.match(management, /bulk-advance-to-deliberation/);
  assert.match(management, /Only proposals that are still drafts will move/);
  assert.match(management, /deliberation timing starts immediately/);
  assert.doesNotMatch(
    management,
    /for \([^)]*proposal[^)]*\)[\s\S]{0,300}\/proposals\/\$\{[^}]+\}\/advance/,
  );
});
