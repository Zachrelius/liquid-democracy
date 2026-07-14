export function slugifyOrganizationName(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50);
}

export function parseInvitationEmails(text) {
  const seen = new Set();
  const valid = [];
  const invalid = [];

  text.split(/\r?\n/).forEach(raw => {
    const email = raw.trim().toLowerCase();
    if (!email) return;
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      invalid.push(raw.trim());
      return;
    }
    if (!seen.has(email)) {
      seen.add(email);
      valid.push(email);
    }
  });

  return { valid, invalid };
}

export function pendingSelectedTopics(topics, existingNames = [], completedNames = []) {
  const alreadyPresent = new Set(
    [...existingNames, ...completedNames].map(name => name.trim().toLowerCase()),
  );
  return topics.filter(topic => (
    topic.checked && !alreadyPresent.has(topic.name.trim().toLowerCase())
  ));
}
