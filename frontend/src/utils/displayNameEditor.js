export function displayNameSettingsPath(slug) {
  return `/settings?displayNameOrg=${encodeURIComponent(slug)}#display-names`;
}

export function displayNameTargetFromSearch(search, orgs = []) {
  const requested = new URLSearchParams(search).get('displayNameOrg');
  return requested && orgs.some(org => org.slug === requested) ? requested : 'default';
}

/** Small coordinator that makes selection changes invalidate stale saves. */
export function createDisplayNameSaveCoordinator() {
  let generation = 0;
  let controller = null;
  let target = 'default';
  return {
    begin(nextTarget) {
      controller?.abort();
      controller = new AbortController();
      generation += 1;
      target = nextTarget;
      const mine = generation;
      return {
        signal: controller.signal,
        isCurrent: () => mine === generation && target === nextTarget,
      };
    },
    cancel(nextTarget = target) {
      controller?.abort();
      controller = null;
      generation += 1;
      target = nextTarget;
    },
  };
}
