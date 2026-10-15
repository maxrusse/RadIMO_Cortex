/**
 * Live assignment surroundings: prominent result with clipboard status and a
 * short history of the last assignments made on this PC (localStorage only).
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'radimo.live.history';
  const MAX_ENTRIES = 5;

  function t(text) {
    return window.RadimoI18n?.t ? window.RadimoI18n.t(text) : text;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function abbreviationOf(person) {
    const match = String(person || '').match(/\(([^)]+)\)\s*$/) || String(person || '').match(/\(([^)]+)\)/);
    return match ? match[1] : '';
  }

  function load() {
    try {
      const entries = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      return Array.isArray(entries) ? entries : [];
    } catch (error) {
      return [];
    }
  }

  function save(entries) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
    } catch (error) {
      // Private mode or quota: history is optional.
    }
  }

  async function copy(text) {
    if (!text) return false;
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      return false;
    }
  }

  function render() {
    const container = document.getElementById('liveHistory');
    if (!container) return;
    const entries = load();
    if (!entries.length) {
      container.innerHTML = `<div class="live-history__empty">${escapeHtml(t('No assignments on this PC yet.'))}</div>`;
      return;
    }
    container.innerHTML = entries.map((entry, index) => `
      <div class="live-history__row">
        <span class="live-history__time">${escapeHtml(entry.time)}</span>
        <span class="live-history__context">${escapeHtml(entry.context)}</span>
        <span class="live-history__person" title="${escapeHtml(entry.person)}">${escapeHtml(entry.person)}</span>
        ${entry.abbreviation ? `<button type="button" class="live-history__copy" data-history-copy="${index}" title="${escapeHtml(t('Copy abbreviation'))}">${escapeHtml(entry.abbreviation)} ⧉</button>` : '<span></span>'}
      </div>`).join('');
  }

  function setCopyStatus(ok, abbreviation) {
    const status = document.getElementById('liveCopyStatus');
    if (!status) return;
    status.className = `live-result__copy ${ok ? 'is-ok' : 'is-error'}`;
    status.textContent = ok
      ? `✓ ${abbreviation} ${t('copied')}`
      : `${t('Copy not possible')} · ${abbreviation}`;
  }

  /**
   * Show an assignment result and record it.
   * @param {{person: string, context: string}} result
   */
  async function showAssignment(result) {
    const person = result.person || t('Nobody available');
    const abbreviation = abbreviationOf(result.person);
    const time = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    const entries = load();
    entries.unshift({ time, context: result.context || '', person, abbreviation });
    save(entries);
    render();
    if (abbreviation) setCopyStatus(await copy(abbreviation), abbreviation);
    return abbreviation;
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-history-copy]');
    if (!button) return;
    const entry = load()[Number(button.dataset.historyCopy)];
    if (!entry) return;
    const ok = await copy(entry.abbreviation);
    button.classList.toggle('is-copied', ok);
    setTimeout(() => button.classList.remove('is-copied'), 1200);
  });

  document.addEventListener('DOMContentLoaded', render);
  document.addEventListener('radimo:languagechange', render);

  window.LiveHistory = { showAssignment, render, abbreviationOf };
})();
