import renderMarkdown from './renderMarkdown.js';

const FULL_LEGAL_TEXT_HEADING = /^[ \t]*## Full legal text[ \t]*$/m;

export function splitProposalLegalText(body) {
  const source = body || '';
  const match = FULL_LEGAL_TEXT_HEADING.exec(source);
  if (!match) {
    return { hasLegalText: false, preamble: source, legalText: '' };
  }
  return {
    hasLegalText: true,
    preamble: source.slice(0, match.index).trimEnd(),
    legalText: source.slice(match.index).trimStart(),
  };
}

export function proposalBodyHtml(markdown) {
  if (!markdown) return '';
  // Existing renderer consumers add one surrounding paragraph. Proposal
  // bodies can contain real blocks, so split only the renderer's supported
  // headings/lists here and keep ordinary text in valid paragraph wrappers.
  const lines = markdown.split('\n');
  const blocks = [];
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${renderMarkdown(paragraph.join('\n'))}</p>`);
    paragraph = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.trim()) {
      flushParagraph();
      continue;
    }
    if (/^#{1,3} .+/.test(line)) {
      flushParagraph();
      blocks.push(renderMarkdown(line));
      continue;
    }
    if (/^[-*] .+/.test(line)) {
      flushParagraph();
      const listLines = [line];
      while (index + 1 < lines.length && /^[-*] .+/.test(lines[index + 1])) {
        listLines.push(lines[index + 1]);
        index += 1;
      }
      blocks.push(renderMarkdown(listLines.join('\n')));
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  return blocks.join('');
}
