/**
 * Shared page shell behaviour.
 *
 * - Closes the Administration menu on outside click or Escape.
 * - RadimoUI.setDirty(scope, count): registers unsaved edits for a page area.
 *   Elements with data-dirty-for="<scope>" show the count; the browser asks
 *   before leaving while any scope has unsaved edits.
 */
(function () {
  'use strict';

  const dirtyScopes = new Map();

  function t(text) {
    return window.RadimoI18n?.t ? window.RadimoI18n.t(text) : text;
  }

  function renderDirty(scope) {
    const count = dirtyScopes.get(scope) || 0;
    document.querySelectorAll(`[data-dirty-for="${scope}"]`).forEach(element => {
      element.hidden = count === 0;
      const label = count === 1 ? t('1 unsaved change') : `${count} ${t('unsaved changes')}`;
      element.textContent = label;
    });
  }

  function setDirty(scope, count) {
    const value = Math.max(0, Number(count) || 0);
    if (value) {
      dirtyScopes.set(scope, value);
    } else {
      dirtyScopes.delete(scope);
    }
    renderDirty(scope);
  }

  function hasDirty() {
    return dirtyScopes.size > 0;
  }

  window.addEventListener('beforeunload', event => {
    if (!hasDirty()) return;
    event.preventDefault();
    event.returnValue = '';
  });

  document.addEventListener('click', event => {
    document.querySelectorAll('details.system-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.removeAttribute('open');
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('details.system-menu[open]').forEach(menu => {
      menu.removeAttribute('open');
      menu.querySelector('summary')?.focus();
    });
  });

  window.RadimoUI = { setDirty, hasDirty };
})();
