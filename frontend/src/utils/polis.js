// Phase 81 — display label for a Polis discussion topic, with a stable
// fallback when the operator linked a bare pol.is conversation without
// entering a topic. Used across CreatePolis (success), PolisDetail (header +
// breadcrumb), Polis (voter header), Polises (list row), and LinkedPolisCard.
export function polisTopicLabel(polis) {
  const t = (polis?.title || '').trim();
  if (t) return t;
  const cid = (polis?.polis_conversation_id || '').trim();
  return cid ? `Linked pol.is conversation ${cid}` : 'Linked pol.is conversation';
}
