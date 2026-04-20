(function() {
  const WORKER_SORT_TITLES = new Set(['dr', 'pd', 'prof', 'med', 'dent', 'dipl', 'ing', 'dipl-ing']);
  const WORKER_SORT_PARTICLES = new Set(['von', 'van', 'de', 'del', 'der', 'den', 'zu', 'zum', 'zur']);

  function getDisplayStyle() {
    return String(window.WORKER_NAME_DISPLAY_STYLE || 'first_last_id').toLowerCase();
  }

  function extractLabelAndId(name) {
    const raw = (name == null ? '' : String(name)).trim();
    if (!raw) return { raw: '', cleaned: '', workerId: '' };
    const match = raw.match(/\(([^()]+)\)\s*$/);
    const workerId = match ? match[1].trim() : '';
    const cleaned = raw.replace(/\s*\([^)]*\)\s*$/, '').replace(/\s+/g, ' ').trim();
    return { raw, cleaned, workerId };
  }

  function cleanTokens(value) {
    return String(value || '')
      .split(' ')
      .map(token => token.trim().replace(/^[,.;:()[\]{}]+|[,.;:()[\]{}]+$/g, ''))
      .filter(Boolean)
      .filter(token => !WORKER_SORT_TITLES.has(token.toLowerCase()));
  }

  function splitNameParts(name) {
    const { cleaned } = extractLabelAndId(name);
    if (!cleaned) return { surname: '', given: '' };

    if (cleaned.includes(',')) {
      const parts = cleaned.split(',', 2);
      const surname = cleanTokens(parts[0]).join(' ').trim() || parts[0].trim();
      const given = cleanTokens(parts[1] || '').join(' ').trim() || (parts[1] || '').trim();
      return { surname, given };
    }

    const tokens = cleanTokens(cleaned);
    if (!tokens.length) return { surname: cleaned, given: '' };
    if (tokens.length === 1) return { surname: tokens[0], given: '' };

    let surnameStart = tokens.length - 1;
    const last = tokens[tokens.length - 1].toLowerCase();
    const penultimate = tokens[tokens.length - 2].toLowerCase();
    if (WORKER_SORT_PARTICLES.has(penultimate) || (WORKER_SORT_PARTICLES.has(last) && tokens.length >= 2)) {
      surnameStart = tokens.length - 2;
    }
    return {
      surname: tokens.slice(surnameStart).join(' ').trim(),
      given: tokens.slice(0, surnameStart).join(' ').trim(),
    };
  }

  function formatDisplayName(name, workerId = '') {
    const { raw, cleaned, workerId: embeddedId } = extractLabelAndId(name);
    const explicitId = extractLabelAndId(workerId).workerId || String(workerId || '').trim();
    const resolvedId = String(explicitId || embeddedId || '').trim();
    const { surname, given } = splitNameParts(cleaned || name);
    const style = getDisplayStyle();
    let base;
    if (style === 'raw') {
      return raw || resolvedId;
    } else if (surname && given && style === 'last_first_id') {
      base = `${surname}, ${given}`;
    } else if (surname && given) {
      base = `${given} ${surname}`;
    } else {
      base = surname || cleaned || resolvedId;
    }
    if (resolvedId && !base.includes(`(${resolvedId})`)) {
      return `${base} (${resolvedId})`;
    }
    return base;
  }

  function buildSortKey(name) {
    const raw = (name == null ? '' : String(name)).trim();
    if (!raw) return '';
    const { cleaned } = extractLabelAndId(raw);
    if (!cleaned) return raw.toLowerCase();

    if (cleaned.includes(',')) {
      const parts = cleaned.split(',', 2);
      const last = cleanTokens(parts[0]).join(' ').toLowerCase() || parts[0].trim().toLowerCase();
      const first = cleanTokens(parts[1] || '').join(' ').toLowerCase() || (parts[1] || '').trim().toLowerCase();
      const full = `${last} ${first}`.trim();
      return `${last}|${first}|${full}`;
    }

    const tokens = cleaned
      .split(' ')
      .map(token => token.trim().replace(/^[,.;:()[\]{}]+|[,.;:()[\]{}]+$/g, ''))
      .filter(Boolean)
      .filter(token => {
        const normalized = token.toLowerCase();
        return !WORKER_SORT_TITLES.has(normalized) && !WORKER_SORT_PARTICLES.has(normalized);
      });

    if (!tokens.length) {
      const fallback = cleaned.toLowerCase();
      return `${fallback}|${fallback}`;
    }

    const last = tokens[tokens.length - 1].toLowerCase();
    const first = tokens.slice(0, -1).join(' ').toLowerCase();
    const full = tokens.join(' ').toLowerCase();
    return `${last}|${first}|${full}`;
  }

  window.WorkerNameUtils = {
    getDisplayStyle,
    extractLabelAndId,
    cleanTokens,
    splitNameParts,
    formatDisplayName,
    buildSortKey,
  };
})();
